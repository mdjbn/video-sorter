from __future__ import annotations

import platform
import sys
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import DEFAULTS
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
    transcode_preset: str | None = None
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
    if "host" in patch and patch["host"] not in {"0.0.0.0", "127.0.0.1", "localhost"}:
        patch.pop("host")
    values = st.cfg.update(patch)
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
    return {
        "version": st.cfg.version,
        "data_dir": str(st.cfg.data_dir),
        "platform": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
        "ffmpeg": st.tools.ffmpeg or "",
        "ffprobe": st.tools.ffprobe or "",
        "media_ready": st.tools.available,
        "root_dir": st.cfg.get("root_dir") or "",
        "upload_dir": st.cfg.get("upload_dir") or "",
        "web_dir": str(st.web_dir or ""),
        "discovery": bool(st.discovery is not None and st.discovery.running),
        "discovery_port": int(st.cfg.get("discovery_port") or 38080),
    }
