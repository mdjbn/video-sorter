"""会话列表要能标出「当前这一条」，前端才能区分自己和别的设备。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _login(c) -> str:
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200
    return r.json()["token"]


def test_sessions_marks_current_token(env) -> None:
    c = env["client"]
    _login(c)  # 另一台设备留下的会话
    token = _login(c)
    h = {"Authorization": f"Bearer {token}"}
    sessions = c.get("/api/auth/sessions", headers=h).json()["sessions"]
    assert len(sessions) == 2
    current = [s for s in sessions if s["current"]]
    assert len(current) == 1
    # /me 里也带着同样的标记
    me = c.get("/api/auth/me", headers=h).json()
    assert sum(1 for s in me["sessions"] if s["current"]) == 1
