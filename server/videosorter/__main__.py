"""命令行入口：python -m videosorter [--host 0.0.0.0] [--port 8080] [--data-dir DIR]"""
from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from pathlib import Path

from . import APP_NAME, __version__
from .app import create_app
from .config import Config


def _safe_stdio() -> None:
    """把 stdout/stderr 调成「宁可打问号也不要崩」。

    Windows 控制台欧版/美版是 cp1252，打包成 exe 后由别的进程带管道拉起时更是如此：
    这时打印「网页端：」这类中文会抛 UnicodeEncodeError，服务还没起来就挂了。
    GUI 模式（console=False）下 sys.stdout 还可能是 None，一并兜住。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "").replace("_", "")
            if enc.startswith("utf"):
                continue  # 已经是 utf-8，不用管
            stream.reconfigure(errors="replace")  # 中文编不出来就打 ?，别抛异常
        except Exception:  # noqa: BLE001  —— StringIO 之类没有 reconfigure
            pass


def main(argv: list[str] | None = None) -> int:
    _safe_stdio()
    parser = argparse.ArgumentParser(prog="videosorter", description=f"{APP_NAME} 本地视频整理服务")
    parser.add_argument("--host", default=None, help="监听地址，默认取配置（0.0.0.0）")
    parser.add_argument("--port", type=int, default=None, help="监听端口，默认 8080")
    parser.add_argument("--data-dir", default=None, help="数据目录（数据库/缩略图/转码缓存）")
    parser.add_argument("--web-dir", default=None, help="网页端构建产物目录（默认自动查找 web/dist）")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码改动自动重启")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config(args.data_dir)
    if args.host:
        cfg.set("host", args.host)
    if args.port:
        cfg.set("port", args.port)
    web_dir = Path(args.web_dir) if args.web_dir else None

    import uvicorn

    host, port = cfg.get("host") or "0.0.0.0", int(cfg.get("port") or 8080)
    app = create_app(cfg, web_dir)
    url = f"http://{'127.0.0.1' if host in {'0.0.0.0', '::'} else host}:{port}/"
    print(f"\n  {APP_NAME} {__version__}")
    print(f"  网页端：{url}")
    print(f"  数据目录：{cfg.data_dir}\n")
    if args.open:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    uvicorn.run(app, host=host, port=port, log_level=args.log_level, reload=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
