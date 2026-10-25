from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..scanner import scan_sources
from ..state import get_state
from .deps import require_user

router = APIRouter(prefix="/api", tags=["scan"])


class ScanIn(BaseModel):
    source_ids: list[int] | None = None
    full: bool = False


@router.post("/scan")
def start_scan(body: ScanIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    if not st.tools.available:
        raise HTTPException(status_code=400, detail="未找到 ffmpeg/ffprobe，无法扫描")
    tid = st.tasks.spawn("scan", lambda t: scan_sources(st.db, st.cfg, st.tools, st.tasks, t,
                                                       body.source_ids, body.full),
                         label="扫描源文件夹")
    return {"ok": True, "task_id": tid}


@router.get("/tasks/{task_id}")
def task_status(task_id: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    t = st.tasks.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return t


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    if not st.tasks.get(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    st.tasks.cancel(task_id)
    return {"ok": True}
