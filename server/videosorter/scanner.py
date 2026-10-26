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
                 task_id: str, source_ids: list[int] | None = None, full: bool = False) -> dict[str, Any]:
    if not tools.available:
        raise RuntimeError("未找到 ffmpeg，无法扫描元数据")

    if source_ids:
        marks = ",".join("?" * len(source_ids))
        rows = db.query(f"SELECT * FROM sources WHERE enabled=1 AND id IN ({marks})", source_ids)
    else:
        rows = db.query("SELECT * FROM sources WHERE enabled=1")
    roots = [Path(r["path"]) for r in rows]
    if not roots:
        raise RuntimeError("还没有添加源文件夹")

    # 1) 收集文件清单
    tasks.update(task_id, message="正在遍历目录…")
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        got = iter_videos(root)
        files.extend(got)
        tasks.update(task_id, message=f"已发现 {len(files)} 个视频（{root}）")
    tasks.set_total(task_id, len(files))

    # 2) 现有记录
    existing = {r["path"]: r for r in db.query("SELECT id, path, size, mtime, thumb, status FROM videos")}

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
        for p, item in zip(files, pool.map(work, files)):
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
                if old_row is not None and str(old_row["status"]) == "missing":
                    # 文件重新出现但大小/mtime 未变：不需要重新探测，但状态要恢复
                    db.execute("UPDATE videos SET status='idle', scanned_at=? WHERE path=?", (now_iso(), spath))
                    stats["updated"] += 1
                    tasks.step(task_id, f"恢复：{p.name}")
                else:
                    stats["skipped"] += 1
                    tasks.step(task_id, f"未变化：{p.name}")
                continue
            # 先入库拿到真实 id，再用 id 命名缩略图（之前用时间戳当 id，同一毫秒内会撞名 →
            # 多个视频指向同一张缩略图，表现为「封面和视频对不上」）
            vid = _upsert(db, p, item, "")
            if vid:
                try:
                    thumb_path = cfg.thumb_dir / f"{vid}.jpg"
                    if make_thumb(tools, p, thumb_path, float(item.get("duration") or 0),
                                  float(cfg.get("thumb_position", 0.15))):
                        db.execute("UPDATE videos SET thumb=? WHERE id=?", (thumb_path.name, vid))
                except Exception:
                    pass
            if item["old"] is None:
                stats["added"] += 1
                tasks.step(task_id, f"新增：{p.name}")
            else:
                stats["updated"] += 1
                tasks.step(task_id, f"更新：{p.name}")

    # 3) 标记丢失的文件（源目录内的）
    for spath, row in existing.items():
        if spath in seen:
            continue
        try:
            p = Path(spath)
            in_scope = any(_is_under(p, r) for r in roots)
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


def _upsert(db: Database, p: Path, item: dict[str, Any], thumb: str) -> int:
    now = now_iso()
    old = item["old"]
    if old is None:
        new_id = db.execute(
            """INSERT INTO videos (path, filename, ext, size, duration, width, height, vcodec, acodec,
                                   bitrate, thumb, status, direct_play, mtime, scanned_at, added_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, 'idle', ?, ?, ?, ?)""",
            (str(p), p.name, p.suffix.lower().lstrip("."), item["size"],
             float(item.get("duration") or 0), int(item.get("width") or 0), int(item.get("height") or 0),
             item.get("vcodec", ""), item.get("acodec", ""), int(item.get("bitrate") or 0),
             thumb, item.get("direct", 1), item["mtime"], now, now),
        )
        return int(new_id or 0)
    else:
        db.execute(
            """UPDATE videos SET size=?, duration=?, width=?, height=?, vcodec=?, acodec=?, bitrate=?,
                                 thumb=?, direct_play=?, mtime=?, scanned_at=?,
                                 status=CASE WHEN status='missing' THEN 'idle' ELSE status END
               WHERE path=?""",
            (item["size"], float(item.get("duration") or 0), int(item.get("width") or 0),
             int(item.get("height") or 0), item.get("vcodec", ""), item.get("acodec", ""),
             int(item.get("bitrate") or 0), thumb or old["thumb"], item.get("direct", 1),
             item["mtime"], now, str(p)),
        )
        return int(old["id"])
