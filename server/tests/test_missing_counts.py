"""磁盘上的文件被删掉后，扫描要能判定 missing，且各处计数要同步下降。

以前源目录卡片、概览总数、标签视频数都直接用 COUNT(*) 统计，
文件删了、扫描后这些数字一动不动，用户看起来就是「扫描只能扫出新增，扫不出移除」。
"""
from __future__ import annotations

import time
from pathlib import Path

from conftest import make_video


def _login(client) -> None:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin1234",
                                            "remember": True})
    assert r.status_code == 200, r.text


def _scan(client) -> dict:
    r = client.post("/api/scan", json={})
    assert r.status_code == 200, r.text
    tid = r.json()["task_id"]
    for _ in range(300):
        t = client.get(f"/api/tasks/{tid}").json()
        if t["status"] != "running":
            assert t["status"] == "done", t
            return t["result"]
        time.sleep(0.05)
    raise AssertionError("扫描超时")


def test_removed_file_drops_from_counts(env):
    client, src = env["client"], Path(env["src"])
    _login(client)
    client.post("/api/sources", json={"path": str(src)})
    _scan(client)

    before = client.get("/api/videos?limit=0").json()
    assert before["total"] == 3
    src_count = next(s for s in client.get("/api/sources").json()["sources"]
                     if s["kind"] != "upload")
    assert src_count["count"] == 3
    stats_before = client.get("/api/stats").json()
    assert stats_before["total"] == 3

    # 有一个视频被用户从磁盘上删掉了
    (src / "周末骑行.mkv").unlink()
    res = _scan(client)
    assert res["missing"] == 1

    after = client.get("/api/videos?limit=0").json()
    assert after["total"] == 2, after["total"]
    assert all(v["filename"] != "周末骑行.mkv" for v in after["items"])
    assert after["counts"]["all"] == 2
    assert after["counts"]["untagged"] == 2

    src_count = next(s for s in client.get("/api/sources").json()["sources"]
                     if s["kind"] != "upload")
    assert src_count["count"] == 2

    stats = client.get("/api/stats").json()
    assert stats["total"] == 2
    assert stats["missing"] == 1
    # 源目录与标签的视频数都不能把 missing 算进去
    assert next(s for s in stats["sources"]
                if s["kind"] != "upload")["count"] == 2
    assert sum(t["count"] for t in stats["tags"]) == 0
