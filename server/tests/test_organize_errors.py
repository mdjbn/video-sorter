"""整理失败时的报错要能看懂：Windows 上「文件正在播放」最常见，不能把 WinError 32 直接甩给用户。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videosorter import organizer  # noqa: E402


def _login(c):
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _wait_task(c, h, tid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        body = c.get(f"/api/tasks/{tid}", headers=h).json()
        if body["status"] in ("done", "error", "cancelled"):
            return body
        time.sleep(0.15)
    raise AssertionError("任务超时")


def test_explain_error_maps_common_failures() -> None:
    assert "占用" in organizer.explain_error(PermissionError(13, "Permission denied"))
    assert "占用" in organizer.explain_error(OSError(16, "Device or resource busy"))
    assert "空间不足" in organizer.explain_error(OSError(28, "No space left on device"))
    assert organizer.explain_error(RuntimeError("目标已存在")) == "目标已存在"


def test_execute_plan_reports_friendly_busy_message(env, monkeypatch) -> None:
    c, h, src = env["client"], _login(env["client"]), env["src"]
    assert c.post("/api/sources", json={"path": str(src)}, headers=h).status_code == 200
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    assert _wait_task(c, h, tid)["status"] == "done"
    tag = next(t for t in c.get("/api/tags", headers=h).json()["tags"] if t["name"] == "旅行")
    vid = c.get("/api/videos", headers=h).json()["items"][0]["id"]
    assert c.post(f"/api/videos/{vid}/tag", json={"tag_id": tag["id"]}, headers=h).status_code == 200

    def boom(*_a, **_k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(organizer, "move_file", boom)
    r = c.post("/api/organize/execute", json={"tag_ids": [tag["id"]]}, headers=h)
    assert r.status_code == 200
    body = _wait_task(c, h, r.json()["task_id"])
    assert body["status"] == "done"
    result = body.get("result") or {}
    assert result.get("moved") == 0
    assert result.get("failed"), "应当有失败记录"
    assert "占用" in result["failed"][0]["error"]


def test_busy_file_is_retried_then_succeeds(env, monkeypatch) -> None:
    """文件被占用常常是瞬时的（播放器刚松开），重试之后应当成功而不是直接判失败。"""
    c, h, src = env["client"], _login(env["client"]), env["src"]
    assert c.post("/api/sources", json={"path": str(src)}, headers=h).status_code == 200
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    assert _wait_task(c, h, tid)["status"] == "done"
    tag = next(t for t in c.get("/api/tags", headers=h).json()["tags"] if t["name"] == "旅行")
    vid = c.get("/api/videos", headers=h).json()["items"][0]["id"]
    assert c.post(f"/api/videos/{vid}/tag", json={"tag_id": tag["id"]}, headers=h).status_code == 200

    real = organizer.move_file
    calls = {"n": 0}

    def flaky(s, d):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(13, "Permission denied")
        return real(s, d)

    monkeypatch.setattr(organizer, "move_file", flaky)
    r = c.post("/api/organize/execute", json={"tag_ids": [tag["id"]]}, headers=h)
    assert r.status_code == 200
    result = _wait_task(c, h, r.json()["task_id"]).get("result") or {}
    assert result.get("moved") == 1, result
    assert not result.get("failed")
    assert calls["n"] == 3
