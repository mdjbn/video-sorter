"""视频播放：原始文件 Range 流 + 直放 / HLS 策略 + HLS 分片服务。"""
from __future__ import annotations

import asyncio
import mimetypes
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..media import can_direct_play, transcode_reason
from ..state import get_state
from .deps import require_user

router = APIRouter(prefix="/api/videos/{video_id}", tags=["stream"])
status_router = APIRouter(prefix="/api", tags=["stream"])

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
HLS_NAME_RE = re.compile(r"^(index\.m3u8|seg\d{5}\.ts)$")
HLS_PART_RE = re.compile(r"^s(\d+)$")
CHUNK = 1 << 20


def _video_row(st, video_id: int):
    row = st.db.query_one("SELECT * FROM videos WHERE id=?", (video_id,))
    if not row:
        raise HTTPException(404, "视频不存在")
    return row


def _file_iter(path: Path, start: int, end: int):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/raw")
def raw(video_id: int, request: Request, download: int = 0,
        user: dict[str, Any] = Depends(require_user)):
    st = get_state()
    row = _video_row(st, video_id)
    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(404, "文件不存在或已被移动")
    size = path.stat().st_size
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if ctype == "application/mp4":
        ctype = "video/mp4"
    disp = {}
    if download:
        # 网页端「下载」用：让浏览器按附件保存，文件名沿用原始文件名
        from urllib.parse import quote
        disp["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(row['filename'] or path.name)}")
    header = request.headers.get("range")
    if header:
        m = RANGE_RE.match(header.strip())
        if not m:
            raise HTTPException(416, "Range 头不合法")
        first, last = m.group(1), m.group(2)
        if first == "":
            n = int(last or 0)
            if n <= 0:
                raise HTTPException(416, "Range 头不合法")
            start, end = max(0, size - n), size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            raise HTTPException(416, "Range 超出文件范围")
        headers = {
            **disp,
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
        }
        return StreamingResponse(_file_iter(path, start, end), status_code=206,
                                 media_type=ctype, headers=headers)
    return StreamingResponse(
        _file_iter(path, 0, size - 1), media_type=ctype,
        headers={**disp, "Accept-Ranges": "bytes", "Content-Length": str(size)})


@router.get("/play")
def play(video_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """返回播放策略：能直放就直放，否则按需转 HLS。"""
    st = get_state()
    row = _video_row(st, video_id)
    path = Path(row["path"])
    if not path.exists():
        return {"mode": "missing", "message": "文件不存在或已被移动"}
    ext = "." + (row["ext"] or path.suffix.lstrip(".")).lower().lstrip(".")
    vcodec = (row["vcodec"] or "").lower()
    acodec = (row["acodec"] or "").lower()
    if can_direct_play(ext, vcodec, acodec):
        return {"mode": "direct", "url": f"/api/videos/{video_id}/raw",
                "duration": row["duration"] or 0, "reason": "容器与编码可直放"}
    if not st.cfg.get("transcode"):
        return {"mode": "direct", "url": f"/api/videos/{video_id}/raw",
                "duration": row["duration"] or 0, "warning": "浏览器可能无法播放该编码"}
    if not st.tools.available:
        return {"mode": "error", "message": "未找到 ffmpeg，无法转码；请安装 ffmpeg 或把 ffmpeg.exe 放进 tools/"}
    job = st.hls.ensure(video_id, path, row["duration"] or 0, vcodec, acodec)
    return {
        "mode": "hls",
        "url": f"/api/videos/{video_id}/hls/s0/index.m3u8",
        "status": job.status,
        "copy": job.copy_mode,
        "percent": getattr(job, "percent", 0),
        "duration": row["duration"] or 0,
        "reason": transcode_reason(ext, vcodec, acodec),
        "seek": True,
    }


@router.get("/hls/{part}/{name}")
async def hls_file(video_id: int, part: str, name: str,
                   user: dict[str, Any] = Depends(require_user)):
    """HLS 分片。part 形如 `s120` —— 表示「从第 120 秒开始切的那一路」，
    播放器拖动进度条超出已转码范围时会换到新的 part，从而秒级从目标位置继续。"""
    st = get_state()
    m = HLS_PART_RE.match(part)
    if not m or not HLS_NAME_RE.match(name):
        raise HTTPException(404, "分片不存在")
    start = float(m.group(1))
    row = _video_row(st, video_id)
    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(404, "文件不存在或已被移动")
    job = st.hls.ensure(video_id, path, row["duration"] or 0,
                        row["vcodec"] or "", row["acodec"] or "", start=start)
    target = job.dir / name
    if not target.exists():
        for _ in range(150):  # 最多等 30 秒
            if target.exists():
                break
            if job.status in {"error", "cancelled"}:
                break
            await asyncio.sleep(0.2)
    if not target.exists():
        if job.status == "error":
            raise HTTPException(500, job.error or "转码失败")
        raise HTTPException(504, "转码尚未就绪，请稍后重试")
    ctype = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t"
    return FileResponse(target, media_type=ctype, headers={"Cache-Control": "no-store"})


@status_router.get("/videos/{video_id}/hlsstatus")
def hls_status(video_id: int, start: int = 0,
               user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    row = _video_row(st, video_id)
    # start > 0：查「从第 start 秒开始切的那一路」的进度
    job = st.hls.jobs.get((video_id, max(0, int(start)))) or st.hls.job_for_video(video_id)
    return {
        "video_id": video_id,
        "status": job.status if job else "idle",
        "percent": getattr(job, "percent", 0) if job else 0,
        "ready": job.ready if job else False,
        "finished": job.finished if job else False,
        "error": job.error if job else "",
        "location": row["path"],
    }
