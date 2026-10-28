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


def _collapse_upload_path(path: Path) -> Path:
    """把历史上被重复套上的「手机上传」收敛回一层。

    老逻辑拿「第一条源目录」当基准再拼 `手机上传`，而上传目录自己也是一条 id 最小的源目录，
    于是每次启动 / 加源 / 改设置都会再套一层（`…/手机上传/手机上传/手机上传`）。
    """
    p = Path(path)
    while p.name == UPLOAD_DIRNAME and p.parent.name == UPLOAD_DIRNAME:
        p = p.parent
    return p


def _is_fallback_dir(st, path: Path) -> bool:
    """这条上传目录是不是还停在「数据目录/uploads」这个兜底位置（没有跟着源目录走）。"""
    try:
        return Path(path).resolve() == (Path(st.cfg.data_dir) / "uploads").resolve()
    except OSError:
        return False


def _fallback_has_uploads(st, path: Path) -> bool:
    """兜底位置上已经有用户上传的视频时，不要再挪（挪了用户会找不到上传的东西）。"""
    if not _is_fallback_dir(st, path):
        return False
    try:
        return any(p.is_file() for p in Path(path).iterdir())
    except OSError:
        return True  # 判断不了就当有，保守不动


def _default_dir(st) -> Path:
    custom = (st.cfg.get("upload_dir") or "").strip()
    if custom:
        return Path(custom).expanduser()
    root = (st.cfg.get("root_dir") or "").strip()
    if root:
        return Path(root).expanduser() / UPLOAD_DIRNAME
    # 上传目录本身就是一条内置源目录（kind='upload'），绝不能再拿它当基准拼一层「手机上传」，
    # 否则会自己套自己。已经固定下来的路径（用户在界面里改过、或已经在某个源目录下）优先尊重；
    # 只有还停在「数据目录/uploads」这个兜底位置时，才跟着第一个普通源目录走 —— 与 README 的描述一致。
    row = st.db.query_one("SELECT path FROM sources WHERE kind='upload' ORDER BY id LIMIT 1")
    row_path = None
    if row and (row["path"] or "").strip():
        row_path = _collapse_upload_path(Path(row["path"]))
        if not _is_fallback_dir(st, row_path) or _fallback_has_uploads(st, row_path):
            return row_path
    src = st.db.query_one(
        "SELECT path FROM sources WHERE enabled=1 AND COALESCE(kind, '') <> 'upload' "
        "ORDER BY id LIMIT 1")
    if src and (src["path"] or "").strip():
        return Path(src["path"]) / UPLOAD_DIRNAME
    if row_path is not None:
        return row_path
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
