"""扫描源目录：增量收集视频文件、探测元数据、生成封面。"""
from __future__ import annotations

import os
import time
from .concurrency import scan_pool
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database, now_iso
from .media import MediaTools, can_direct_play, make_thumb, probe
from .organizer import resolve_tag_dir
from .tasks import TaskRegistry

VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".rmvb", ".rm", ".3gp",
    ".ogv", ".divx", ".vob", ".asf", ".f4v",
}
SKIP_DIRS = {"@eaDir", "#recycle", "$RECYCLE.BIN", "System Volume Information",
             ".Trash", ".Trashes", ".@__thumb", "lost+found"}


def is_video(p: Path) -> bool:
    return p.suffix.lower() in VIDEO_EXTS


def iter_videos(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        for name in filenames:
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            if is_video(p):
                found.append(p)
    return found


def scan_sources(db: Database, cfg: Config, tools: MediaTools, tasks: TaskRegistry,
                 task_id: str, source_ids: list[int] | None = None, full: bool = False,
                 tag_ids: list[int] | None = None) -> dict[str, Any]:
    if not tools.available:
        raise RuntimeError("未找到 ffmpeg，无法扫描元数据")

    # 只给了 tag_ids 时只扫这些标签的目标文件夹（新建标签后立刻入库用），不碰源文件夹
    only_tag_dirs = bool(tag_ids) and not source_ids
    if only_tag_dirs:
        rows: list[dict[str, Any]] = []
    elif source_ids:
        marks = ",".join("?" * len(source_ids))
        rows = db.query(f"SELECT * FROM sources WHERE enabled=1 AND id IN ({marks})", source_ids)
    else:
        rows = db.query("SELECT * FROM sources WHERE enabled=1")
    roots = [Path(r["path"]) for r in rows]
    source_id_by_path = {str(Path(r["path"])): int(r["id"]) for r in rows}

    def _source_id_of(rows_arg, root_path: Path) -> int:
        return source_id_by_path.get(str(root_path), 0)

    # 标签对应的目标文件夹也算扫描范围：整理过的视频就躺在这些目录里，
    # 不扫它们的话，重装/换机后这些文件无法重新入库。
    tag_dirs: list[tuple[Path, int]] = []
    if tag_ids:
        marks = ",".join("?" * len(tag_ids))
        tag_rows = db.query(
            f"SELECT id, name, dir_path FROM tags WHERE id IN ({marks}) ORDER BY sort_order, id", tag_ids)
    else:
        tag_rows = db.query("SELECT id, name, dir_path FROM tags ORDER BY sort_order, id")
    for t in tag_rows:
        d = resolve_tag_dir(db, cfg, {"dir_path": t["dir_path"], "name": t["name"]})
        if d is not None:
            tag_dirs.append((Path(d), int(t["id"])))
    if not roots and not tag_dirs:
        raise RuntimeError("这个标签还没有可扫描的文件夹" if only_tag_dirs else "还没有添加源文件夹")

    # 1) 收集文件清单（源文件夹 + 标签文件夹；同一文件按「标签文件夹」归类）
    tasks.update(task_id, message="正在遍历目录…")
    planned: dict[str, tuple[Path, int | None]] = {}

    def _key(p: Path) -> str:
        try:
            return str(p.resolve())
        except OSError:
            return str(p)

    for root in roots:
        if not root.exists():
            continue
        got = iter_videos(root)
        for p in got:
            planned.setdefault(_key(p), (p, None))
        tasks.update(task_id, message=f"已发现 {len(planned)} 个视频（{root}）")

    # 「上次扫描时间」只记**真的遍历过**的标签目录（目录存在且能读），
    # 目录都不存在的不记——否则用户会以为那个标签查过了，其实一次都没查。
    scanned_tag_ids: list[int] = []
    for tdir, tid in tag_dirs:
        if not tdir.exists():
            continue
        got = iter_videos(tdir)
        scanned_tag_ids.append(tid)
        for p in got:
            prev = planned.get(_key(p))
            if prev is not None and prev[1] is None and not _under_prefix(str(p), str(tdir)):
                # 同一个文件被源目录先扫到，而它的字面路径并不在标签目录下（只是 resolve 后撞了路径）：
                # 保持「源文件夹里的文件」，不要因为同名目录把它算成标签文件夹。
                continue
            planned[_key(p)] = (p, tid)  # 标签文件夹优先
        if got:
            tasks.update(task_id, message=f"标签文件夹 {tdir.name}：{len(got)} 个视频")

    files: list[tuple[Path, int | None]] = list(planned.values())
    in_scope_roots = roots + [d for d, _ in tag_dirs]
    tag_dirs_only = [d for d, _ in tag_dirs]

    # 每个文件夹单独的扫描结果：前端「每个目录扫完弹一条 toast」就靠它。
    # 标签文件夹优先归属（同一个文件被两处扫到时，它算标签文件夹的）；
    # 只在源文件夹里出现的才算源文件夹的。
    per_dir: list[dict[str, Any]] = []
    dir_of: dict[str, str] = {}   # 文件真实路径 → per_dir 里的 key
    for tdir, tid in tag_dirs:
        if not tdir.exists():
            continue
        per_dir.append({"kind": "tag", "id": tid, "name": tdir.name, "path": str(tdir),
                        "found": 0, "added": 0, "updated": 0, "skipped": 0, "failed": 0})
    for root in roots:
        if not root.exists():
            continue
        per_dir.append({"kind": "source", "id": _source_id_of(rows, root), "name": root.name or str(root),
                        "path": str(root), "found": 0, "added": 0, "updated": 0, "skipped": 0, "failed": 0})

    def _dir_key(d: dict[str, Any]) -> str:
        return f"{d['kind']}:{d['id']}"

    dir_index = {_dir_key(d): d for d in per_dir}
    # 先给标签文件夹打标，再给源文件夹（这样同一条文件归属唯一）
    for p, tid in files:
        k = _key(p)
        if tid is not None:
            dir_of[k] = f"tag:{tid}"
    for p, tid in files:
        k = _key(p)
        if k in dir_of:
            continue
        for root in roots:
            if _is_under(p, root):
                dir_of[k] = f"source:{_source_id_of(rows, root)}"
                break
    for k, key in dir_of.items():
        d = dir_index.get(key)
        if d is not None:
            d["found"] += 1

    def tag_dir_of(p: Path) -> bool:
        """文件是否真的躺在某个标签文件夹里（按真实路径 + 字符串前缀双重判断）。"""
        return any(_is_under(p, d) for d in tag_dirs_only)

    tasks.set_total(task_id, len(files))

    # 2) 现有记录
    existing = {r["path"]: r for r in db.query("SELECT id, path, size, mtime, thumb, status, tag_id FROM videos")}

    stats = {"added": 0, "updated": 0, "skipped": 0, "missing": 0, "failed": 0}
    seen: set[str] = set()
    workers = max(1, int(cfg.get("scan_workers", 3) or 3))

    def work(p: Path) -> dict[str, Any] | None:
        try:
            st = p.stat()
        except OSError:
            return None
        spath = str(p)
        old = existing.get(spath)
        need = full or old is None or int(old["size"]) != st.st_size or abs(float(old["mtime"]) - st.st_mtime) > 1
        item = {"path": spath, "size": st.st_size, "mtime": st.st_mtime, "old": old, "need_probe": need}
        if need:
            meta = probe(tools, p)
            item.update(meta)
            item["direct"] = 1 if can_direct_play(p.suffix, meta.get("vcodec", ""), meta.get("acodec", "")) else 0
        return item

    # 全局共享线程池：scan_workers 是**全局上限**，不是每个扫描各一份。
    # 以前每次扫描自己开一个池，两个扫描并发就是 6 个 ffprobe 同时跑。
    def bump(key: str, field: str) -> None:
        d = dir_index.get(dir_of.get(key) or "")
        if d is not None:
            d[field] += 1

    pool = scan_pool(workers)
    for (p, tag_id), item in zip(files, pool.map(work, [f[0] for f in files])):
        if tasks.is_cancelled(task_id):
            break
        spath = str(p)
        seen.add(spath)
        dkey = dir_of.get(_key(p))
        if item is None:
            stats["failed"] += 1
            if dkey and dkey in dir_index:
                dir_index[dkey]["failed"] += 1
            tasks.step(task_id, f"跳过（无法读取）：{p.name}")
            continue
        if not item["need_probe"]:
            old_row = item["old"]
            if (old_row is not None and tag_id is None
                    and str(old_row["status"]) == "organized"
                    and not tag_dir_of(p)):
                # 记录是「已整理」，但文件其实还在源文件夹里、不在任何标签文件夹下：
                # 多半是标签默认目录（源目录/标签名）和用户自己的同名子目录撞名，纠正回来。
                fixed = "tagged" if old_row["tag_id"] is not None else "idle"
                db.execute(
                    "UPDATE videos SET status=?, organized_at=NULL, scanned_at=? WHERE id=?",
                    (fixed, now_iso(), old_row["id"]),
                )
                stats["updated"] += 1
                bump(spath, "updated")
                tasks.step(task_id, f"归位（不在标签文件夹里）：{p.name}")
                continue
            if old_row is not None and tag_id is not None and (
                    str(old_row["status"]) != "organized" or old_row["tag_id"] is None):
                # 文件位于标签文件夹里：说明它已经被整理过，补上「已整理 + 标签」
                # （tag_id 为空也要补：比如标签被删过再重建、或者换机后扫描到旧归档）
                db.execute(
                    "UPDATE videos SET status='organized', tag_id=COALESCE(tag_id, ?), "
                    "organized_at=COALESCE(organized_at, ?), scanned_at=? WHERE path=?",
                    (tag_id, now_iso(), now_iso(), spath),
                )
                stats["updated"] += 1
                bump(spath, "updated")
                tasks.step(task_id, f"归类为标签文件夹：{p.name}")
            elif old_row is not None and str(old_row["status"]) == "missing":
                # 文件重新出现但大小/mtime 未变：不需要重新探测，但状态要恢复
                db.execute(
                    "UPDATE videos SET status=?, scanned_at=? WHERE path=?",
                    ("organized" if tag_id is not None else "idle", now_iso(), spath),
                )
                stats["updated"] += 1
                bump(spath, "updated")
                tasks.step(task_id, f"恢复：{p.name}")
            else:
                stats["skipped"] += 1
                bump(spath, "skipped")
                tasks.step(task_id, f"未变化：{p.name}")
            continue
        # 先入库拿到真实 id，再用 id 命名缩略图（之前用时间戳当 id，同一毫秒内会撞名 →
        # 多个视频指向同一张缩略图，表现为「封面和视频对不上」）
        vid = _upsert(db, p, item, "", tag_id=tag_id)
        if vid and tag_id is None and item["old"] is not None \
                and str(item["old"]["status"]) == "organized" and not tag_dir_of(p):
            fixed = "tagged" if item["old"]["tag_id"] is not None else "idle"
            db.execute("UPDATE videos SET status=?, organized_at=NULL WHERE id=?",
                       (fixed, item["old"]["id"]))
        if vid:
            try:
                thumb_path = cfg.thumb_dir / f"{vid}.jpg"
                if make_thumb(tools, p, thumb_path, float(item.get("duration") or 0),
                              float(cfg.get("thumb_position", 0.0))):
                    db.execute("UPDATE videos SET thumb=? WHERE id=?", (thumb_path.name, vid))
            except Exception:
                pass
        if item["old"] is None:
            stats["added"] += 1
            bump(spath, "added")
            prefix = "新增（标签文件夹）" if tag_id is not None else "新增"
            tasks.step(task_id, f"{prefix}：{p.name}")
        else:
            stats["updated"] += 1
            bump(spath, "updated")
            tasks.step(task_id, f"更新：{p.name}")

    # 3) 标记丢失的文件（源文件夹与标签文件夹范围内的）
    #    以前这里直接跳过 organized，导致「整理过的文件被删掉」也一直显示在库里；
    #    现在改为按「文件是否真的存在」判断：整理后的记录指向标签文件夹，只要文件还在就不会误判。
    for spath, row in existing.items():
        if spath in seen:
            continue
        try:
            p = Path(spath)
            in_scope = any(_is_under(p, r) for r in in_scope_roots)
        except OSError:
            in_scope = False
        if in_scope and not Path(spath).exists() and row["status"] != "missing":
            db.execute("UPDATE videos SET status='missing' WHERE id=?", (row["id"],))
            stats["missing"] += 1

    # 「上次扫描时间」按目录各记各的：源文件夹记在自己那行、标签记在自己那行。
    # 以前另有一个全局 settings.last_scan_at，只扫一个标签也会被刷新，看起来像源文件夹
    # 刚查过——误导（而且两个扫描并发时后完成的会覆盖先完成的）。现在整库不留全局时间。
    stamp = now_iso()
    for r in rows:
        db.execute("UPDATE sources SET last_scan_at=? WHERE id=?", (stamp, r["id"]))
    for tid in scanned_tag_ids:
        db.execute("UPDATE tags SET last_scan_at=? WHERE id=?", (stamp, tid))

    # 每个文件夹一条结果，给前端「每个目录扫完弹一条 toast」用
    stats["dirs"] = per_dir
    return warn_unwritable(tasks, task_id, stats)


def unwritable_note(unwritable: list[dict[str, Any]]) -> str:
    """把不可写目录拼成一句给人看的话（扫描结果与整理提示共用）。"""
    if not unwritable:
        return ""
    first = unwritable[0]
    more = f" 等 {len(unwritable)} 个目录" if len(unwritable) > 1 else "目录"
    return (f"扫描完成，但{more}服务用户没有写权限（{first['path']}：{first['reason']}），"
            "其中的视频无法整理，请调整目录权限后重试")


def warn_unwritable(tasks: TaskRegistry, task_id: str, stats: dict[str, Any]) -> dict[str, Any]:
    """扫描本身只需要读权限，所以不可写不算失败；只在结果和消息里提示一下。

    预检结果在任务启动前就写进了 extra（tasks.spawn(..., unwritable=[...])），
    这里在扫描结束时把它补进 result 并给出 warning 文案，前端轮询就能拿到。
    """
    with tasks.lock:
        t = tasks.tasks.get(task_id) or {}
        unwritable = list(t.get("unwritable") or [])
    stats["unwritable"] = unwritable
    if unwritable:
        note = unwritable_note(unwritable)
        tasks.update(task_id, warning=note)
        # 消息类字段会被后续 step() 覆盖，所以只加字段、不覆盖当前 message；收尾由 spawn 处理
    return stats


def _under_prefix(path: str, root: str) -> bool:
    p = path.replace("\\", "/").rstrip("/")
    r = root.replace("\\", "/").rstrip("/")
    if not r:
        return False
    return p == r or p.startswith(r + "/")


def _is_under(path: Path, root: Path) -> bool:
    """path 是否在 root 目录下。

    先按真实路径比较；符号链接、绑定挂载导致两边 resolve() 得到不同路径时，
    再退回字符串前缀判断——否则文件删掉后会被判成「不在扫描范围」，
    永远不会标 missing，表现出来就是「只能扫出新增，扫不出移除」。
    """
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        pass
    return _under_prefix(str(path), str(root))


def _upsert(db: Database, p: Path, item: dict[str, Any], thumb: str,
            tag_id: int | None = None) -> int:
    now = now_iso()
    old = item["old"]
    organized = tag_id is not None
    if old is None:
        # ON CONFLICT 是兜底：`old` 来自开扫时的全库快照，如果这期间别的代码路径
        # （并发扫描、或用户手动调接口）刚把同一个 path 插进来，裸 INSERT 会撞
        # videos.path 的 UNIQUE 约束抛 IntegrityError，整轮扫描直接失败。
        # 改成冲突即更新，最差也只是把这行刷新一遍，不会中断扫描。
        new_id = db.execute(
            """INSERT INTO videos (path, filename, ext, size, duration, width, height, vcodec, acodec,
                                   bitrate, thumb, tag_id, status, direct_play, mtime, scanned_at,
                                   organized_at, added_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET
                 filename=excluded.filename, ext=excluded.ext, size=excluded.size,
                 duration=excluded.duration, width=excluded.width, height=excluded.height,
                 vcodec=excluded.vcodec, acodec=excluded.acodec, bitrate=excluded.bitrate,
                 thumb=CASE WHEN excluded.thumb<>'' THEN excluded.thumb ELSE videos.thumb END,
                 tag_id=COALESCE(excluded.tag_id, videos.tag_id),
                 status=CASE WHEN excluded.status='organized' THEN 'organized'
                             WHEN videos.status='missing' THEN excluded.status
                             ELSE videos.status END,
                 direct_play=excluded.direct_play, mtime=excluded.mtime,
                 scanned_at=excluded.scanned_at,
                 organized_at=CASE WHEN excluded.organized_at IS NOT NULL
                                   THEN COALESCE(videos.organized_at, excluded.organized_at)
                                   ELSE videos.organized_at END""",
            (str(p), p.name, p.suffix.lower().lstrip("."), item["size"],
             float(item.get("duration") or 0), int(item.get("width") or 0), int(item.get("height") or 0),
             item.get("vcodec", ""), item.get("acodec", ""), int(item.get("bitrate") or 0),
             thumb, tag_id, "organized" if organized else "idle", item.get("direct", 1),
             item["mtime"], now, now if organized else None, now),
        )
        if new_id:
            return int(new_id)
        # 走了 ON CONFLICT 的 UPDATE 分支：lastrowid 不是这行的 id，按 path 查回来
        row = db.query_one("SELECT id FROM videos WHERE path=?", (str(p),))
        return int(row["id"]) if row else 0
    else:
        db.execute(
            """UPDATE videos SET size=?, duration=?, width=?, height=?, vcodec=?, acodec=?, bitrate=?,
                                 thumb=?, direct_play=?, mtime=?, scanned_at=?,
                                 tag_id=COALESCE(tag_id, ?),
                                 status=CASE WHEN status='missing' THEN ?
                                             WHEN ? IS NOT NULL THEN 'organized'
                                             ELSE status END,
                                 organized_at=CASE WHEN ? IS NOT NULL THEN COALESCE(organized_at, ?)
                                                   ELSE organized_at END
               WHERE path=?""",
            (item["size"], float(item.get("duration") or 0), int(item.get("width") or 0),
             int(item.get("height") or 0), item.get("vcodec", ""), item.get("acodec", ""),
             int(item.get("bitrate") or 0), thumb or old["thumb"], item.get("direct", 1),
             item["mtime"], now, tag_id,
             "organized" if organized else "idle", tag_id, tag_id, now,
             str(p)),
        )
        return int(old["id"])
