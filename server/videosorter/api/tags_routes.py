from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import now_iso
from ..organizer import default_tag_dir, resolve_tag_dir
from ..state import get_state
from .deps import require_user

router = APIRouter(prefix="/api/tags", tags=["tags"])


class TagIn(BaseModel):
    name: str
    color: str = "#8d98a8"
    dir_path: str = ""


class TagPatch(BaseModel):
    name: str | None = None
    color: str | None = None
    dir_path: str | None = None
    sort_order: int | None = None


def _serialize(row: Any, counts: dict[int, int], st) -> dict[str, Any]:
    d = dict(row)
    tag = {"name": d["name"], "dir_path": d["dir_path"]}
    d["count"] = counts.get(d["id"], 0)
    d["default_dir"] = default_tag_dir(st.db, st.cfg, d["name"])
    eff = resolve_tag_dir(st.db, st.cfg, tag)
    d["effective_dir"] = str(eff) if eff else ""
    return d


@router.get("")
def list_tags(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    rows = st.db.query("SELECT * FROM tags ORDER BY sort_order, id")
    counts = {r["tag_id"]: r["n"] for r in
              st.db.query("SELECT tag_id, COUNT(*) AS n FROM videos WHERE tag_id IS NOT NULL GROUP BY tag_id")}
    return {"tags": [_serialize(r, counts, st) for r in rows]}


@router.post("")
def create_tag(body: TagIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    if st.db.query_one("SELECT id FROM tags WHERE name=?", (name,)):
        raise HTTPException(status_code=400, detail="已存在同名标签")
    # dir_path 只在用户明确填写时落库；留空表示「跟随默认目录」，由 resolve_tag_dir 现场算。
    # 以前这里会把 default_tag_dir() 的结果写死进 tags.dir_path，导致「先建标签、之后在设置里
    # 改全局根目录」永远不生效（resolve_tag_dir 最优先用标签自己的 dir_path）。
    dir_path = body.dir_path.strip()
    order = (st.db.query_one("SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM tags") or {"n": 1})["n"]
    tid = st.db.execute(
        "INSERT INTO tags (name, color, dir_path, sort_order, created_at) VALUES (?,?,?,?,?)",
        (name, body.color, dir_path, order, now_iso()))
    row = st.db.query_one("SELECT * FROM tags WHERE id=?", (tid,))
    return {"ok": True, "tag": _serialize(row, {}, st)}


@router.put("/{tag_id}")
def update_tag(tag_id: int, body: TagPatch, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    row = st.db.query_one("SELECT * FROM tags WHERE id=?", (tag_id,))
    if not row:
        raise HTTPException(status_code=404, detail="标签不存在")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "name" in patch:
        patch["name"] = patch["name"].strip()
        if not patch["name"]:
            raise HTTPException(status_code=400, detail="标签名不能为空")
        if st.db.query_one("SELECT id FROM tags WHERE name=? AND id<>?", (patch["name"], tag_id)):
            raise HTTPException(status_code=400, detail="已存在同名标签")
    if not patch:
        return {"ok": True, "tag": _serialize(row, {}, st)}
    sets = ", ".join(f"{k}=?" for k in patch)
    st.db.execute(f"UPDATE tags SET {sets} WHERE id=?", (*patch.values(), tag_id))
    row = st.db.query_one("SELECT * FROM tags WHERE id=?", (tag_id,))
    counts = {r["tag_id"]: r["n"] for r in
              st.db.query("SELECT tag_id, COUNT(*) AS n FROM videos WHERE tag_id IS NOT NULL GROUP BY tag_id")}
    return {"ok": True, "tag": _serialize(row, counts, st)}


@router.delete("/{tag_id}")
def delete_tag(tag_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    row = st.db.query_one("SELECT * FROM tags WHERE id=?", (tag_id,))
    if not row:
        raise HTTPException(status_code=404, detail="标签不存在")
    n = (st.db.query_one("SELECT COUNT(*) AS n FROM videos WHERE tag_id=?", (tag_id,)) or {"n": 0})["n"]
    st.db.execute(
        "UPDATE videos SET tag_id=NULL, status=CASE WHEN status='organized' THEN 'organized' ELSE 'idle' END "
        "WHERE tag_id=?", (tag_id,))
    st.db.execute("DELETE FROM tags WHERE id=?", (tag_id,))
    return {"ok": True, "released": n}
