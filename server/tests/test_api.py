"""端到端接口测试：登录 → 扫描 → 打标签 → 整理 → 撤销 → 播放 → 上传。"""
from __future__ import annotations

import time
from pathlib import Path

DEFAULT = {"username": "admin", "password": "admin1234", "remember": True}


def login(c):
    r = c.post("/api/auth/login", json=DEFAULT)
    assert r.status_code == 200, r.text
    return r.json()


def wait_task(c, task_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200, r.text
        t = r.json()
        if t["status"] in {"done", "error", "cancelled"}:
            return t
        time.sleep(0.1)
    raise AssertionError("任务超时")


def test_health_public(env):
    r = env["client"].get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["app"] == "VideoSorter"


def test_requires_auth(env):
    r = env["client"].get("/api/videos")
    assert r.status_code == 401


def test_login_and_me(env):
    c = env["client"]
    me = login(c)
    assert me["user"]["username"] == "admin"
    r = c.get("/api/auth/me")
    assert r.status_code == 200
    assert c.get("/api/videos").status_code == 200


def test_wrong_password(env):
    r = env["client"].post("/api/auth/login", json={"username": "admin", "password": "bad", "remember": False})
    assert r.status_code == 401


def test_default_tags(env):
    c = env["client"]
    login(c)
    tags = c.get("/api/tags").json()["tags"]
    names = [t["name"] for t in tags]
    assert names[:5] == ["旅行", "美食", "运动", "学习", "待整理"]
    assert all("effective_dir" in t for t in tags)


def test_scan_and_list(env):
    c, src = env["client"], env["src"]
    login(c)
    r = c.post("/api/sources", json={"path": str(src)})
    assert r.status_code == 200, r.text
    task = c.post("/api/scan", json={}).json()
    done = wait_task(c, task["task_id"])
    assert done["status"] == "done", done
    assert done["result"]["added"] == 3
    listing = c.get("/api/videos").json()
    assert listing["total"] == 3
    v = listing["items"][0]
    assert v["thumb_url"] and v["duration"] > 0
    # 封面能取到
    r = c.get(v["thumb_url"])
    assert r.status_code == 200 and len(r.content) > 100
    stats = c.get("/api/stats").json()
    assert stats["total"] == 3 and stats["untagged"] == 3


def test_tag_then_organize_and_undo(env):
    c, src = env["client"], env["src"]
    login(c)
    c.post("/api/sources", json={"path": str(src)})
    wait_task(c, c.post("/api/scan", json={}).json()["task_id"])
    videos = c.get("/api/videos").json()["items"]
    tags = {t["name"]: t for t in c.get("/api/tags").json()["tags"]}
    mp4 = next(v for v in videos if v["ext"] == ".mp4")
    mkv = next(v for v in videos if v["ext"] == ".mkv")
    # 打标签
    assert c.post(f"/api/videos/{mp4['id']}/tag", json={"tag_id": tags["旅行"]["id"]}).status_code == 200
    assert c.post(f"/api/videos/{mkv['id']}/tag", json={"tag_id": tags["美食"]["id"]}).status_code == 200
    preview = c.post("/api/organize/preview", json={}).json()
    assert preview["total"] == 2
    targets = {Path(i["to"]).name for i in preview["items"]}
    assert "海边日落延时摄影.mp4" in targets
    # 执行
    task = c.post("/api/organize/execute", json={}).json()
    done = wait_task(c, task["task_id"])
    assert done["status"] == "done", done
    assert done["result"]["moved"] == 2
    for item in done["result"]["items"]:
        assert Path(item["to"]).exists(), item
        assert not Path(item["from"]).exists(), item
    # 已整理状态
    after = c.get("/api/videos").json()["items"]
    assert sum(1 for v in after if v["organized"]) == 2
    # 撤销
    batch = done["result"]["batch_id"]
    r = c.post(f"/api/organize/undo/{batch}")
    assert r.status_code == 200 and r.json()["restored"] == 2
    back = c.get("/api/videos").json()["items"]
    assert all(Path(v["path"]).exists() for v in back)
    assert sum(1 for v in back if v["organized"]) == 0
    assert c.post(f"/api/organize/undo/{batch}").status_code == 400


def test_organize_conflict_renames(env):
    c, src = env["client"], env["src"]
    login(c)
    c.post("/api/sources", json={"path": str(src)})
    wait_task(c, c.post("/api/scan", json={}).json()["task_id"])
    tags = {t["name"]: t for t in c.get("/api/tags").json()["tags"]}
    video = next(v for v in c.get("/api/videos").json()["items"] if v["ext"] == ".mp4")
    tag = tags["旅行"]
    c.post(f"/api/videos/{video['id']}/tag", json={"tag_id": tag["id"]})
    preview = c.post("/api/organize/preview", json={}).json()
    target = Path(preview["items"][0]["to"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"existing")
    preview2 = c.post("/api/organize/preview", json={}).json()
    assert preview2["items"][0]["renamed"] is True
    assert preview2["items"][0]["to"].endswith("(1).mp4")


def test_rename_video(env):
    c, src = env["client"], env["src"]
    login(c)
    c.post("/api/sources", json={"path": str(src)})
    wait_task(c, c.post("/api/scan", json={}).json()["task_id"])
    video = next(v for v in c.get("/api/videos").json()["items"] if v["ext"] == ".mp4")
    r = c.post(f"/api/videos/{video['id']}/rename", json={"name": "改名后的视频"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert Path(out["path"]).exists()
    assert out["path"].endswith(video["ext"])
    dup = c.post(f"/api/videos/{video['id']}/rename", json={"name": out["filename"]})
    assert dup.status_code in (200, 409)


def test_play_direct_and_hls(env):
    c, src = env["client"], env["src"]
    login(c)
    c.post("/api/sources", json={"path": str(src)})
    wait_task(c, c.post("/api/scan", json={}).json()["task_id"])
    videos = c.get("/api/videos").json()["items"]
    mp4 = next(v for v in videos if v["ext"] == ".mp4")
    mkv = next(v for v in videos if v["ext"] == ".mkv")
    p = c.get(f"/api/videos/{mp4['id']}/play").json()
    assert p["mode"] == "direct", p
    # Range 请求
    r = c.get(f"/api/videos/{mp4['id']}/raw", headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206
    assert len(r.content) == 1024
    assert r.headers["content-range"].startswith("bytes 0-1023/")
    full = c.get(f"/api/videos/{mp4['id']}/raw")
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"
    # mkv → HLS（copy 模式，秒级）
    p = c.get(f"/api/videos/{mkv['id']}/play").json()
    assert p["mode"] == "hls", p
    playlist = c.get(f"/api/videos/{mkv['id']}/hls/index.m3u8")
    assert playlist.status_code == 200, playlist.text
    assert b"#EXTM3U" in playlist.content
    seg = c.get(f"/api/videos/{mkv['id']}/hls/seg00000.ts")
    assert seg.status_code == 200 and len(seg.content) > 1000


def test_history(env):
    c, src = env["client"], env["src"]
    login(c)
    c.post("/api/sources", json={"path": str(src)})
    wait_task(c, c.post("/api/scan", json={}).json()["task_id"])
    video = c.get("/api/videos").json()["items"][0]
    assert c.post(f"/api/videos/{video['id']}/history", json={"position": 12.5, "duration": 30}).status_code == 200
    hist = c.get("/api/history").json()["items"]
    assert len(hist) == 1 and abs(hist[0]["position"] - 12.5) < 0.01
    assert c.delete(f"/api/history/{video['id']}").status_code == 200
    assert c.get("/api/history").json()["items"] == []


def test_upload(env):
    c, src = env["client"], env["src"]
    login(c)
    payload = (env["src"] / "海边日落延时摄影.mp4").read_bytes()
    r = c.post("/api/upload", files={"file": ("上传测试.mp4", payload, "video/mp4")},
               data={"dir": str(env["src"] / "手机上传")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert Path(out["path"]).exists()
    assert out["video"]["filename"] == "上传测试.mp4"
    # 同名再传会加序号
    r2 = c.post("/api/upload", files={"file": ("上传测试.mp4", payload, "video/mp4")},
                data={"dir": str(env["src"] / "手机上传")})
    assert r2.status_code == 200
    assert "上传测试 (1).mp4" in r2.json()["path"]


def test_delete_video(env):
    c, src = env["client"], env["src"]
    login(c)
    c.post("/api/sources", json={"path": str(src)})
    wait_task(c, c.post("/api/scan", json={}).json()["task_id"])
    video = c.get("/api/videos").json()["items"][0]
    path = Path(video["path"])
    r = c.delete(f"/api/videos/{video['id']}?file=true")
    assert r.status_code == 200 and r.json()["file_removed"] is True
    assert not path.exists()
    assert c.get(f"/api/videos/{video['id']}").status_code == 404


def test_settings_and_info(env):
    c = env["client"]
    login(c)
    info = c.get("/api/info").json()
    assert info["media_ready"] is True
    r = c.put("/api/settings", json={"root_dir": "/tmp/vs-root-test", "thumb_position": 0.2})
    assert r.status_code == 200
    assert c.get("/api/settings").json()["settings"]["root_dir"] == "/tmp/vs-root-test"


def test_change_password(env):
    c = env["client"]
    login(c)
    bad = c.post("/api/auth/password", json={"old_password": "wrong", "new_password": "newpass123"})
    assert bad.status_code in (400, 401)
    ok = c.post("/api/auth/password", json={"old_password": "admin1234", "new_password": "newpass123"})
    assert ok.status_code == 200, ok.text
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"username": "admin", "password": "newpass123"}).status_code == 200
