"""视频库：列表、详情、打标签、重命名、删除、封面、统计、播放历史。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..db import now_iso
from ..media import make_thumb
from ..state import get_state
from .deps import require_user
from .serialize import VIDEO_SQL, video_dict

router = APIRouter(prefix="/api", tags=["videos"])

STATUSES = {"idle", "tagged", "organized", "missing"}


class TagIn(BaseModel):
    tag_id: int | None = None


class RenameIn(BaseModel):
    name: str


class HistoryIn(BaseModel):
    position: float = 0
    duration: float = 0


def _apply_tag(st, video_id: int, tag_id: int | None) -> dict[str, Any]:
    row = st.db.query_one("SELECT * FROM videos WHERE id=?", (video_id,))
    if not row:
        raise HTTPException(404, "视频不存在")
    if tag_id is not None:
        tag = st.db.query_one("SELECT * FROM tags WHERE id=?", (tag_id,))
        if not tag:
            raise HTTPException(404, "标签不存在")
    status = row["status"]
    if status not in {"organized", "missing"}:
        status = "tagged" if tag_id else "idle"
    st.db.execute("UPDATE videos SET tag_id=?, status=? WHERE id=?", (tag_id, status, video_id))
    updated = st.db.query_one(VIDEO_SQL + " WHERE v.id=?", (video_id,))
    return video_dict(updated)


@router.get("/videos")
def list_videos(
    status: str = Query("all"),
    tag: str | None = Query(None, description="数字=标签 id，none=未打标签"),
    q: str = Query("", description="文件名关键字"),
    sort: str = Query("added"),
    order: str = Query("desc"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    st = get_state()
    where, args = [], []
    if status == "untagged":
        where.append("v.tag_id IS NULL")
    elif status in STATUSES:
        where.append("v.status=?")
        args.append(status)
    if tag == "none":
        where.append("v.tag_id IS NULL")
    elif tag and tag.isdigit():
        where.append("v.tag_id=?")
        args.append(int(tag))
    if q.strip():
        where.append("v.filename LIKE ?")
        args.append(f"%{q.strip()}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    sorts = {
        "added": "v.added_at",
        "name": "v.filename",
        "duration": "v.duration",
        "size": "v.size",
        "organized": "v.organized_at",
        "status": "v.status",
    }
    col = sorts.get(sort, "v.added_at")
    direction = "ASC" if order.lower() == "asc" else "DESC"
    rows = st.db.query(
        VIDEO_SQL + clause + f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
        (*args, limit, offset),
    )
    total = st.db.query_one("SELECT COUNT(*) AS n FROM videos v" + clause, tuple(args))["n"]
    counts = {r["status"]: r["n"] for r in st.db.query(
        "SELECT status, COUNT(*) AS n FROM videos GROUP BY status")}
    counts["all"] = st.db.query_one("SELECT COUNT(*) AS n FROM videos")["n"]
    counts["untagged"] = st.db.query_one(
        "SELECT COUNT(*) AS n FROM videos WHERE tag_id IS NULL")["n"]
    return {"items": [video_dict(r) for r in rows], "total": total, "counts": counts}


@router.get("/stats")
def stats(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    counts = {r["status"]: r["n"] for r in st.db.query(
        "SELECT status, COUNT(*) AS n FROM videos GROUP BY status")}
    total = st.db.query_one("SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS bytes FROM videos")
    tagged = st.db.query_one("SELECT COUNT(*) AS n FROM videos WHERE tag_id IS NOT NULL")["n"]
    untagged = st.db.query_one("SELECT COUNT(*) AS n FROM videos WHERE tag_id IS NULL")["n"]
    last_scan = st.db.get_setting("last_scan_at") or ""
    tags = [dict(r) for r in st.db.query(
        "SELECT t.id, t.name, t.color, COUNT(v.id) AS count FROM tags t "
        "LEFT JOIN videos v ON v.tag_id = t.id GROUP BY t.id ORDER BY t.sort_order, t.id")]
    srcs = [dict(r) for r in st.db.query("SELECT * FROM sources ORDER BY id")]
    for s in srcs:
        s["count"] = st.db.query_one(
            "SELECT COUNT(*) AS n FROM videos WHERE path LIKE ?", (s["path"].rstrip("/") + "/%",))["n"]
    return {
        "total": total["n"], "bytes": total["bytes"], "tagged": tagged, "untagged": untagged,
        "organized": counts.get("organized", 0), "tagged_pending": counts.get("tagged", 0),
        "missing": counts.get("missing", 0), "last_scan_at": last_scan,
        "tags": tags, "sources": srcs,
    }


@router.get("/videos/{video_id}")
def get_video(video_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    row = st.db.query_one(VIDEO_SQL + " WHERE v.id=?", (video_id,))
    if not row:
        raise HTTPException(404, "视频不存在")
    return video_dict(row)


@router.patch("/videos/{video_id}")
def patch_video(video_id: int, body: TagIn,
                user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return _apply_tag(get_state(), video_id, body.tag_id)


@router.post("/videos/{video_id}/tag")
def set_tag(video_id: int, body: TagIn,
            user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return _apply_tag(get_state(), video_id, body.tag_id)


@router.post("/videos/{video_id}/rename")
def rename_video(video_id: int, body: RenameIn,
                 user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    row = st.db.query_one("SELECT * FROM videos WHERE id=?", (video_id,))
    if not row:
        raise HTTPException(404, "视频不存在")
    new = (body.name or "").strip().replace("/", "_").replace("\\", "_")
    if not new:
        raise HTTPException(400, "文件名不能为空")
    src = Path(row["path"])
    if not src.exists():
        raise HTTPException(400, "原文件不存在，可能已被移动")
    if not Path(new).suffix:
        ext = (row["ext"] or src.suffix.lstrip(".")).lower().lstrip(".")
        new += f".{ext}" if ext else ""
    dst = src.with_name(new)
    if dst.exists() and dst != src:
        raise HTTPException(409, f"同目录下已存在「{new}」")
    try:
        if dst != src:
            src.rename(dst)
    except OSError as e:
        raise HTTPException(400, f"重命名失败：{e}") from e
    st.db.execute("UPDATE videos SET path=?, filename=?, ext=? WHERE id=?",
                  (str(dst), dst.name, dst.suffix.lower().lstrip("."), video_id))
    updated = st.db.query_one(VIDEO_SQL + " WHERE v.id=?", (video_id,))
    out = video_dict(updated)
    if row["tag_id"] and row["status"] == "tagged":
        out["tag_id"] = row["tag_id"]
    return out


@router.delete("/videos/{video_id}")
def delete_video(video_id: int, file: bool = Query(False, description="是否同时删除磁盘文件"),
                 user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    row = st.db.query_one("SELECT * FROM videos WHERE id=?", (video_id,))
    if not row:
        raise HTTPException(404, "视频不存在")
    removed = False
    if file:
        p = Path(row["path"])
        try:
            if p.exists():
                p.unlink()
                removed = True
        except OSError as e:
            raise HTTPException(400, f"删除文件失败：{e}") from e
    st.db.execute("DELETE FROM videos WHERE id=?", (video_id,))
    thumb = st.cfg.thumb_dir / f"{video_id}.jpg"
    if thumb.exists():
        thumb.unlink(missing_ok=True)
    st.hls.cleanup(video_id)
    return {"ok": True, "file_removed": removed}


@router.get("/videos/{video_id}/thumb")
def thumb(video_id: int, user: dict[str, Any] = Depends(require_user)):
    st = get_state()
    row = st.db.query_one("SELECT * FROM videos WHERE id=?", (video_id,))
    if not row:
        raise HTTPException(404, "视频不存在")
    # 规范命名：缩略图永远叫 <video_id>.jpg（历史数据里可能是时间戳名字或绝对路径，
    # 会在首次访问时按 id 重新生成并修正，从而修好「封面和视频对不上」的旧数据）
    canonical = st.cfg.thumb_dir / f"{video_id}.jpg"
    stored = (row["thumb"] or "").strip()
    legacy: Path | None = None
    if stored:
        legacy = Path(stored)
        if not legacy.is_absolute():
            legacy = st.cfg.thumb_dir / legacy
    if not canonical.exists():
        src = Path(row["path"])
        made = False
        if st.tools.available and src.exists():
            made = make_thumb(st.tools, src, canonical, row["duration"] or 0,
                              st.cfg.get("thumb_position") or 0.15)
        if not made and legacy is not None and legacy.exists():
            # 没有 ffmpeg 时退而用旧文件，但改正记录
            try:
                shutil.copyfile(legacy, canonical)
                made = True
            except OSError:
                made = False
        if made:
            st.db.execute("UPDATE videos SET thumb=? WHERE id=?", (canonical.name, video_id))
        elif legacy is not None and legacy.exists():
            return FileResponse(legacy, media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=60"})
    if canonical.exists():
        # 规范历史记录里的名字（时间戳名 / 绝对路径 / 空）→ 统一成 <id>.jpg
        if stored.rsplit("/", 1)[-1] != canonical.name:
            st.db.execute("UPDATE videos SET thumb=? WHERE id=?", (canonical.name, video_id))
        return FileResponse(canonical, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})
    return JSONResponse({"error": "暂无封面"}, status_code=404)


# ---------- 播放历史 ----------
@router.post("/videos/{video_id}/history")
def save_history(video_id: int, body: HistoryIn,
                 user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    if not st.db.query_one("SELECT id FROM videos WHERE id=?", (video_id,)):
        raise HTTPException(404, "视频不存在")
    st.db.execute(
        "INSERT INTO play_history(video_id, position, duration, watched_at) VALUES(?,?,?,?) "
        "ON CONFLICT(video_id) DO UPDATE SET position=excluded.position, "
        "duration=excluded.duration, watched_at=excluded.watched_at",
        (video_id, max(0.0, body.position), max(0.0, body.duration), now_iso()))
    return {"ok": True}


@router.get("/history")
def list_history(limit: int = Query(60, ge=1, le=500),
                 user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    rows = st.db.query(
        VIDEO_SQL + " WHERE h.video_id IS NOT NULL ORDER BY h.watched_at DESC LIMIT ?", (limit,))
    return {"items": [video_dict(r) for r in rows]}


@router.delete("/history/{video_id}")
def delete_history(video_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    get_state().db.execute("DELETE FROM play_history WHERE video_id=?", (video_id,))
    return {"ok": True}


@router.delete("/history")
def clear_history(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    get_state().db.execute("DELETE FROM play_history")
    return {"ok": True}
