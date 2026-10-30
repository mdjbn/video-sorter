"""整理：按标签把视频移动到标签对应的目标文件夹。

安全性要求：
  · 先出预览（plan），前端确认后才执行；
  · 目标重名自动加 " (1)"、" (2)"…，绝不覆盖；
  · 同盘用 os.replace 原子改名，跨盘走"复制→校验大小→删除源"；
  · 每一步写 organize_logs，支持整批撤销。
"""
from __future__ import annotations

import errno
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database, now_iso
from .tasks import TaskRegistry


class OrganizeError(RuntimeError):
    pass


# ---------- 目标目录 ----------
def resolve_tag_dir(db: Database, cfg: Config, tag: dict[str, Any],
                    video_path: str | None = None) -> Path | None:
    """标签目标目录优先级：标签自定义 > 全局根目录/标签名 > 首个启用源目录/标签名 > 视频所在目录/标签名。"""
    custom = (tag.get("dir_path") or "").strip()
    if custom:
        return Path(custom).expanduser()
    root = (cfg.get("root_dir") or "").strip()
    if root:
        return Path(root).expanduser() / str(tag["name"])
    row = (db.query_one("SELECT path FROM sources WHERE enabled=1 AND COALESCE(kind,'')<>'upload' ORDER BY id LIMIT 1")
           or db.query_one("SELECT path FROM sources WHERE enabled=1 ORDER BY id LIMIT 1"))
    if row:
        return Path(row["path"]) / str(tag["name"])
    if video_path:
        return Path(video_path).parent / str(tag["name"])
    return None


def default_tag_dir(db: Database, cfg: Config, tag_name: str) -> str:
    root = (cfg.get("root_dir") or "").strip()
    if root:
        return str(Path(root).expanduser() / tag_name)
    row = (db.query_one("SELECT path FROM sources WHERE enabled=1 AND COALESCE(kind,'')<>'upload' ORDER BY id LIMIT 1")
           or db.query_one("SELECT path FROM sources WHERE enabled=1 ORDER BY id LIMIT 1"))
    if row:
        return str(Path(row["path"]) / tag_name)
    return ""


# ---------- 预览 ----------
def build_plan(db: Database, cfg: Config,
               tag_ids: list[int] | None = None,
               video_ids: list[int] | None = None) -> dict[str, Any]:
    sql = ("SELECT v.*, t.name AS tag_name, t.color AS tag_color, t.dir_path AS tag_dir "
           "FROM videos v JOIN tags t ON t.id = v.tag_id "
           "WHERE v.tag_id IS NOT NULL AND v.status IN ('idle','tagged')")
    params: list[Any] = []
    if tag_ids:
        sql += f" AND v.tag_id IN ({','.join('?' * len(tag_ids))})"
        params += list(tag_ids)
    if video_ids:
        sql += f" AND v.id IN ({','.join('?' * len(video_ids))})"
        params += list(video_ids)
    sql += " ORDER BY v.tag_id, v.filename"
    rows = [dict(r) for r in db.query(sql, params)]

    planned: set[str] = set()
    items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for v in rows:
        src = Path(v["path"])
        if not src.exists():
            skipped.append({"video_id": v["id"], "name": v["filename"], "reason": "文件不存在"})
            continue
        tag = {"name": v["tag_name"], "dir_path": v["tag_dir"]}
        tdir = resolve_tag_dir(db, cfg, tag, v["path"])
        if tdir is None:
            skipped.append({"video_id": v["id"], "name": v["filename"], "reason": "没有可用的目标目录"})
            continue
        if src.parent.resolve() == tdir.resolve():
            skipped.append({"video_id": v["id"], "name": v["filename"], "reason": "已在目标文件夹"})
            continue
        target = _unique_target(tdir, v["filename"], planned)
        planned.add(str(target).lower())
        items.append({
            "video_id": v["id"],
            "name": v["filename"],
            "size": v["size"],
            "duration": v["duration"],
            "tag_id": v["tag_id"],
            "tag_name": v["tag_name"],
            "tag_color": v["tag_color"],
            "from": str(src),
            "to": str(target),
            "dir": str(tdir),
            "renamed": target.name != v["filename"],
            "cross_device": _cross_device(src, tdir),
        })

    groups: dict[str, dict[str, Any]] = {}
    for it in items:
        g = groups.setdefault(it["dir"], {"dir": it["dir"], "tag_name": it["tag_name"],
                                          "tag_color": it["tag_color"], "count": 0, "bytes": 0})
        g["count"] += 1
        g["bytes"] += int(it["size"] or 0)
    return {
        "items": items,
        "skipped": skipped,
        "groups": list(groups.values()),
        "total": len(items),
        "total_bytes": sum(int(i["size"] or 0) for i in items),
        "renamed": sum(1 for i in items if i["renamed"]),
    }


def _unique_target(tdir: Path, filename: str, planned: set[str]) -> Path:
    target = tdir / filename
    if not target.exists() and str(target).lower() not in planned:
        return target
    stem, ext = os.path.splitext(filename)
    n = 1
    while True:
        cand = tdir / f"{stem} ({n}){ext}"
        if not cand.exists() and str(cand).lower() not in planned:
            return cand
        n += 1
        if n > 9999:
            raise OrganizeError("同名文件过多，无法生成唯一文件名")


def _cross_device(src: Path, dst_dir: Path) -> bool:
    try:
        src.parent.mkdir(parents=True, exist_ok=True)
        dst_dir.mkdir(parents=True, exist_ok=True)
        return os.stat(src).st_dev != os.stat(dst_dir).st_dev
    except OSError:
        return True


# ---------- 执行 ----------
def explain_error(e: Exception) -> str:
    """把底层的系统错误翻成用户能看懂的中文（Windows 上「文件被占用」最常见）。"""
    winerror = getattr(e, "winerror", None)
    busy = winerror == 32 or getattr(e, "errno", None) in (errno.EACCES, errno.EPERM, errno.EBUSY, errno.ETXTBSY)
    if isinstance(e, OSError) and busy:
        return "文件正被占用（可能正在播放，或被其他程序打开），请关闭播放器后重试"
    if isinstance(e, OSError) and getattr(e, "errno", None) == errno.ENOSPC:
        return "磁盘空间不足"
    return str(e) or e.__class__.__name__


def _move_with_retry(src: Path, dst: Path, attempts: int = 3, delay: float = 0.3) -> str:
    """Windows 上「文件正在播放」常常是瞬时的（播放器刚松开或 ffmpeg 正在退出），先重试几次再判失败。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return move_file(src, dst)
        except OSError as e:
            busy = getattr(e, "winerror", None) == 32 or getattr(e, "errno", None) in (
                errno.EACCES, errno.EPERM, errno.EBUSY, errno.ETXTBSY)
            if not busy or i == attempts - 1:
                raise
            last = e
            time.sleep(delay)
    raise last  # pragma: no cover — 上面一定已经 return 或 raise


# ---------- 可写性预检 ----------
def normalize_dir(path: str | Path) -> str:
    """把目录路径归一化成一个可比较的字符串键（解析 ~、绝对化、去掉尾部分隔符）。"""
    p = Path(path).expanduser()
    try:
        p = p.absolute()
    except OSError:  # pragma: no cover — absolute() 基本不会抛
        pass
    s = os.path.normpath(str(p))
    return s.rstrip("\\/") or s


def is_under(path: str | Path, root: str | Path) -> bool:
    """path 是否就是 root 或落在 root 之下（按路径分隔符边界比较）。"""
    p = normalize_dir(path).replace("\\", "/")
    r = normalize_dir(root).replace("\\", "/")
    if not r:
        return False
    return p == r or p.startswith(r.rstrip("/") + "/")


def _writable_reason(p: str, allow_missing: bool = False) -> tuple[bool, str]:
    """返回 (是否可写, 不可写原因)。只用 os.access，不在用户目录里创建探针文件。

    标签目录是整理时才按需创建的（默认「源目录/标签名」，整理前根本不存在），
    所以对标签目录传 allow_missing=True：目录还不存在时，看它最靠近的、**已经存在**的祖先目录
    能不能写 —— 能写就说明整理时 mkdir 得出来，算可写，不报。否则只要用户还没整理过，
    界面上就会满屏误报「目录不存在」。祖先目录不可写才是真问题（整理时一定会 Permission denied）。
    """
    try:
        if not os.path.exists(p):
            # 只有「源目录/上传目录」这种必须事先存在的路径才报「目录不存在」
            if not allow_missing:
                return False, "目录不存在"
            parent = os.path.dirname(p.rstrip("/\\")) or p
            for _ in range(16):  # 一路往上找第一个存在的祖先目录（标签目录一般就在源目录下一层）
                if os.path.isdir(parent):
                    ok, why = _writable_reason(parent)
                    return ok, why if not ok else ""
                nxt = os.path.dirname(parent.rstrip("/\\"))
                if not nxt or nxt == parent:
                    return False, "目录不存在"
                parent = nxt
            return False, "目录不存在"
        if not os.path.isdir(p):
            return False, "不是一个目录"
    except OSError as e:  # pragma: no cover — exists/isdir 很少抛
        return False, f"无法访问：{e}"
    try:
        if os.access(p, os.W_OK, effective_ids=True):
            return True, ""
        if os.access(p, os.W_OK):
            return True, ""
    except (OSError, NotImplementedError):  # pragma: no cover — 不支持 effective_ids 的平台
        pass
    return False, "服务用户没有写权限"


def check_roots_writable(db: Database, cfg: Config,
                         plan_items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """扫描/整理前预检：所有启用源目录 + 每个标签的目标目录是否可写。

    返回 [{"path","kind":"source"|"tag","reason"}]，按路径排序、同一路径只报一次。
    只读判断（os.access），不创建任何探针文件。

    传了 plan_items（整理计划）时只按计划项自己算出来的目标目录判定，不再拿标签的
    全局默认目录去猜 —— 计划项的 dir 就是 execute_plan 真正要写的地方，这样「剔掉哪几项」
    和「报哪个目录不可写」永远一致。
    """
    cand: dict[str, dict[str, Any]] = {}
    try:
        rows = db.query("SELECT path, COALESCE(kind,'') AS kind FROM sources WHERE enabled=1 ORDER BY id")
    except Exception:  # noqa: BLE001 — 预检失败不该挡住主流程
        rows = []
    for r in rows:
        candidates_add(cand, r["path"], "source")
    if plan_items is not None:
        for it in plan_items:
            candidates_add(cand, it.get("dir") or "", "tag")
    else:
        try:
            tag_rows = db.query("SELECT * FROM tags ORDER BY sort_order, id")
        except Exception:  # noqa: BLE001
            tag_rows = []
        for t in tag_rows:
            d = resolve_tag_dir(db, cfg, dict(t))
            if d is not None:
                candidates_add(cand, str(d), "tag")

    out: list[dict[str, Any]] = []
    # 源目录优先：同一个路径既是源又是标签目标时，按源判定（源目录不存在才是真问题）
    for key in sorted(cand, key=lambda k: (cand[k]["kind"] != "source", k)):
        kind = cand[key]["kind"]
        ok, reason = _writable_reason(key, allow_missing=(kind == "tag"))
        if not ok:
            out.append({"path": key, "kind": kind, "reason": reason})
    out.sort(key=lambda x: x["path"])
    return out


def candidates_add(cand: dict[str, dict[str, Any]], path: str, kind: str) -> None:
    raw = (path or "").strip()
    if not raw:
        return
    key = normalize_dir(raw)
    if not os.path.isabs(key):
        return  # 相对路径（没配 root_dir 时的兜底）不做预检，否则会误报
    cand.setdefault(key, {"kind": kind})


def _reason_owner(unwritable: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    """失败原因里常带完整路径（如 Permission denied: '/data/videos/x.mp4'），
    文件所在目录若是被预检报出来的不可写目录，就认为是它的锅。"""
    for u in unwritable:
        if u.get("path") and u["path"] in text:
            return u
    return None


def resolve_plan_unwritable(items: list[dict[str, Any]],
                            unwritable: list[dict[str, Any]]) -> dict[str, Any]:
    """把「目标目录落在不可写路径下」的计划项剔掉。

    返回 {"items": 保留的计划项, "dropped": [{"video_id","name","dir","path","reason"}],
          "paths": [涉及的不可写目录, 稳定排序]}。
    """
    keep: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    used: dict[str, dict[str, Any]] = {}
    for it in items:
        hit = next((u for u in unwritable
                    if is_under(it.get("dir") or it.get("to") or "", u["path"])), None)
        if hit is None:
            keep.append(it)
            continue
        used[hit["path"]] = hit
        dropped.append({"video_id": it.get("video_id"), "name": it.get("name"),
                        "dir": it.get("dir"), "path": hit["path"], "reason": hit["reason"]})
    return {"items": keep, "dropped": dropped, "paths": sorted(used)}


def skip_summary(dropped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按目录汇总被跳过的原因，前端可以直接显示。"""
    by: dict[str, dict[str, Any]] = {}
    for d in dropped:
        g = by.setdefault(d["path"], {"path": d["path"], "reason": d["reason"], "count": 0})
        g["count"] += 1
    return [by[k] for k in sorted(by)]


def move_file(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"目标已存在：{dst}")
    try:
        os.replace(src, dst)
        return "rename"
    except OSError:
        pass
    tmp = dst.with_name(dst.name + ".vsmoving")
    try:
        shutil.copy2(src, tmp)
        if tmp.stat().st_size != src.stat().st_size:
            raise OrganizeError(f"复制后大小不一致：{src.name}")
        os.replace(tmp, dst)
        src.unlink()
        return "copy"
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def summarize_outcome(moved: int, failed: list[dict[str, Any]]) -> tuple[str, str]:
    """整理结论 → (message, task_status)。

    · 一个都没移动、且有失败 → error（网页 Player.vue 的 `status === 'error'` 靠它提示）；
    · 部分成功 → 仍是 done，消息里写清已移动/失败条数；
    · 全部成功 → done；
    · 0 移动 0 失败（用户取消）→ done，保持原来的静默。
    """
    if moved == 0 and failed:
        reasons: list[str] = []
        for f in failed:
            r = str(f.get("error") or "").strip()
            if r and r not in reasons:
                reasons.append(r)
        head = reasons[0] if reasons else "未知原因"
        more = f"（以及另外 {len(reasons) - 1} 种原因）" if len(reasons) > 1 else ""
        return f"{len(failed)} 个视频全部整理失败：{head}{more}", "error"
    if failed:
        return f"已移动 {moved} 个，失败 {len(failed)} 个", "done"
    if moved == 0:
        return "没有可整理的视频", "done"
    return f"已整理 {moved} 个视频", "done"


def execute_plan(db: Database, cfg: Config, tasks: TaskRegistry, task_id: str,
                 tag_ids: list[int] | None = None,
                 video_ids: list[int] | None = None,
                 items: list[dict[str, Any]] | None = None,
                 unwritable: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    plan = {"items": items, "total": len(items or [])} if items else build_plan(db, cfg, tag_ids, video_ids)
    items = plan["items"]
    tasks.update(task_id, total=len(items), message="开始整理…")
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    db.execute("INSERT INTO organize_batches (id, created_at, undone, note) VALUES (?,?,0,?)",
               (batch_id, now_iso(), f"整理 {len(items)} 个视频"))

    moved: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for it in items:
        if tasks.is_cancelled(task_id):
            break
        src, dst = Path(it["from"]), Path(it["to"])
        try:
            if not src.exists():
                raise FileNotFoundError("源文件已不存在")
            _unique_target(Path(it["dir"]), it["name"], set())  # 占位，防止并发重名
            real_dst = dst
            if real_dst.exists():
                real_dst = _unique_target(Path(it["dir"]), it["name"], set())
            how = _move_with_retry(src, real_dst)
            db.execute(
                "INSERT INTO organize_logs (batch_id, video_id, tag_id, from_path, to_path, moved_at) "
                "VALUES (?,?,?,?,?,?)",
                (batch_id, it["video_id"], it["tag_id"], str(src), str(real_dst), now_iso()),
            )
            db.execute(
                "UPDATE videos SET path=?, filename=?, status='organized', organized_at=? WHERE id=?",
                (str(real_dst), real_dst.name, now_iso(), it["video_id"]),
            )
            moved.append({"video_id": it["video_id"], "name": it["name"], "tag_id": it["tag_id"],
                          "from": str(src), "to": str(real_dst), "how": how})
            tasks.step(task_id, f"已移动 {real_dst.name}")
        except Exception as e:  # noqa: BLE001 — 单个文件失败不应中断整批
            reason = explain_error(e)
            entry: dict[str, Any] = {"video_id": it["video_id"], "name": it["name"], "error": reason}
            # 失败的是「目标目录不可写」时补一条明说，网页才能提示去改权限
            owner = _reason_owner(unwritable or [], reason) or _reason_owner(unwritable or [], str(it.get("to") or ""))
            if owner and owner["kind"] == "tag":
                entry["hint"] = f"目标目录不可写：{owner['path']}"
            failed.append(entry)
            tasks.step(task_id, f"失败 {it['name']}：{reason}")

    if not moved and not failed:
        db.execute("DELETE FROM organize_batches WHERE id=?", (batch_id,))
    message, task_status = summarize_outcome(len(moved), failed)
    return {"batch_id": batch_id, "moved": len(moved), "failed": failed,
            "items": moved, "message": message, "task_status": task_status}


# ---------- 撤销 ----------
def undo_batch(db: Database, batch_id: str) -> dict[str, Any]:
    batch = db.query_one("SELECT * FROM organize_batches WHERE id=?", (batch_id,))
    if not batch:
        raise OrganizeError("找不到这条整理记录")
    if batch["undone"]:
        raise OrganizeError("这批已经撤销过了")
    logs = db.query("SELECT * FROM organize_logs WHERE batch_id=? ORDER BY id DESC", (batch_id,))
    restored, failed = 0, []
    for log in logs:
        to_path, from_path = Path(log["to_path"]), Path(log["from_path"])
        try:
            if not to_path.exists():
                raise FileNotFoundError("文件已不在整理后的位置")
            if from_path.exists():
                raise FileExistsError("原位置已存在同名文件")
            move_file(to_path, from_path)
            db.execute(
                "UPDATE videos SET path=?, filename=?, status=CASE WHEN tag_id IS NULL THEN 'idle' ELSE 'tagged' END, "
                "organized_at=NULL WHERE id=?",
                (str(from_path), from_path.name, log["video_id"]),
            )
            restored += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"name": to_path.name, "error": explain_error(e)})
    db.execute("UPDATE organize_batches SET undone=1 WHERE id=?", (batch_id,))
    return {"restored": restored, "failed": failed}


# ---------- 记录 ----------
def list_batches(db: Database, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT b.*, COUNT(l.id) AS files FROM organize_batches b "
        "LEFT JOIN organize_logs l ON l.batch_id = b.id "
        "GROUP BY b.id ORDER BY b.created_at DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r)
        dirs = db.query(
            "SELECT DISTINCT rtrim(SUBSTR(to_path, 1, LENGTH(to_path) - LENGTH(filename))) AS d "
            "FROM organize_logs l JOIN videos v ON v.id = l.video_id WHERE l.batch_id=?", (r["id"],))
        d["dirs"] = [x["d"] for x in dirs][:6]
        out.append(d)
    return out
