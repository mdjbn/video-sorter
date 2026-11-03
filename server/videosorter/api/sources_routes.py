from __future__ import annotations

import json
import os
import string
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import now_iso
from ..pathmatch import under_dir
from ..state import get_state
from .deps import require_user

router = APIRouter(prefix="/api", tags=["sources"])


class SourceIn(BaseModel):
    path: str


def _tag_dirs(st) -> list[tuple[str, Path]]:
    """所有标签的有效目录（[(标签名, 目录)]），用来做「源目录不能压住标签目录」的校验。"""
    from ..organizer import resolve_tag_dir
    out: list[tuple[str, Path]] = []
    for t in st.db.query("SELECT name, dir_path FROM tags"):
        d = resolve_tag_dir(st.db, st.cfg, {"dir_path": t["dir_path"], "name": t["name"]})
        if d is not None:
            out.append((str(t["name"]), Path(d)))
    return out


def _is_upload_source(st, source_id: int) -> bool:
    row = st.db.query_one("SELECT kind FROM sources WHERE id=?", (source_id,))
    return bool(row) and (row["kind"] or "") == "upload"


def check_source_path(st, path: str, *, exclude_source_id: int | None = None,
                      is_upload: bool = False) -> None:
    """源目录的合法性：不能和其它源目录重叠，也不能落在任何标签目录里。

    为什么必须在写入时就拦：扫描范围 = 所有源目录 + 所有标签目录。两处范围一旦
    互相包含，同一个文件就会被扫两次——并发扫描时两边都 INSERT，撞 videos.path
    的 UNIQUE 约束，整轮扫描报 IntegrityError（实测 3 个并发全量扫描，2 个直接失败）。

    例外：**上传目录**（kind='upload'）默认就落在第一个源目录下面（按 README 的设计
    「上传的视频先落到源目录/手机上传」）。它是系统自带的一条源目录，不是用户手工
    添加的，所以对它放行「在另一个源目录内部」这一条；其余规则照常校验。
    """
    from ..paths import overlap_message, overlaps

    for r in st.db.query("SELECT id, path FROM sources"):
        if exclude_source_id is not None and int(r["id"]) == int(exclude_source_id):
            continue
        if is_upload:
            # 上传目录是系统自带的一条源目录，默认就落在第一个源目录下面（README 的设计），
            # 所以「被别的源目录包含」这一条对它放行；但它仍不能包含别人的目录，
            # 那会把别人的文件扫两遍。
            from ..paths import is_under
            if is_under(path, r["path"]):
                raise HTTPException(
                    status_code=400,
                    detail="源文件夹不能重叠：" + overlap_message(path, r["path"], "源文件夹"))
            continue
        if overlaps(path, r["path"]):
            raise HTTPException(
                status_code=400,
                detail="源文件夹不能重叠：" + overlap_message(path, r["path"], "源文件夹"))

    for name, d in _tag_dirs(st):
        if overlaps(path, str(d)):
            raise HTTPException(
                status_code=400,
                detail="源文件夹不能放在标签目录里：" + overlap_message(path, str(d), f"标签「{name}」"))


def upload_dir(st) -> Path:
    """当前生效的上传目录（与 upload_routes._default_dir 保持一致）。"""
    from .upload_routes import _default_dir
    return _default_dir(st)


def ensure_upload_source(st) -> None:
    """把上传目录作为一个内置源目录登记进来：可扫描、可改路径、不可删除。"""
    target = upload_dir(st).expanduser()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    path = str(target)
    row = st.db.query_one("SELECT * FROM sources WHERE kind='upload'")
    if row:
        if row["path"] != path:
            # 上传目录改了路径：同步这条内置源目录（老路径下已入库的视频不动）
            st.db.execute("UPDATE sources SET path=? WHERE id=?", (path, row["id"]))
        return
    if st.db.query_one("SELECT id FROM sources WHERE path=?", (path,)):
        return
    st.db.execute(
        "INSERT INTO sources (path, enabled, kind, created_at) VALUES (?,1,'upload',?)",
        (path, now_iso()))


def _counts(db) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in db.query("SELECT path FROM videos"):
        out[str(Path(r["path"]).parent)] = out.get(str(Path(r["path"]).parent), 0) + 1
    return out


def _parse_scan_result(raw: str | None) -> dict[str, Any] | None:
    """库里的 last_scan_result 是一小段 JSON，坏了就当没有，别让列表接口跟着挂。"""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


@router.get("/sources")
def list_sources(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    ensure_upload_source(st)
    rows = st.db.query("SELECT * FROM sources ORDER BY id")
    out = []
    for r in rows:
        d = dict(r)
        d["exists"] = Path(d["path"]).exists()
        clause, params = under_dir("path", str(d["path"]))
        # 只统计还在盘上的文件：扫描判定为 missing（已删除/移走）的记录不再计数，
        # 否则删掉文件再扫描，卡片上的「N 个视频」也不会掉，看着像「扫不出移除」
        total = st.db.query_one(
            f"SELECT COUNT(*) AS n FROM videos WHERE ({clause}) AND status<>'missing'", params)
        d["count"] = int(total["n"]) if total else 0
        d["kind"] = d.get("kind") or ""
        # 上次扫描结果的原始 JSON（前端解析成 {added, updated, ...}）；没扫过就是 None
        d["last_scan"] = _parse_scan_result(d.pop("last_scan_result", None))
        d["editable"] = True
        d["deletable"] = d["kind"] != "upload"
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
    check_source_path(st, path)
    if path == str(upload_dir(st)):
        raise HTTPException(status_code=400, detail="这就是上传目录，它已经在源文件夹里了")
    sid = st.db.execute("INSERT INTO sources (path, enabled, created_at) VALUES (?,1,?)", (path, now_iso()))
    # 不在这里把源目录硬写进 tags.dir_path：标签目录由 resolve_tag_dir 动态解析
    # （标签自定义 > 全局根目录 > 首个源目录 > 视频所在目录），改 root_dir 或换源目录才会生效。
    # 上传目录默认跟着第一个源目录走（没有显式配置 upload_dir/root_dir 时），加完源目录顺手同步一次。
    ensure_upload_source(st)
    return {"ok": True, "source": {"id": sid, "path": path}}


@router.put("/sources/{source_id}")
def update_source(source_id: int, body: SourceIn,
                  user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """修改源目录路径。内置上传目录改的是 upload_dir（后续上传落到新目录）。"""
    st = get_state()
    row = st.db.query_one("SELECT * FROM sources WHERE id=?", (source_id,))
    if not row:
        raise HTTPException(status_code=404, detail="源目录不存在")
    raw = body.path.strip().strip('"')
    if not raw:
        raise HTTPException(status_code=400, detail="请填写目录路径")
    p = Path(raw).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"目录不可创建或不可访问：{raw}：{e}") from e
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在或不可访问：{raw}")
    path = str(p.resolve())
    if (row["kind"] or "") == "upload":
        if not os.access(path, os.W_OK):
            raise HTTPException(status_code=400, detail=f"目录不可写：{path}")
        # 上传目录可以待在别的源目录里面（默认就是这样），但不能把它换成某个
        # 源目录的上级——那样它会把别人的文件也扫一遍。
        check_source_path(st, path, exclude_source_id=source_id, is_upload=True)
        st.cfg.update({"upload_dir": path})
        st.cfg.save()
        st.db.execute("UPDATE sources SET path=? WHERE id=?", (path, source_id))
        return {"ok": True, "source": {"id": source_id, "path": path, "kind": "upload"}}
    dup = st.db.query_one("SELECT id FROM sources WHERE path=? AND id<>?", (path, source_id))
    if dup:
        raise HTTPException(status_code=400, detail="这个目录已经添加过了")
    check_source_path(st, path, exclude_source_id=source_id, is_upload=_is_upload_source(st, source_id))
    st.db.execute("UPDATE sources SET path=? WHERE id=?", (path, source_id))
    return {"ok": True, "source": {"id": source_id, "path": path, "kind": ""}}


def _purge_media(st, ids: list[int]) -> None:
    """删源之后清缩略图与转码产物。放后台做：几千个文件的 unlink/rmtree 比 SQL 慢得多，
    用户在网页上等的只是「列表里视频没了」，不该等这些文件。"""
    thumbs = st.cfg.thumb_dir
    for vid in ids:
        try:
            (thumbs / f"{vid}.jpg").unlink(missing_ok=True)
        except OSError:
            pass
        try:
            st.hls.cleanup(vid)
        except Exception:
            pass


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    row = st.db.query_one("SELECT * FROM sources WHERE id=?", (source_id,))
    if not row:
        raise HTTPException(status_code=404, detail="源目录不存在")
    if (row["kind"] or "") == "upload":
        raise HTTPException(status_code=400, detail="上传目录不能删除，只能修改路径")
    # 源文件夹移除后，其下视频同步从视频库删除；播放记录保留并标注「视频已删除」。
    # 注意：必须一条语句批量改删（以前是每条视频两次 execute，等于几千次开启连接 + commit，
    # NAS 上删一个 5000 条的源要 77 秒）。现在整个删除在同一个事务里，文件清理丢后台。
    scope, scope_params = under_dir("path", str(row["path"]))
    with st.db.tx() as c:
        # 先补文件名再删 videos：子查询依赖 videos 里还有记录
        c.execute(
            "UPDATE play_history SET deleted=1, "
            "filename=CASE WHEN filename='' THEN COALESCE("
            "(SELECT v.filename FROM videos v WHERE v.id=play_history.video_id), '') "
            "ELSE filename END "
            f"WHERE video_id IN (SELECT id FROM videos WHERE {scope})",
            scope_params)
        ids = [int(r[0]) for r in c.execute(f"SELECT id FROM videos WHERE {scope}", scope_params)]
        c.execute(f"DELETE FROM videos WHERE {scope}", scope_params)
        c.execute("DELETE FROM sources WHERE id=?", (source_id,))
    if ids:
        threading.Thread(target=_purge_media, args=(st, ids), daemon=True).start()
    return {"ok": True, "removed": row["path"], "videos_removed": len(ids)}


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


@router.get("/fs/roots")
def fs_roots(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """目录选择器的快捷入口：返回这台机器上常见的几个根目录。"""
    st = get_state()
    roots: list[dict[str, str]] = []

    def add(name: str, path: str | Path | None) -> None:
        if path is None or str(path).strip() == "":
            return
        p = Path(str(path))
        try:
            if not p.is_dir():
                return
        except OSError:
            return
        key = str(p)
        if any(r["path"] == key for r in roots):
            return
        roots.append({"name": name, "path": key})

    add("主目录", Path.home())
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            add(f"{letter}: 盘", f"{letter}:\\")
    else:
        add("根目录", "/")
        for candidate in ("/vol1", "/volume1", "/mnt", "/media", "/srv", "/data"):
            add(candidate, candidate)
    add("数据目录", getattr(st.cfg, "data_dir", None))
    add("整理根目录", st.cfg.get("root_dir"))
    return {"roots": roots, "home": str(Path.home())}
