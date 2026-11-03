from __future__ import annotations

import json
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
    # 必填：标签的目标文件夹。留空会让「这个标签的文件到底在哪个目录」变成隐式推导
    # （源目录/标签名），而那个默认位置恰好会落进源目录内部，导致同一个文件被源目录
    # 和标签目录各扫一次。所以要求用户显式指定。
    dir_path: str


class TagPatch(BaseModel):
    name: str | None = None
    color: str | None = None
    dir_path: str | None = None
    sort_order: int | None = None


def _source_paths(st) -> list[str]:
    return [str(r["path"]) for r in st.db.query("SELECT path FROM sources WHERE enabled=1")]


def check_tag_dir(st, dir_path: str, *, exclude_tag_id: int | None = None) -> str:
    """标签目录的合法性，返回规范化后的路径。

    规则：必填；不能落在任何源目录里；不能和别的标签目录重叠（含互相包含）。
    和源目录那条对称——两处扫描范围一旦重叠，同一个文件会被扫两次，并发时撞
    videos.path 的 UNIQUE 约束。
    """
    from ..paths import norm_path, overlap_message, overlaps

    raw = (dir_path or "").strip().strip('"')
    if not raw:
        raise HTTPException(status_code=400, detail="请填写这个标签的目标文件夹")
    path = norm_path(raw)

    for src in _source_paths(st):
        if overlaps(path, src):
            raise HTTPException(
                status_code=400,
                detail="标签目录不能放在源文件夹里：" + overlap_message(path, src, "源文件夹"))

    for t in st.db.query("SELECT id, name, dir_path FROM tags"):
        if exclude_tag_id is not None and int(t["id"]) == int(exclude_tag_id):
            continue
        d = resolve_tag_dir(st.db, st.cfg, {"dir_path": t["dir_path"], "name": t["name"]})
        if d is not None and overlaps(path, str(d)):
            raise HTTPException(
                status_code=400,
                detail="标签之间不能重叠：" + overlap_message(path, str(d), f"标签「{t['name']}」"))
    return path


def _parse_scan_result(raw: str | None) -> dict[str, Any] | None:
    """库里的 last_scan_result 是一小段 JSON，坏了就当没有，别让列表接口跟着挂。"""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _serialize(row: Any, counts: dict[int, int], st) -> dict[str, Any]:
    d = dict(row)
    tag = {"name": d["name"], "dir_path": d["dir_path"]}
    d["count"] = counts.get(d["id"], 0)
    d["default_dir"] = default_tag_dir(st.db, st.cfg, d["name"])
    eff = resolve_tag_dir(st.db, st.cfg, tag)
    d["effective_dir"] = str(eff) if eff else ""
    # 上次扫描结果的原始 JSON（前端把它解析成 {added, updated, ...}）；没扫过就是 None
    d["last_scan"] = _parse_scan_result(d.pop("last_scan_result", None))
    return d


@router.get("")
def list_tags(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    rows = st.db.query("SELECT * FROM tags ORDER BY sort_order, id")
    counts = {r["tag_id"]: r["n"] for r in
              st.db.query("SELECT tag_id, COUNT(*) AS n FROM videos WHERE tag_id IS NOT NULL GROUP BY tag_id")}
    return {"tags": [_serialize(r, counts, st) for r in rows]}


@router.get("/default-dir")
def tag_default_dir(name: str = "", user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """新建标签时建议的目标文件夹。

    默认规则和以前一致：全局根目录/标签名 → 首个源目录/标签名。
    v1.3.9 起建标签必须带 dir_path，而手机 App 从播放页「新建标签」时没有输入框，
    靠这个接口把建议值填进去，免得一律报 422。
    """
    st = get_state()
    return {"dir": default_tag_dir(st.db, st.cfg, (name or "").strip())}


@router.post("")
def create_tag(body: TagIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    if st.db.query_one("SELECT id FROM tags WHERE name=?", (name,)):
        raise HTTPException(status_code=400, detail="已存在同名标签")
    # 目录必填且要合规（不在源目录里、不和别的标签目录重叠），见 check_tag_dir。
    dir_path = check_tag_dir(st, body.dir_path)
    order = (st.db.query_one("SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM tags") or {"n": 1})["n"]
    tid = st.db.execute(
        "INSERT INTO tags (name, color, dir_path, sort_order, created_at) VALUES (?,?,?,?,?)",
        (name, body.color, dir_path, order, now_iso()))
    row = st.db.query_one("SELECT * FROM tags WHERE id=?", (tid,))
    return {"ok": True, "tag": _serialize(row, {}, st)}


class TagOrderIn(BaseModel):
    ids: list[int]


@router.put("/order")
def reorder_tags(body: TagOrderIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """按前端拖拽结果的顺序重排标签（只改 sort_order）。

    - 只接受已知的 id，重复项与未知项忽略；
    - 前端没提到的标签按原相对顺序排在后面，保证不会「丢标签」。
    """
    st = get_state()
    existing = [r["id"] for r in st.db.query("SELECT id FROM tags ORDER BY sort_order, id")]
    known = set(existing)
    order: list[int] = []
    seen: set[int] = set()
    for tid in body.ids:
        if tid in known and tid not in seen:
            seen.add(tid)
            order.append(tid)
    order.extend(tid for tid in existing if tid not in seen)
    for idx, tid in enumerate(order):
        st.db.execute("UPDATE tags SET sort_order=? WHERE id=?", (idx + 1, tid))
    rows = st.db.query("SELECT * FROM tags ORDER BY sort_order, id")
    counts = {r["tag_id"]: r["n"] for r in
              st.db.query("SELECT tag_id, COUNT(*) AS n FROM videos WHERE tag_id IS NOT NULL GROUP BY tag_id")}
    return {"ok": True, "order": order, "tags": [_serialize(r, counts, st) for r in rows]}


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
    if "dir_path" in patch:
        patch["dir_path"] = check_tag_dir(st, str(patch["dir_path"]), exclude_tag_id=tag_id)
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
