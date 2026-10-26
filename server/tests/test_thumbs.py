"""缩略图必须和视频一一对应（回归：以前同一毫秒内扫描多个视频会撞名，导致封面错乱）。"""
from __future__ import annotations

import time


def _login(c):
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _scan(c, h, src):
    c.post("/api/sources", json={"path": str(src)}, headers=h)
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    for _ in range(200):
        if c.get(f"/api/tasks/{tid}", headers=h).json()["status"] != "running":
            return
        time.sleep(0.05)
    raise AssertionError("扫描超时")


def test_thumbs_match_videos(env):
    """每个视频的封面文件名都等于 <id>.jpg，URL 各不相同且能取到不同图片。"""
    c = env["client"]
    h = _login(c)
    _scan(c, h, env["src"])

    items = c.get("/api/videos?limit=100", headers=h).json()["items"]
    assert len(items) >= 3

    urls = [v["thumb_url"] for v in items]
    assert all(urls), f"有视频没有封面: {urls}"
    assert len(set(urls)) == len(urls), f"封面 URL 重复（会渲染成同一张图）: {urls}"

    blobs = {}
    for v in items:
        assert v["thumb_url"].startswith(f"/api/videos/{v['id']}/thumb?v="), v["thumb_url"]
        r = c.get(v["thumb_url"], headers=h)
        assert r.status_code == 200, v
        assert r.headers["content-type"].startswith("image/jpeg")
        blobs[v["id"]] = r.content
    # 不同视频的封面内容不应全部相同
    assert len({b for b in blobs.values()}) >= 2, "所有封面图片都一样，说明取错了文件"


def test_thumb_selfheals_legacy_name(env):
    """历史数据里 thumb 存的是时间戳名字/绝对路径时，访问后应自愈为 <id>.jpg。"""
    from videosorter.state import get_state

    c = env["client"]
    h = _login(c)
    _scan(c, h, env["src"])
    item = c.get("/api/videos?limit=1", headers=h).json()["items"][0]

    st = get_state()
    st.db.execute("UPDATE videos SET thumb=? WHERE id=?", ("legacy-name.jpg", item["id"]))
    r = c.get(f"/api/videos/{item['id']}/thumb", headers=h)
    assert r.status_code == 200
    row = st.db.query_one("SELECT thumb FROM videos WHERE id=?", (item["id"],))
    assert row["thumb"] == f"{item['id']}.jpg"
