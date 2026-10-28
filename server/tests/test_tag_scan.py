"""扫描要同时覆盖「标签文件夹」：整理过的视频即使数据库丢了也能重新入库。"""
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
    # 扫描是后台线程任务，必须给它时间（CI 机器快，紧凑轮询会在扫描结束前就把次数用完）
    for _ in range(300):
        t = client.get(f"/api/tasks/{tid}").json()
        if t["status"] != "running":
            assert t["status"] == "done", t
            return t
        time.sleep(0.05)
    raise AssertionError("扫描超时")


def test_scan_covers_tag_folders(env):
    client, src = env["client"], Path(env["src"])
    _login(client)
    # 源目录里放一个普通视频
    make_video(src / "源里的视频.mp4")
    # 标签「旅行」的目标文件夹放在源目录之外（模拟已整理的文件）
    out = Path(env["data"]).parent / "归档" / "旅行"
    out.mkdir(parents=True)
    make_video(out / "已整理1.mp4")
    make_video(out / "已整理2.mkv")

    tags = client.get("/api/tags").json()["tags"]
    travel = next(t for t in tags if t["name"] == "旅行")
    r = client.put(f"/api/tags/{travel['id']}", json={"dir_path": str(out)})
    assert r.status_code == 200, r.text

    client.post("/api/sources", json={"path": str(src)})
    _scan(client)

    data = client.get("/api/videos?limit=50").json()
    names = {v["filename"]: v for v in data["items"]}
    assert "源里的视频.mp4" in names
    assert "已整理1.mp4" in names and "已整理2.mkv" in names
    v1 = names["已整理1.mp4"]
    assert v1["status"] == "organized"
    assert v1["tag_id"] == travel["id"]
    assert names["源里的视频.mp4"]["status"] in ("idle", "tagged")
    counts = data["counts"]
    assert counts["organized"] == 2
    assert counts["source"] == 4   # 夹具自带的 3 个样片 + 新加的 1 个
    assert data["total"] == 6


def test_tag_folder_inside_source_is_classified(env):
    client, src = env["client"], Path(env["src"])
    _login(client)
    tags = client.get("/api/tags").json()["tags"]
    food = next(t for t in tags if t["name"] == "美食")
    client.post("/api/sources", json={"path": str(src)})
    inner = src / "美食"
    inner.mkdir()
    # 显式指定标签目标目录，避免依赖「第一个源目录」的默认规则
    client.put(f"/api/tags/{food['id']}", json={"dir_path": str(inner)})
    make_video(inner / "整理过的美食.mp4")
    make_video(src / "还没整理.mp4")

    _scan(client)
    names = {v["filename"]: v for v in client.get("/api/videos?limit=50").json()["items"]}
    got = names["整理过的美食.mp4"]
    assert got["status"] == "organized", names
    assert got["tag_id"] == food["id"]
    assert names["还没整理.mp4"]["status"] == "idle"


def _scan_tag(client, tag_ids: list[int]) -> dict:
    r = client.post("/api/scan", json={"tag_ids": tag_ids})
    assert r.status_code == 200, r.text
    tid = r.json()["task_id"]
    for _ in range(300):
        t = client.get(f"/api/tasks/{tid}").json()
        if t["status"] != "running":
            assert t["status"] == "done", t
            return t
        time.sleep(0.05)
    raise AssertionError("扫描超时")


def test_scan_only_given_tag_folder(env):
    """新建标签后要能只扫这个标签的文件夹：源文件夹里的视频这次不入库。"""
    client, src = env["client"], Path(env["src"])
    _login(client)
    tags = client.get("/api/tags").json()["tags"]
    travel = next(t for t in tags if t["name"] == "旅行")
    client.post("/api/sources", json={"path": str(src)})
    make_video(src / "源里的视频.mp4")

    out = Path(env["data"]).parent / "归档2" / "旅行"
    out.mkdir(parents=True)
    make_video(out / "旧归档.mp4")
    client.put(f"/api/tags/{travel['id']}", json={"dir_path": str(out)})

    _scan_tag(client, [travel["id"]])
    data = client.get("/api/videos?limit=50").json()
    names = {v["filename"]: v for v in data["items"]}
    assert "旧归档.mp4" in names, names
    assert names["旧归档.mp4"]["tag_id"] == travel["id"]
    assert "源里的视频.mp4" not in names, names


def test_scan_only_given_tag_folder_without_dir(env):
    """标签的文件夹还不存在时也不该报错崩掉，只是这次什么都没扫到。"""
    client = env["client"]
    _login(client)
    tags = client.get("/api/tags").json()["tags"]
    empty = next(t for t in tags if t["name"] == "待整理")
    client.put(f"/api/tags/{empty['id']}", json={"dir_path": ""})
    env["cfg"].update({"root_dir": str(Path(env["data"]).parent / "不存在的根" / "x")})
    t = _scan_tag(client, [empty["id"]])
    result = t.get("result") or {}
    assert result.get("added") == 0 and result.get("failed") == 0, t
