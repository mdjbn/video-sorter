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
from ..pathmatch import under_dir
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
    tags: str = Query("", description="多标签筛选，逗号分隔的标签 id，如 1,3"),
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
        where.append("v.status<>'missing'")
    elif status == "missing":
        where.append("v.status='missing'")
    elif status in STATUSES:
        where.append("v.status=?")
        args.append(status)
    else:
        # 默认（all）：文件已被删除/移走的记录不再出现在视频库与播放列表里
        if "missing" in STATUSES:
            where.append("v.status<>'missing'")
    picked = [int(x) for x in tags.replace("，", ",").split(",") if x.strip().isdigit()]
    if picked:
        # 多标签并集：勾了几个标签就显示这几个标签下的视频
        where.append("v.tag_id IN (" + ",".join("?" * len(picked)) + ")")
        args.extend(picked)
    elif tag == "none":
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
    # 两组卡片：来自源文件夹的（还没整理）／来自标签对应文件夹的（已整理）
    counts["organized"] = st.db.query_one(
        "SELECT COUNT(*) AS n FROM videos WHERE status='organized'")["n"]
    counts["source"] = st.db.query_one(
        "SELECT COUNT(*) AS n FROM videos WHERE status IN ('idle','tagged')")["n"]
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
        scope, scope_params = under_dir("path", str(s["path"]))
        s["count"] = st.db.query_one(
            f"SELECT COUNT(*) AS n FROM videos WHERE {scope}", scope_params)["n"]
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
    # 播放记录保留下来并标注「视频已删除」（历史里仍能看到这条，只是不能播放）
    st.db.execute(
        "UPDATE play_history SET deleted=1, filename=CASE WHEN filename='' THEN ? ELSE filename END "
        "WHERE video_id=?", (row["filename"] or "", video_id))
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
                              st.cfg.get("thumb_position") or 0.0)
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
    row = st.db.query_one("SELECT filename FROM videos WHERE id=?", (video_id,))
    fname = ((row["filename"] if row else "") or "").strip()
    st.db.execute(
        "INSERT INTO play_history(video_id, position, duration, watched_at, filename, deleted) "
        "VALUES(?,?,?,?,?,0) "
        "ON CONFLICT(video_id) DO UPDATE SET position=excluded.position, "
        "duration=excluded.duration, watched_at=excluded.watched_at, "
        "filename=excluded.filename, deleted=0",
        (video_id, max(0.0, body.position), max(0.0, body.duration), now_iso(), fname))
    # 同一个视频（同名文件）只保留最新一条：重扫后会产生新 id，旧记录清掉
    if fname:
        st.db.execute("DELETE FROM play_history WHERE filename=? AND video_id<>?", (fname, video_id))
    return {"ok": True}


@router.get("/history")
def list_history(limit: int = Query(60, ge=1, le=500),
                 user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    rows = st.db.query(
        "SELECT h.video_id AS h_video_id, h.position AS h_position, h.duration AS h_duration, "
        "h.watched_at AS h_watched_at, h.filename AS h_filename, h.deleted AS h_deleted, "
        "v.*, t.name AS tag_name, t.color AS tag_color, t.dir_path AS tag_dir "
        "FROM play_history h "
        "LEFT JOIN videos v ON v.id = h.video_id "
        "LEFT JOIN tags t ON t.id = v.tag_id "
        "ORDER BY h.watched_at DESC LIMIT ?", (limit,))
    items: list[dict[str, Any]] = []
    for r in rows:
        if r["id"] is None:
            # 视频已被删除：用快照信息展示，前端标注「视频已删除」
            items.append({
                "id": r["h_video_id"],
                "filename": r["h_filename"] or "（已删除的视频）",
                "path": "",
                "ext": "",
                "duration": float(r["h_duration"] or 0),
                "size": 0,
                "status": "deleted",
                "tag_id": None,
                "tag_name": None,
                "tag_color": None,
                "position": float(r["h_position"] or 0),
                "watched_at": r["h_watched_at"],
                "thumb_url": None,
                "raw_url": None,
                "deleted": True,
                "organized": False,
                "has_tag": False,
            })
        else:
            d = video_dict(r)
            d["position"] = float(r["h_position"] or 0)
            d["watched_at"] = r["h_watched_at"]
            d["deleted"] = bool(r["h_deleted"])
            items.append(d)
    return {"items": items}


@router.delete("/history/{video_id}")
def delete_history(video_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    get_state().db.execute("DELETE FROM play_history WHERE video_id=?", (video_id,))
    return {"ok": True}


@router.delete("/history")
def clear_history(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    get_state().db.execute("DELETE FROM play_history")
    return {"ok": True}
