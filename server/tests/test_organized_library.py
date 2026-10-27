"""整理后再扫描：已整理的视频必须留在媒体库里（不能被标记成 missing）。"""
from __future__ import annotations

import time


def _login(c):
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234", "remember": True})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _wait_task(c, h, tid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tasks/{tid}", headers=h)
        assert r.status_code == 200
        body = r.json()
        if body["status"] in ("done", "error", "cancelled"):
            return body
        time.sleep(0.15)
    raise AssertionError("任务超时")


def test_organized_video_stays_in_library_after_rescan(env):
    c = env["client"]
    h = _login(c)
    src = env["src"]

    # 1) 加源目录并扫描
    assert c.post("/api/sources", json={"path": str(src)}, headers=h).status_code == 200
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    assert _wait_task(c, h, tid)["status"] == "done"
    items = c.get("/api/videos", headers=h).json()
    assert items["total"] == 3

    # 2) 给其中两个打标签（标签目标目录设在源目录外，模拟真实整理）
    tags = c.get("/api/tags", headers=h).json()["tags"]
    tag = next(t for t in tags if t["name"] == "旅行")
    target = env["data"].parent / "organized" / "旅行"
    r = c.put(f"/api/tags/{tag['id']}", json={"dir_path": str(target)}, headers=h)
    assert r.status_code == 200
    picked = [v["id"] for v in items["items"] if v["ext"] in (".mp4", ".mkv")]
    for vid in picked:
        assert c.post(f"/api/videos/{vid}/tag", json={"tag_id": tag["id"]}, headers=h).status_code == 200

    # 3) 执行整理
    plan = c.post("/api/organize/preview", json={"tag_ids": [tag["id"]]}, headers=h).json()
    assert plan["total"] == 2
    ex = c.post("/api/organize/execute", json={"tag_ids": [tag["id"]]}, headers=h).json()
    done = _wait_task(c, h, ex["task_id"])
    assert done["status"] == "done", done
    assert len(list(target.glob("*"))) == 2

    # 4) 再次扫描源目录：整理走的视频不能消失
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    stats = _wait_task(c, h, tid)["result"]
    assert stats["missing"] == 0, stats
    body = c.get("/api/videos", headers=h).json()
    assert body["total"] == 3, body["total"]
    assert body["counts"]["organized"] == 2, body["counts"]
    assert body["counts"]["source"] == 1, body["counts"]
    ids = {v["id"]: v for v in body["items"]}
    for vid in picked:
        assert ids[vid]["status"] == "organized"
        assert ids[vid]["organized"] is True
        assert str(target) in ids[vid]["path"]
    # 媒体库默认列表里仍然能看到它们
    assert len([v for v in body["items"] if v["organized"]]) == 2
