"""数据库行 → API 字典。"""
from __future__ import annotations

from typing import Any


def video_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    vid = d.get("id")
    d["thumb_url"] = f"/api/videos/{vid}/thumb" if d.get("thumb") else None
    d["raw_url"] = f"/api/videos/{vid}/raw"
    ext = (d.get("ext") or "").lower().lstrip(".")
    d["ext"] = f".{ext}" if ext else ""
    d["duration"] = float(d.get("duration") or 0)
    d["size"] = int(d.get("size") or 0)
    d["organized"] = d.get("status") == "organized"
    d["has_tag"] = bool(d.get("tag_id"))
    return d


VIDEO_SQL = (
    "SELECT v.*, t.name AS tag_name, t.color AS tag_color, t.dir_path AS tag_dir, "
    "h.position AS position, h.watched_at AS watched_at "
    "FROM videos v LEFT JOIN tags t ON t.id = v.tag_id "
    "LEFT JOIN play_history h ON h.video_id = v.id "
)
