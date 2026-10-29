from __future__ import annotations

import json
import platform
import sys
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..config import DEFAULTS
from ..db import now_iso
from ..state import get_state
from .deps import require_user

router = APIRouter(prefix="/api", tags=["settings"])


class SettingsIn(BaseModel):
    port: int | None = None
    host: str | None = None
    root_dir: str | None = None
    allow_lan: bool | None = None
    theme: str | None = None
    transcode: bool | None = None
    transcode_encoder: str | None = None
    transcode_preset: str | None = None
    transcode_jobs: int | None = None
    thumb_position: float | None = None
    scan_workers: int | None = None
    upload_dir: str | None = None
    discovery: bool | None = None
    discovery_port: int | None = None


@router.get("/settings")
def get_settings(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    return {"settings": st.cfg.values, "defaults": DEFAULTS}


@router.put("/settings")
def put_settings(body: SettingsIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "transcode_jobs" in patch:
        # 0 = 不限并发；负数/超大都夹到合理范围，免得配错把机器拖死
        try:
            patch["transcode_jobs"] = max(0, min(16, int(patch["transcode_jobs"])))
        except (TypeError, ValueError):
            patch.pop("transcode_jobs")
    if "host" in patch and patch["host"] not in {"0.0.0.0", "127.0.0.1", "localhost"}:
        patch.pop("host")
    values = st.cfg.update(patch)
    if "transcode_encoder" in patch:
        # 换了编码器要把探测缓存清掉，否则新选择不会生效
        from ..media import ENCODER_SPECS, reset_encoder_cache
        if patch["transcode_encoder"] not in ENCODER_SPECS and patch["transcode_encoder"] != "auto":
            patch["transcode_encoder"] = "auto"
            st.cfg.update({"transcode_encoder": "auto"})
        reset_encoder_cache()
    if "upload_dir" in patch:
        # 上传目录同时是一条内置源目录，路径变了要同步
        from .sources_routes import ensure_upload_source
        try:
            ensure_upload_source(st)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 上传目录同步失败：{e}")
    return {"ok": True, "settings": values, "restart_required": bool({"port", "host"} & set(patch))}


@router.get("/info")
def info(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    from ..media import encoder_info
    try:
        enc = encoder_info(st.cfg, st.tools)
    except Exception:  # noqa: BLE001  探测失败不影响别的作用
        enc = {"configured": "auto", "resolved": "libx264", "label": "CPU（libx264）",
               "hardware": False, "choices": []}
    return {
        "version": st.cfg.version,
        "data_dir": str(st.cfg.data_dir),
        "platform": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
        "ffmpeg": st.tools.ffmpeg or "",
        "ffprobe": st.tools.ffprobe or "",
        "media_ready": st.tools.available,
        "encoder": enc,
        "root_dir": st.cfg.get("root_dir") or "",
        "upload_dir": st.cfg.get("upload_dir") or "",
        "web_dir": str(st.web_dir or ""),
        "discovery": bool(st.discovery is not None and st.discovery.running),
        "discovery_port": int(st.cfg.get("discovery_port") or 38080),
    }


# ---------------------------------------------------------------------------
# 备份设置 / 导入设置
# ---------------------------------------------------------------------------

EXPORT_FORMAT = "videosorter-settings"
EXPORT_VERSION = 1

# 导出哪些配置项；端口/监听地址属于「这台机器怎么跑」，只放进 server 段做参考，导入时不套用
EXPORT_SETTINGS = (
    "root_dir", "upload_dir", "theme", "transcode", "transcode_encoder", "transcode_preset",
    "transcode_jobs", "thumb_position", "scan_workers", "discovery", "discovery_port", "allow_lan",
)

THEMES = {"light", "dark", "auto"}


class SourceEntry(BaseModel):
    path: str = ""
    kind: str = ""
    enabled: Any = 1


class TagEntry(BaseModel):
    name: str = ""
    color: str = ""
    dir_path: str = ""
    sort_order: Any = None


class ImportIn(BaseModel):
    format: str | None = None
    format_version: Any = None
    app_version: str | None = None
    settings: dict[str, Any] | None = None
    sources: list[SourceEntry] | None = None
    tags: list[TagEntry] | None = None


def _coerce_setting(key: str, value: Any) -> Any:
    """按 DEFAULTS 里的类型做一次宽松转换；非法值抛 400。"""
    default = DEFAULTS.get(key)
    try:
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if isinstance(default, int):
            return int(value)
        if isinstance(default, float):
            return float(value)
        return str(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"配置项 {key} 的值不合法：{value!r}") from None


@router.get("/settings/export")
def export_settings(user: dict[str, Any] = Depends(require_user)) -> Response:
    """把设置 / 源目录 / 标签导出成一个 JSON 文件（浏览器直接下载）。"""
    st = get_state()
    sources = [
        {"path": r["path"], "kind": r["kind"] or "", "enabled": int(r["enabled"] or 0)}
        for r in st.db.query("SELECT path, kind, enabled FROM sources ORDER BY id")
        # 上传目录是派生的内置源，导入时会按 upload_dir 自动重建，不必导出
        if (r["kind"] or "") != "upload"
    ]
    tags = [
        {
            "name": r["name"], "color": r["color"], "dir_path": r["dir_path"],
            "sort_order": int(r["sort_order"] or 0),
        }
        for r in st.db.query("SELECT name, color, dir_path, sort_order FROM tags ORDER BY sort_order, id")
    ]
    payload = {
        "app": "videosorter",
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_VERSION,
        "app_version": st.cfg.version,
        "exported_at": now_iso(),
        "settings": {k: st.cfg.get(k) for k in EXPORT_SETTINGS},
        # 仅供参考，导入不套用（端口/监听地址跟着具体机器走）
        "server": {
            "port": int(st.cfg.get("port") or 8080),
            "host": str(st.cfg.get("host") or "0.0.0.0"),
            "data_dir": str(st.cfg.data_dir),
        },
        "sources": sources,
        "tags": tags,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="videosorter-settings-{stamp}.json"'},
    )


@router.post("/settings/import")
def import_settings(body: ImportIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """把导出的 JSON 套回来：设置覆盖、源目录与标签「缺的补上、有的更新」，不删任何东西。"""
    st = get_state()
    if (body.format or "") != EXPORT_FORMAT:
        raise HTTPException(status_code=400, detail="这不是「视频整理」导出的设置文件")
    try:
        fmt_version = int(body.format_version or 0)
    except (TypeError, ValueError):
        fmt_version = 0
    if fmt_version > EXPORT_VERSION:
        raise HTTPException(status_code=400, detail="备份文件的版本比当前程序新，请先升级服务端")

    patch: dict[str, Any] = {}
    for key, value in (body.settings or {}).items():
        if key not in EXPORT_SETTINGS or value is None:
            continue
        if key == "theme":
            theme = str(value).strip().lower()
            if theme in THEMES:
                patch[key] = theme
            continue
        patch[key] = _coerce_setting(key, value)
    if "discovery_port" in patch and not (1 <= int(patch["discovery_port"]) <= 65535):
        patch.pop("discovery_port")

    if patch:
        st.cfg.update(patch)
    restart_required = bool({"port", "host"} & set(patch))

    added_sources = 0
    skipped_sources = 0
    for entry in body.sources or []:
        path = (entry.path or "").strip()
        if not path or (entry.kind or "") == "upload":
            continue
        if st.db.query_one("SELECT id FROM sources WHERE path=?", (path,)):
            skipped_sources += 1
            continue
        enabled = 0 if str(entry.enabled).strip().lower() in ("0", "false") else 1
        st.db.execute(
            "INSERT INTO sources (path, enabled, kind, created_at) VALUES (?,?,'',?)",
            (path, enabled, now_iso()),
        )
        added_sources += 1

    added_tags = 0
    updated_tags = 0
    for entry in body.tags or []:
        name = (entry.name or "").strip()
        if not name:
            continue
        color = (entry.color or "").strip() or "#8d98a8"
        dir_path = (entry.dir_path or "").strip()
        row = st.db.query_one("SELECT * FROM tags WHERE name=?", (name,))
        if row:
            st.db.execute(
                "UPDATE tags SET color=?, dir_path=? WHERE id=?",
                (color, dir_path, row["id"]),
            )
            updated_tags += 1
            continue
        try:
            order = int(entry.sort_order) if entry.sort_order is not None else 0
        except (TypeError, ValueError):
            order = 0
        st.db.execute(
            "INSERT INTO tags (name, color, dir_path, sort_order, created_at) VALUES (?,?,?,?,?)",
            (name, color, dir_path, order, now_iso()),
        )
        added_tags += 1

    # 上传目录/整理根目录变了：内置上传源要跟着改
    if {"upload_dir", "root_dir"} & set(patch):
        from .sources_routes import ensure_upload_source
        try:
            ensure_upload_source(st)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 上传目录同步失败：{e}")

    return {
        "ok": True,
        "applied": {
            "settings": sorted(patch.keys()),
            "sources_added": added_sources,
            "sources_skipped": skipped_sources,
            "tags_added": added_tags,
            "tags_updated": updated_tags,
        },
        "settings": st.cfg.values,
        "restart_required": restart_required,
    }
