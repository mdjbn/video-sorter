"""视频列表的 limit 语义：limit>0 截断，limit=0 表示不限（视频库/播放列表要全量）。"""
from __future__ import annotations

import time

DEFAULT = {"username": "admin", "password": "admin1234", "remember": True}


def _login(c):
    r = c.post("/api/auth/login", json=DEFAULT)
    assert r.status_code == 200, r.text


def _wait_task(c, task_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        t = c.get(f"/api/tasks/{task_id}").json()
        if t["status"] in {"done", "error", "cancelled"}:
            return t
        time.sleep(0.1)
    raise AssertionError("任务超时")


def _scan_all(env):
    c, src = env["client"], env["src"]
    _login(c)
    assert c.post("/api/sources", json={"path": str(src)}).status_code == 200
    done = _wait_task(c, c.post("/api/scan", json={}).json()["task_id"])
    assert done["status"] == "done", done


def test_limit_zero_returns_everything(env):
    _scan_all(env)
    c = env["client"]
    total = c.get("/api/videos").json()["total"]
    assert total == 3

    capped = c.get("/api/videos?limit=1").json()
    assert len(capped["items"]) == 1
    assert capped["total"] == 3

    full = c.get("/api/videos?limit=0").json()
    assert len(full["items"]) == total
    assert {v["id"] for v in full["items"]} == {
        v["id"] for v in c.get("/api/videos?limit=0&offset=0").json()["items"]
    }


def test_limit_zero_keeps_sorting_and_filters(env):
    _scan_all(env)
    c = env["client"]
    asc = c.get("/api/videos?limit=0&sort=name&order=asc").json()["items"]
    desc = c.get("/api/videos?limit=0&sort=name&order=desc").json()["items"]
    assert [v["filename"] for v in asc] == list(reversed([v["filename"] for v in desc]))

    untagged = c.get("/api/videos?limit=0&status=untagged").json()
    assert untagged["total"] == 3
    assert len(untagged["items"]) == 3


def test_limit_accepts_negative_boundary(env):
    """limit 有下界 0：负数应被 FastAPI 挡下（422），而不是当成不限。"""
    _scan_all(env)
    r = env["client"].get("/api/videos?limit=-1")
    assert r.status_code == 422
