"""FastAPI 应用装配：API 路由 + 网页端静态托管（同一端口、无 CORS）。"""
from __future__ import annotations

import logging
import platform
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__
from .api import (auth_routes, organize_routes, scan_routes, settings_routes,
                  sources_routes, stream_routes, tags_routes, upload_routes,
                  videos_routes)
from .config import Config
from .discovery import DISCOVERY_PORT, DiscoveryService
from .state import get_state, init

log = logging.getLogger("videosorter")

API_ROUTERS = [auth_routes, settings_routes, tags_routes, sources_routes, scan_routes,
               videos_routes, stream_routes, organize_routes, upload_routes]

PLACEHOLDER = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>VideoSorter</title>
<style>body{{background:#0b0e13;color:#e8edf3;font-family:system-ui,sans-serif;
display:grid;place-items:center;height:100vh;margin:0}}div{{max-width:560px;padding:28px;
background:#12161d;border:1px solid #232932;border-radius:14px}}code{{color:#35d18a}}</style>
<div><h2>视频整理服务已启动</h2>
<p>网页端还没构建。先执行：</p>
<p><code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code></p>
<p>然后刷新本页。API 文档在 <a style="color:#35d18a" href="/docs">/docs</a>。</p></div></html>"""


def default_web_dir() -> Path | None:
    """按优先级找一个可用的网页端构建产物目录。"""
    here = Path(__file__).resolve()
    candidates = [
        # PyInstaller onedir：可执行文件旁边 / _internal 里
        Path(sys.executable).parent / "webdist",
        Path(getattr(sys, "_MEIPASS", here.parent)) / "webdist",
        here.parent.parent / "webdist",
        # 开发时：server/web/dist、仓库根/web/dist
        here.parent.parent / "web" / "dist",
        here.parent.parent.parent / "web" / "dist",
        here.parent / "webdist",
    ]
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return None


def create_app(cfg: Config | None = None, web_dir: Path | str | None = None) -> FastAPI:
    cfg = cfg or Config()
    wd = Path(web_dir) if web_dir else default_web_dir()
    st = init(cfg, wd)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # 局域网发现：手机 App 广播 VS_DISCOVER，这里回包告诉它端口/名称
        if cfg.get("discovery", True) and st.discovery is None:
            st.discovery = DiscoveryService(
                int(cfg.get("discovery_port", DISCOVERY_PORT)),
                int(cfg.get("port") or 8080),
            )
        if st.discovery is not None:
            st.discovery.start()
        try:
            yield
        finally:
            if st.discovery is not None:
                st.discovery.stop()

    app = FastAPI(title=APP_NAME, version=__version__,
                  description="本地视频分类整理服务（扫描 / 打标签 / 按标签移动）",
                  lifespan=lifespan)
    app.state.cfg = cfg
    app.state.web_dir = wd

    for mod in API_ROUTERS:
        app.include_router(mod.router)
    app.include_router(stream_routes.status_router)

    @app.get("/api/health")
    def health() -> dict:
        st = get_state()
        return {
            "ok": True, "app": APP_NAME, "version": __version__,
            "media_ready": st.tools.available,
            "ffmpeg": st.tools.ffmpeg or "", "ffprobe": st.tools.ffprobe or "",
            "platform": platform.platform(), "python": sys.version.split()[0],
            "web": bool(wd), "data_dir": str(cfg.data_dir),
            "discovery": bool(st.discovery is not None and st.discovery.running),
        }

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail, "status": exc.status_code},
                            status_code=exc.status_code)

    if wd and (wd / "index.html").exists():
        assets = wd / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(404, "接口不存在")
            # HTML 一律不缓存：重装/升级后浏览器必须拿到新的 index.html 与新的资源哈希，
            # 否则用户会看到旧界面（"主题切换没生效"就是这种缓存造成的错觉）。
            no_cache = {"Cache-Control": "no-store, must-revalidate"}
            target = (wd / full_path).resolve()
            if full_path and target.is_file() and str(target).startswith(str(wd.resolve())):
                headers = no_cache if target.suffix.lower() in {".html", ".m3u8"} else None
                return FileResponse(target, headers=headers)
            return FileResponse(wd / "index.html", headers=no_cache)
    else:
        @app.get("/", include_in_schema=False)
        def placeholder():
            return HTMLResponse(PLACEHOLDER.format())

    return app
