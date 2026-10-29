"""HLS 拖动进度：从中间某一秒另起一路转码（s<秒>），以及「转码标记」字段。"""
from __future__ import annotations

import time

DEFAULT = {"username": "admin", "password": "admin1234", "remember": True}


def _login(c):
    r = c.post("/api/auth/login", json=DEFAULT)
    assert r.status_code == 200, r.text


def _scan(c, path):
    r = c.post("/api/sources", json={"path": str(path)})
    assert r.status_code == 200, r.text
    r = c.post("/api/scan", json={})
    assert r.status_code == 200, r.text
    tid = r.json()["task_id"]
    for _ in range(600):
        t = c.get(f"/api/tasks/{tid}").json()
        if t["status"] in {"done", "error", "cancelled"}:
            assert t["status"] == "done", t
            return
        time.sleep(0.05)
    raise AssertionError("扫描超时")


def test_hls_seek_stream_from_middle(env):
    c, src = env["client"], env["src"]
    _login(c)
    _scan(c, src)
    videos = c.get("/api/videos?limit=0").json()["items"]
    mkv = next(v for v in videos if v["ext"] == ".mkv")

    # 第一路（从头）：s0
    r = c.get(f"/api/videos/{mkv['id']}/hls/s0/index.m3u8")
    assert r.status_code == 200, r.text
    assert b"#EXTM3U" in r.content

    # 拖动到第 1 秒：另起一路 s1，秒级就绪（-ss 输入端 seek）
    r = c.get(f"/api/videos/{mkv['id']}/hls/s1/index.m3u8")
    assert r.status_code == 200, r.text
    assert b"#EXTM3U" in r.content
    seg = c.get(f"/api/videos/{mkv['id']}/hls/s1/seg00000.ts")
    assert seg.status_code == 200 and len(seg.content) > 500, seg.status_code

    # 两路产物互不覆盖
    d = env["cfg"].hls_dir / str(mkv["id"])
    assert (d / "index.m3u8").exists()
    assert (d / "s1" / "index.m3u8").exists()

    # 状态接口带 start 也能查
    st = c.get(f"/api/videos/{mkv['id']}/hlsstatus?start=1").json()
    assert st["ready"] is True

    # 非法 part / 非法分片名
    assert c.get(f"/api/videos/{mkv['id']}/hls/x9/index.m3u8").status_code == 404
    assert c.get(f"/api/videos/{mkv['id']}/hls/s0/evil.ts").status_code == 404


def test_transcode_flag_and_reason(env):
    c, src = env["client"], env["src"]
    _login(c)
    _scan(c, src)
    items = c.get("/api/videos?limit=0").json()["items"]
    mp4 = next(v for v in items if v["ext"] == ".mp4")
    mkv = next(v for v in items if v["ext"] == ".mkv")
    avi = next(v for v in items if v["ext"] == ".avi")

    assert mp4["transcode"] is False and mp4["transcode_reason"] == ""
    assert mkv["transcode"] is True and "容器" in mkv["transcode_reason"]
    assert avi["transcode"] is True and "MPEG-4" in avi["transcode_reason"]

    # 播放历史里也带同样的标记（前端在历史卡片上显示「转码」小标）
    c.post(f"/api/videos/{mkv['id']}/history", json={"position": 1.0, "duration": 2.0})
    hist = c.get("/api/history").json()["items"]
    row = next(h for h in hist if h["id"] == mkv["id"])
    assert row["transcode"] is True and row["transcode_reason"]
