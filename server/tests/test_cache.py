"""缓存统计与清理接口。"""
from __future__ import annotations

import time


def _login(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin1234",
                                             "remember": True})
    assert r.status_code == 200
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_cache_requires_auth(env):
    assert env["client"].get("/api/cache").status_code == 401


def test_cache_info_and_clear(env):
    client = env["client"]
    h = _login(client)
    # 先扫描出封面，保证有缓存内容
    client.post("/api/sources", json={"path": str(env["src"])}, headers=h)
    task = client.post("/api/scan", json={}, headers=h).json()["task_id"]
    for _ in range(100):
        if client.get(f"/api/tasks/{task}", headers=h).json()["status"] != "running":
            break
        time.sleep(0.1)
    info = client.get("/api/cache", headers=h).json()
    assert set(info) >= {"thumbs", "hls", "total_bytes", "data_dir"}
    assert info["thumbs"]["count"] >= 1
    assert info["thumbs"]["bytes"] > 0

    r = client.post("/api/cache/clear", json={"target": "all"}, headers=h)
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True
    assert body["freed_bytes"] > 0
    assert body["thumbs"]["count"] == 0 and body["hls"]["count"] == 0

    # 封面删掉后仍能懒生成
    vids = client.get("/api/videos", headers=h).json()["items"]
    assert vids
    assert client.get(f"/api/videos/{vids[0]['id']}/thumb", headers=h).status_code == 200
