"""手机端上传：把文件存到服务器的上传目录，并立即入库。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..db import now_iso
from ..media import can_direct_play, make_thumb, probe
from ..scanner import VIDEO_EXTS
from ..state import get_state
from .deps import require_user
from .serialize import VIDEO_SQL, video_dict

router = APIRouter(prefix="/api/upload", tags=["upload"])

UPLOAD_DIRNAME = "手机上传"


def _default_dir(st) -> Path:
    custom = (st.cfg.get("upload_dir") or "").strip()
    if custom:
        return Path(custom).expanduser()
    root = (st.cfg.get("root_dir") or "").strip()
    if root:
        return Path(root).expanduser() / UPLOAD_DIRNAME
    src = st.db.query_one("SELECT path FROM sources WHERE enabled=1 ORDER BY id LIMIT 1")
    if src:
        return Path(src["path"]) / UPLOAD_DIRNAME
    return st.cfg.data_dir / "uploads"


@router.post("")
async def upload(file: UploadFile = File(...),
                 dir: str = Form(""),
                 tag_id: str = Form(""),
                 user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    name = (file.filename or "video.mp4").replace("/", "_").replace("\\", "_")
    ext = Path(name).suffix.lower().lstrip(".")
    if f".{ext}" not in VIDEO_EXTS:
        raise HTTPException(400, f"不支持的文件类型：{ext or '未知'}")
    target_dir = Path(dir).expanduser() if dir.strip() else _default_dir(st)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"无法创建上传目录 {target_dir}：{e}") from e
    if not os.access(target_dir, os.W_OK):
        raise HTTPException(400, f"上传目录不可写：{target_dir}（请检查目录权限或改回默认目录）")
    stem, suffix = Path(name).stem, Path(name).suffix
    dest = target_dir / name
    n = 1
    while dest.exists():
        dest = target_dir / f"{stem} ({n}){suffix}"
        n += 1
    try:
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out, length=1 << 20)
    except OSError as e:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(400, f"写入上传目录失败（{target_dir}）：{e}") from e
    finally:
        await file.close()
    size = dest.stat().st_size
    info = probe(st.tools, dest) if st.tools.available else {"ok": False}
    row = st.db.query_one("SELECT id FROM videos WHERE path=?", (str(dest),))
    if row:
        video_id = row["id"]
    else:
        video_id = st.db.execute(
            "INSERT INTO videos (path, filename, ext, size, duration, width, height, vcodec, acodec, "
            "bitrate, thumb, tag_id, status, direct_play, mtime, scanned_at, added_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,'idle',?,?,?,?)",
            (str(dest), dest.name, ext, size, info.get("duration", 0), info.get("width", 0),
             info.get("height", 0), info.get("vcodec", ""), info.get("acodec", ""),
             info.get("bitrate", 0), "",
             1 if can_direct_play(ext, info.get("vcodec", ""), info.get("acodec", "")) else 0,
             int(dest.stat().st_mtime), now_iso(), now_iso()))
    if tag_id.strip().isdigit():
        t = st.db.query_one("SELECT id FROM tags WHERE id=?", (int(tag_id),))
        if t:
            st.db.execute("UPDATE videos SET tag_id=?, status='tagged' WHERE id=?",
                          (int(tag_id), video_id))
    if st.tools.available:
        thumb = st.cfg.thumb_dir / f"{video_id}.jpg"
        if make_thumb(st.tools, dest, thumb, info.get("duration", 0),
                      st.cfg.get("thumb_position") or 0.0):
            st.db.execute("UPDATE videos SET thumb=? WHERE id=?", (thumb.name, video_id))
    out = st.db.query_one(VIDEO_SQL + " WHERE v.id=?", (video_id,))
    return {"ok": True, "video": video_dict(out), "path": str(dest)}
