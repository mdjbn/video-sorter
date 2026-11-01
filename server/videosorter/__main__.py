"""命令行入口：python -m videosorter [--host 0.0.0.0] [--port 8080] [--data-dir DIR]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import socket
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


class _SpecificHost(Exception):
    """指定了具体监听地址（不是通配），交给 uvicorn 自己按地址族绑定。"""

    def __init__(self, host: str) -> None:
        super().__init__(host)
        self.host = host


def _bind_sockets(host: str, port: int) -> list[socket.socket]:
    """按 host 生成监听用的 socket 列表。

    「只绑 IPv4」是本项目踩过的坑：`--host 0.0.0.0` 下服务根本不听 IPv6，
    外网 IPv6 直连一律 connection refused。而直接绑 `::` 在某些环境（容器、
    net.ipv6.bindv6only=1）又会让 IPv4 完全断掉。

    所以这里显式准备两个 socket：IPv4 绑 0.0.0.0、IPv6 绑 :: 并强制
    IPV6_V6ONLY=1，互不抢占同一端口，两种协议各走各的。任一协议不可用时
    只跳过那一个（比如机器没开 IPv6），不影响启动。
    """
    socks: list[socket.socket] = []
    errors: list[str] = []

    # 通配地址才双栈；指定了具体地址（127.0.0.1 / 192.168.x.x / 某个 IPv6）就只绑那个
    wildcard = host in {"0.0.0.0", "::", "", None}
    want4 = wildcard
    want6 = wildcard

    if want4:
        try:
            s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s4.bind(("0.0.0.0", port))
            s4.listen(2048)
            s4.setblocking(False)
            socks.append(s4)
        except OSError as e:
            errors.append(f"IPv4: {e}")

    if want6:
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # 关键：只吃 IPv6，避免和上面的 IPv4 socket 抢同一端口
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s6.bind(("::", port))
            s6.listen(2048)
            s6.setblocking(False)
            socks.append(s6)
        except OSError as e:
            errors.append(f"IPv6: {e}")

    if not socks and not wildcard:
        # 指定了具体地址：按地址族单绑，交给调用方去绑
        raise _SpecificHost(host)

    if not socks:
        raise OSError("；".join(errors) or f"无法监听端口 {port}")
    for err in errors:
        logging.getLogger("videosorter").warning("监听失败：%s", err)
    return socks


def _serve(app, host: str, port: int, log_level: str) -> None:
    """优先双栈监听；拿不到 socket 时退回 uvicorn 自己的单协议实现。"""
    import uvicorn

    try:
        socks = _bind_sockets(host, port)
    except _SpecificHost:
        # 用户指定了具体地址，按老办法单绑，不用警告
        uvicorn.run(app, host=host, port=port, log_level=log_level, reload=False)
        return
    except OSError as e:
        logging.getLogger("videosorter").warning("双栈监听不可用（%s），退回单协议", e)
        uvicorn.run(app, host=host, port=port, log_level=log_level, reload=False)
        return

    config = uvicorn.Config(app, log_level=log_level, lifespan="on")
    server = uvicorn.Server(config)
    try:
        asyncio.run(server.serve(sockets=socks))
    finally:
        for s in socks:
            try:
                s.close()
            except OSError:
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
    print(f"  数据目录：{cfg.data_dir}")
    if host in {"0.0.0.0", "::", ""}:
        print("  监听：IPv4 0.0.0.0 与 IPv6 [::]（双栈，可用 --host 限定）")
    else:
        print(f"  监听：{host}")
    print()
    if args.open:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    _serve(app, host, port, args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
