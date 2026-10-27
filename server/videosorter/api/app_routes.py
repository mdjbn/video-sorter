"""手机 App 安装包分发：让网页端/手机浏览器可以直接下载 APK。

安装包查找顺序：
1. 数据目录下的 apk/（想换新版本时只要把 apk 丢进去，不必重装）
2. 网页端目录旁边的 apk/（fpk 包里自带：app/webdist + app/apk）
3. 开发环境的仓库 dist/android/ 或仓库根 apk/
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import __version__
from ..state import get_state

router = APIRouter(tags=["app"])

APK_MIME = "application/vnd.android.package-archive"
_VERSION_RE = re.compile(r"videosorter-(\d+\.\d+\.\d+)-(arm64-v8a|armeabi-v7a|x86_64)\.apk$")


def _apk_dirs() -> list[Path]:
    st = get_state()
    dirs: list[Path] = [st.cfg.data_dir / "apk"]
    if st.web_dir:
        dirs.append(Path(st.web_dir).parent / "apk")
    here = Path(__file__).resolve()
    # 开发环境：server/videosorter/api/app_routes.py -> 仓库根
    repo = here.parent.parent.parent.parent
    dirs += [repo / "apk", repo / "dist" / "android", repo / "web" / "public" / "apk"]
    return dirs


def _find_apks() -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for d in _apk_dirs():
        try:
            if not d.is_dir():
                continue
        except OSError:
            continue
        for f in sorted(d.glob("*.apk")):
            try:
                if not f.is_file():
                    continue
                name = f.name
                if name in seen:
                    continue
                seen.add(name)
                m = _VERSION_RE.search(name)
                out.append({
                    "name": name,
                    "abi": m.group(2) if m else "unknown",
                    "version": m.group(1) if m else "",
                    "size": f.stat().st_size,
                    "url": f"/api/app/apk/{name}",
                })
            except OSError:
                continue
    # arm64 排前面，其次 v7a
    order = {"arm64-v8a": 0, "armeabi-v7a": 1, "x86_64": 2}
    out.sort(key=lambda x: (order.get(x["abi"], 9), x["name"]))
    return out


@router.get("/api/app/apk")
def list_apks() -> dict:
    """列出服务器上可下载的 APK；apps 为空时前端只展示 GitHub Releases 入口。"""
    return {
        "version": __version__,
        "apps": _find_apks(),
        "releases": "https://github.com/mdjbn/video-sorter/releases/latest",
    }


@router.get("/api/app/apk/{name}")
def download_apk(name: str) -> FileResponse:
    if not name.endswith(".apk") or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(404, "文件不存在")
    for d in _apk_dirs():
        try:
            f = (d / name).resolve()
            if f.is_file() and str(f).startswith(str(d.resolve())):
                return FileResponse(
                    f,
                    media_type=APK_MIME,
                    filename=name,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'},
                )
        except OSError:
            continue
    raise HTTPException(404, "服务器上还没有这个安装包，请到 GitHub Releases 下载")
