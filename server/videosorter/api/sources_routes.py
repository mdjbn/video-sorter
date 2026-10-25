from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import now_iso
from ..state import get_state
from .deps import require_user

router = APIRouter(prefix="/api", tags=["sources"])


class SourceIn(BaseModel):
    path: str


def _counts(db) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in db.query("SELECT path FROM videos"):
        out[str(Path(r["path"]).parent)] = out.get(str(Path(r["path"]).parent), 0) + 1
    return out


@router.get("/sources")
def list_sources(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    rows = st.db.query("SELECT * FROM sources ORDER BY id")
    out = []
    for r in rows:
        d = dict(r)
        d["exists"] = Path(d["path"]).exists()
        total = st.db.query_one(
            "SELECT COUNT(*) AS n FROM videos WHERE path LIKE ?", (d["path"].rstrip("/") + "/%",))
        d["count"] = int(total["n"]) if total else 0
        out.append(d)
    return {"sources": out}


@router.post("/sources")
def add_source(body: SourceIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    raw = body.path.strip().strip('"')
    if not raw:
        raise HTTPException(status_code=400, detail="请填写目录路径")
    p = Path(raw).expanduser()
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在或不可访问：{raw}")
    path = str(p.resolve())
    if st.db.query_one("SELECT id FROM sources WHERE path=?", (path,)):
        raise HTTPException(status_code=400, detail="这个目录已经添加过了")
    sid = st.db.execute("INSERT INTO sources (path, enabled, created_at) VALUES (?,1,?)", (path, now_iso()))
    # 顺手补齐还没设置目标目录的标签
    for t in st.db.query("SELECT * FROM tags WHERE dir_path='' OR dir_path IS NULL"):
        st.db.execute("UPDATE tags SET dir_path=? WHERE id=?", (str(p / t["name"]), t["id"]))
    return {"ok": True, "source": {"id": sid, "path": path}}


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    row = st.db.query_one("SELECT * FROM sources WHERE id=?", (source_id,))
    if not row:
        raise HTTPException(status_code=404, detail="源目录不存在")
    st.db.execute("DELETE FROM sources WHERE id=?", (source_id,))
    return {"ok": True, "removed": row["path"]}


@router.get("/fs/list")
def list_dirs(path: str = "", user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """给网页端的目录选择器用：列出某个目录下的子目录。"""
    target = Path(path).expanduser() if path else Path.home()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail="目录不存在")
    dirs: list[dict[str, str]] = []
    try:
        for entry in sorted(target.iterdir(), key=lambda x: x.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": str(entry)})
            except OSError:
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail="没有权限读取这个目录") from None
    parent = str(target.parent) if target.parent != target else ""
    sep = "\\" if os.name == "nt" else "/"
    return {"path": str(target), "parent": parent, "sep": sep, "dirs": dirs[:500]}
