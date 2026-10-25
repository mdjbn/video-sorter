"""局域网发现：让手机 App 在同一个 Wi-Fi 下自动找到服务器。

手机端向广播地址的 UDP 38080 端口发送 ``VS_DISCOVER``，
服务器回一个 JSON（名称/版本/端口），手机据此填充服务器地址。
纯标准库实现，不依赖 zeroconf。
"""
from __future__ import annotations

import json
import logging
import socket
import threading

from . import APP_NAME, __version__

log = logging.getLogger(__name__)

DISCOVERY_PORT = 38080
PROBE = b"VS_DISCOVER"


def _local_ipv4() -> str:
    """猜一个本机对外的 IPv4（UDP connect 不会真的发包）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


class DiscoveryService:
    """后台线程监听 UDP 探测包并回包；失败不影响主服务。"""

    def __init__(self, port: int, http_port: int, name: str = "") -> None:
        self.port = port
        self.http_port = http_port
        self.name = name or f"{APP_NAME} @ {socket.gethostname()}"
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("0.0.0.0", self.port))
            sock.settimeout(0.8)
        except OSError as exc:  # 端口被占/权限不足都不致命
            log.warning("局域网发现启动失败：%s", exc)
            return False
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vs-discovery", daemon=True)
        self._thread.start()
        log.info("局域网发现已启动，UDP %s", self.port)
        return True

    def _loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data.startswith(PROBE):
                continue
            payload = {
                "app": APP_NAME,
                "version": __version__,
                "name": self.name,
                "port": self.http_port,
                "ip": _local_ipv4(),
                "tls": False,
            }
            try:
                self._sock.sendto(json.dumps(payload, ensure_ascii=False).encode("utf-8"), addr)
            except OSError:
                pass

    @property
    def running(self) -> bool:
        return bool(self._sock is not None and not self._stop.is_set())

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
