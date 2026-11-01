"""监听地址：默认要同时听 IPv4 和 IPv6。

真实事故：线上一直用 `--host 0.0.0.0`，这个值在 Linux 上只绑 IPv4，
家里宽带给的 IPv6 地址形同虚设，从公网用 IPv6 访问一律 connection refused。
反过来直接绑 `::` 又会在 bindv6only=1 的环境（容器里很常见）把 IPv4 断掉。

所以 `_bind_sockets` 显式准备两个 socket：IPv4 绑 0.0.0.0、IPv6 绑 :: 并强制
IPV6_V6ONLY=1。用例盯住三件事：通配地址确实两个都拿到、指定具体地址时交回
uvicorn 单绑、机器没开 IPv6 时不能拖垮 IPv4。
"""
from __future__ import annotations

import socket

import pytest

from videosorter.__main__ import _bind_sockets, _SpecificHost


def _free_port() -> int:
    """要一个当前空闲的端口：绑一下再放开，交给被测代码去绑。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _has_ipv6() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


IPV6_OK = _has_ipv6()


@pytest.mark.skipif(not IPV6_OK, reason="这台机器没有可用的 IPv6 回环，测不了双栈")
def test_wildcard_host_binds_both_families() -> None:
    """0.0.0.0 / :: / 空 都表示「全网卡」，必须 IPv4 + IPv6 各一个 socket。"""
    for host in ("0.0.0.0", "::", ""):
        socks = _bind_sockets(host, _free_port())
        try:
            families = {s.family for s in socks}
            assert socket.AF_INET in families, f"{host!r} 没绑 IPv4"
            assert socket.AF_INET6 in families, f"{host!r} 没绑 IPv6"
        finally:
            for s in socks:
                s.close()


@pytest.mark.skipif(not IPV6_OK, reason="这台机器没有可用的 IPv6 回环，测不了双栈")
def test_ipv6_socket_is_v6only() -> None:
    """IPv6 那个 socket 必须设 IPV6_V6ONLY=1，否则会和 IPv4 socket 抢同一端口。"""
    socks = _bind_sockets("0.0.0.0", _free_port())
    try:
        v6 = [s for s in socks if s.family == socket.AF_INET6]
        assert len(v6) == 1
        assert v6[0].getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 1
    finally:
        for s in socks:
            s.close()


def test_specific_host_is_handed_back() -> None:
    """指定了具体地址（127.0.0.1 之类）不该被改造成双栈，交回 uvicorn 单绑。"""
    for host in ("127.0.0.1", "192.168.1.10", "::1"):
        with pytest.raises(_SpecificHost) as ei:
            _bind_sockets(host, _free_port())
        assert ei.value.host == host


def test_ipv4_still_binds_when_ipv6_unavailable(monkeypatch) -> None:
    """机器没开 IPv6 时只绑 IPv4 就够，不能因为 IPv6 失败把服务拖垮。"""
    real_socket = socket.socket

    def fake_socket(family=socket.AF_INET, *args, **kwargs):
        if family == socket.AF_INET6:
            raise OSError(97, "Address family not supported by protocol")
        return real_socket(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", fake_socket)
    socks = _bind_sockets("0.0.0.0", _free_port())
    try:
        assert [s.family for s in socks] == [socket.AF_INET]
    finally:
        for s in socks:
            s.close()


def test_real_listener_accepts_ipv4() -> None:
    """真起一个监听，确认 IPv4 能连上（不只是 bind 成功）。"""
    port = _free_port()
    socks = _bind_sockets("0.0.0.0", port)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            pass
    finally:
        for s in socks:
            s.close()
