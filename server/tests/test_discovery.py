"""局域网发现：服务端要能被手机 App 用 UDP 广播找到。"""
from __future__ import annotations

import json
import socket

from videosorter.discovery import DISCOVERY_PORT, PROBE


def test_discovery_replies(env):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    try:
        sock.sendto(PROBE, ("127.0.0.1", DISCOVERY_PORT))
        payload = None
        for _ in range(10):
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
                break
            obj = json.loads(data.decode("utf-8"))
            if obj.get("app") == "VideoSorter":
                payload = obj
                break
    finally:
        sock.close()

    assert payload is not None, "没有收到发现响应"
    assert payload["port"] == int(env["cfg"].get("port"))
    assert payload["version"]
    assert payload["tls"] is False
    assert "name" in payload and "ip" in payload


def test_discovery_can_be_disabled(tmp_path):
    from videosorter.config import Config
    from videosorter.discovery import DiscoveryService

    cfg = Config(tmp_path / "d")
    cfg.set("discovery", False)
    assert cfg.get("discovery") is False
    # 关闭后应用不应持有发现服务
    from fastapi.testclient import TestClient
    from videosorter.app import create_app
    from videosorter.state import get_state

    with TestClient(create_app(cfg)):
        assert get_state().discovery is None
