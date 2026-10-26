"""数据库行 → API 字典。"""
from __future__ import annotations

from typing import Any

from ..state import get_state


def _thumb_version(name: str) -> int:
    """缩略图文件 mtime 作为 cache-buster：重生成后 URL 变化，浏览器/App 才会重新拉取。"""
    try:
        st = get_state()
        f = st.cfg.thumb_dir / name
        return int(f.stat().st_mtime) if f.exists() else 0
    except Exception:
        return 0


def video_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    vid = d.get("id")
    thumb = (d.get("thumb") or "").strip()
    if thumb:
        name = thumb.rsplit("/", 1)[-1]
        ver = _thumb_version(name)
    else:
        # 还没记录名字时，规范文件名是 <id>.jpg
        ver = _thumb_version(f"{vid}.jpg")
    if thumb:
        d["thumb_url"] = f"/api/videos/{vid}/thumb?v={ver}"
    else:
        d["thumb_url"] = f"/api/videos/{vid}/thumb?v={ver}" if ver else None
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
