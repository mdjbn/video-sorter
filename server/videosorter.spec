# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把后端 + 已构建的网页端打成一个可执行服务。

用法：
    pyinstaller server/videosorter.spec --noconfirm --distpath dist/sidecar
产物（onedir）：
    dist/sidecar/videosorter-server/videosorter-server(.exe)
    dist/sidecar/videosorter-server/webdist/...      # 网页端静态文件
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIST = os.path.join(ROOT, "web", "dist")

datas = []
if os.path.isdir(WEB_DIST):
    datas.append((WEB_DIST, "webdist"))
else:
    print("WARNING: web/dist 不存在，打包后的界面会显示构建提示。先执行 cd web && npm run build")

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "videosorter.api.auth_routes",
    "videosorter.api.settings_routes",
    "videosorter.api.tags_routes",
    "videosorter.api.sources_routes",
    "videosorter.api.scan_routes",
    "videosorter.api.videos_routes",
    "videosorter.api.stream_routes",
    "videosorter.api.organize_routes",
    "videosorter.api.upload_routes",
]

a = Analysis(
    [os.path.join(ROOT, "server", "run_server.py")],
    pathex=[os.path.join(ROOT, "server")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="videosorter-server",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="videosorter-server")
