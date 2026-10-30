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
    plan = organizer.build_plan(st.db, st.cfg, body.tag_ids, body.video_ids)
    # 新增字段（不影响原有 items/skipped/groups/total/total_bytes/renamed）：
    #   unwritable      [{"path","kind":"source"|"tag","reason"}] 不可写的根目录
    #   blocked         [{"path","reason","count"}] 因目标目录不可写而整理不了的汇总
    #   blocked_count   int 被挡住的视频数
    unwritable = organizer.check_roots_writable(st.db, st.cfg, plan["items"])
    res = organizer.resolve_plan_unwritable(plan["items"], unwritable)
    plan["unwritable"] = unwritable
    plan["blocked"] = organizer.skip_summary(res["dropped"])
    plan["blocked_count"] = len(res["dropped"])
    return plan


@router.post("/execute")
def execute(body: PlanIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    if body.tag_ids is not None and len(body.tag_ids) == 0:
        raise HTTPException(400, "没有选中任何标签")
    plan = organizer.build_plan(st.db, st.cfg, body.tag_ids, body.video_ids)
    if not plan["items"]:
        raise HTTPException(400, "没有需要整理的视频（需要先打标签）")

    # 写权限预检：目标目录不可写的项先剔掉，剩下的照常跑，别等搬到一半才报 Permission denied。
    # 只按计划项自己的目标目录判定（plan_items），否则标签的全局默认目录会把别的标签也带进来。
    unwritable = organizer.check_roots_writable(st.db, st.cfg, plan["items"])
    res = organizer.resolve_plan_unwritable(plan["items"], unwritable)
    skipped_reasons = organizer.skip_summary(res["dropped"])
    skipped_ids = {d["video_id"] for d in res["dropped"]}
    items = res["items"]
    if not items:
        first = res["paths"][0] if res["paths"] else (unwritable[0]["path"] if unwritable else "")
        raise HTTPException(
            400, f"目标目录不可写：{first}（服务用户没有写权限，请调整目录权限后重试）")

    tid = st.tasks.spawn("organize", lambda t: organizer.execute_plan(
        st.db, st.cfg, st.tasks, t, None, None, items, unwritable),
        unwritable=unwritable, skipped=len(skipped_ids), skipped_reasons=skipped_reasons,
        skipped_video_ids=sorted(skipped_ids))
    # 新增字段：skipped/skipped_reasons/unwritable/excluded（原 task_id/planned/bytes 保留，
    # planned/bytes 现在只算真正要搬的，不含被跳过的）
    # skipped: 被跳过的条数（因为目标目录不可写而剔掉的）
    # skipped_reasons: [{"path","reason","count"}]，按目录汇总，前端可直接显示
    # unwritable: [{"path","kind","reason"}]，整个预检结果
    # excluded: 被剔掉的视频明细 [{video_id,name,reason}]，网页可以列出来让用户知道漏了哪些
    excluded = [{"video_id": d.get("video_id"), "name": d.get("name"),
                 "reason": f"目标目录不可写：{d.get('path')}"} for d in res["dropped"]]
    return {"task_id": tid, "planned": len(items), "bytes": sum(int(i["size"] or 0) for i in items),
            "skipped": len(excluded), "skipped_reasons": skipped_reasons,
            "unwritable": unwritable, "excluded": excluded}


@router.get("/records")
def records(limit: int = 50, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {"items": organizer.list_batches(get_state().db, limit)}


@router.post("/undo/{batch_id}")
def undo(batch_id: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    try:
        return organizer.undo_batch(get_state().db, batch_id)
    except organizer.OrganizeError as e:
        raise HTTPException(400, str(e)) from e
