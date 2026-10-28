"""扫描源目录：增量收集视频文件、探测元数据、生成封面。"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
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

    for tdir, tid in tag_dirs:
        if not tdir.exists():
            continue
        got = iter_videos(tdir)
        for p in got:
            planned[_key(p)] = (p, tid)  # 标签文件夹优先
        if got:
            tasks.update(task_id, message=f"标签文件夹 {tdir.name}：{len(got)} 个视频")

    files: list[tuple[Path, int | None]] = list(planned.values())
    in_scope_roots = roots + [d for d, _ in tag_dirs]
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

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (p, tag_id), item in zip(files, pool.map(work, [f[0] for f in files])):
            if tasks.is_cancelled(task_id):
                break
            spath = str(p)
            seen.add(spath)
            if item is None:
                stats["failed"] += 1
                tasks.step(task_id, f"跳过（无法读取）：{p.name}")
                continue
            if not item["need_probe"]:
                old_row = item["old"]
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
                    tasks.step(task_id, f"归类为标签文件夹：{p.name}")
                elif old_row is not None and str(old_row["status"]) == "missing":
                    # 文件重新出现但大小/mtime 未变：不需要重新探测，但状态要恢复
                    db.execute(
                        "UPDATE videos SET status=?, scanned_at=? WHERE path=?",
                        ("organized" if tag_id is not None else "idle", now_iso(), spath),
                    )
                    stats["updated"] += 1
                    tasks.step(task_id, f"恢复：{p.name}")
                else:
                    stats["skipped"] += 1
                    tasks.step(task_id, f"未变化：{p.name}")
                continue
            # 先入库拿到真实 id，再用 id 命名缩略图（之前用时间戳当 id，同一毫秒内会撞名 →
            # 多个视频指向同一张缩略图，表现为「封面和视频对不上」）
            vid = _upsert(db, p, item, "", tag_id=tag_id)
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
                prefix = "新增（标签文件夹）" if tag_id is not None else "新增"
                tasks.step(task_id, f"{prefix}：{p.name}")
            else:
                stats["updated"] += 1
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

    stamp = now_iso()
    for r in rows:
        db.execute("UPDATE sources SET last_scan_at=? WHERE id=?", (stamp, r["id"]))
    db.set_setting("last_scan_at", stamp)
    return stats


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _upsert(db: Database, p: Path, item: dict[str, Any], thumb: str,
            tag_id: int | None = None) -> int:
    now = now_iso()
    old = item["old"]
    organized = tag_id is not None
    if old is None:
        new_id = db.execute(
            """INSERT INTO videos (path, filename, ext, size, duration, width, height, vcodec, acodec,
                                   bitrate, thumb, tag_id, status, direct_play, mtime, scanned_at,
                                   organized_at, added_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(p), p.name, p.suffix.lower().lstrip("."), item["size"],
             float(item.get("duration") or 0), int(item.get("width") or 0), int(item.get("height") or 0),
             item.get("vcodec", ""), item.get("acodec", ""), int(item.get("bitrate") or 0),
             thumb, tag_id, "organized" if organized else "idle", item.get("direct", 1),
             item["mtime"], now, now if organized else None, now),
        )
        return int(new_id or 0)
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
