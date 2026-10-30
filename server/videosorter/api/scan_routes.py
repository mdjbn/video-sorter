from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import organizer
from ..scanner import scan_sources
from ..state import get_state
from .deps import require_user

router = APIRouter(prefix="/api", tags=["scan"])


class ScanIn(BaseModel):
    source_ids: list[int] | None = None
    # 只扫指定标签的目标文件夹（新建标签后立刻入库用）。给了 tag_ids 又没给 source_ids 时
    # 就不扫源文件夹，避免一次小改动触发整库扫描。
    tag_ids: list[int] | None = None
    full: bool = False


@router.post("/scan")
def start_scan(body: ScanIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    if not st.tools.available:
        raise HTTPException(status_code=400, detail="未找到 ffmpeg/ffprobe，无法扫描")
    label = "扫描标签文件夹" if (body.tag_ids and not body.source_ids) else "扫描源文件夹"
    # 只读扫描本身不需要写权限，所以不可写不拦扫描；但结果要带回去，让用户提前知道
    # 「扫完也整理不了」。预检结果写进任务 extra，前端轮询 /api/tasks/{id} 就能拿到。
    unwritable = organizer.check_roots_writable(st.db, st.cfg)
    tid = st.tasks.spawn("scan", lambda t: scan_sources(st.db, st.cfg, st.tools, st.tasks, t,
                                                       body.source_ids, body.full, body.tag_ids),
                         label=label, unwritable=unwritable)
    return {"ok": True, "task_id": tid, "unwritable": unwritable}


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
