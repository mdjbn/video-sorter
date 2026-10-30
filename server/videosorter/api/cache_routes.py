"""缓存：缩略图与转码分片的占用统计与清理。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..state import get_state
from .deps import require_user

router = APIRouter(prefix="/api/cache", tags=["cache"])


class ClearIn(BaseModel):
    target: str = "all"          # all | hls | thumbs


def _stats(p: Path) -> dict[str, Any]:
    count = 0
    size = 0
    if p.is_dir():
        for f in p.rglob("*"):
            if f.is_file():
                count += 1
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
    return {"count": count, "bytes": size}


def _serialize(st) -> dict[str, Any]:
    thumbs = _stats(st.cfg.thumb_dir)
    hls = _stats(st.cfg.hls_dir)
    return {
        "thumbs": thumbs,
        "hls": hls,
        "total_bytes": thumbs["bytes"] + hls["bytes"],
        # 转码缓存自动清理的策略与当前占用：网页/安卓的缓存页拿它画进度条、算还能删多少
        "hls_used_bytes": hls["bytes"],
        "hls_limit_mb": _limit_mb(st),
        "hls_max_age_hours": _max_age_hours(st),
        "data_dir": str(st.cfg.data_dir),
        "thumb_dir": str(st.cfg.thumb_dir),
        "hls_dir": str(st.cfg.hls_dir),
    }


def _limit_mb(st) -> int:
    try:
        return max(0, int(st.cfg.get("hls_cache_limit_mb", 4096) or 0))
    except (TypeError, ValueError):
        return 0


def _max_age_hours(st) -> int:
    try:
        return max(0, int(st.cfg.get("hls_cache_max_age_hours", 168) or 0))
    except (TypeError, ValueError):
        return 0


@router.get("")
def cache_info(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return _serialize(get_state())


@router.post("/sweep")
def sweep_cache(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """按上限/保留期清一次转码缓存（缓存页「立即清理超额缓存」用）。

    只清 `data/hls` 下的转码分片，不动缩略图；正在转码的视频自动跳过。
    返回 sweep_hls 的统计 + 清理后的缓存概况。
    """
    st = get_state()
    from ..cache import sweep_hls
    result = sweep_hls(st.cfg, st.hls)
    return {"ok": True, **result, **_serialize(st)}


@router.post("/clear")
def clear_cache(body: ClearIn | None = None,
                user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    target = (body.target if body else "all") or "all"
    freed = 0
    if target in ("hls", "all"):
        freed += _stats(st.cfg.hls_dir)["bytes"]
        if st.hls is not None:
            st.hls.clear_all()
        else:
            shutil.rmtree(st.cfg.hls_dir, ignore_errors=True)
    if target in ("thumbs", "all"):
        # 封面删掉即可，列表/播放时会按需重新生成
        freed += _stats(st.cfg.thumb_dir)["bytes"]
        shutil.rmtree(st.cfg.thumb_dir, ignore_errors=True)
    return {"ok": True, "freed_bytes": freed, **_serialize(st)}
