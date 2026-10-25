"""整理：预览计划、执行（后台任务）、记录、撤销。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import organizer
from ..state import get_state
from .deps import require_user

router = APIRouter(prefix="/api/organize", tags=["organize"])


class PlanIn(BaseModel):
    tag_ids: list[int] | None = None
    video_ids: list[int] | None = None


@router.post("/preview")
def preview(body: PlanIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    return organizer.build_plan(st.db, st.cfg, body.tag_ids, body.video_ids)


@router.post("/execute")
def execute(body: PlanIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    plan = organizer.build_plan(st.db, st.cfg, body.tag_ids, body.video_ids)
    if not plan["items"]:
        raise HTTPException(400, "没有需要整理的视频（需要先打标签）")
    tid = st.tasks.spawn("organize", lambda t: organizer.execute_plan(
        st.db, st.cfg, st.tasks, t, body.tag_ids, body.video_ids, None))
    return {"task_id": tid, "planned": plan["total"], "bytes": plan["total_bytes"]}


@router.get("/records")
def records(limit: int = 50, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {"items": organizer.list_batches(get_state().db, limit)}


@router.post("/undo/{batch_id}")
def undo(batch_id: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    try:
        return organizer.undo_batch(get_state().db, batch_id)
    except organizer.OrganizeError as e:
        raise HTTPException(400, str(e)) from e
