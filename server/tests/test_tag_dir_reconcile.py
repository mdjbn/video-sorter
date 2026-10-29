"""同名子目录不得被当成标签文件夹：标签目录改了之后，扫描要把它纠正回来。

用户场景：源目录 /test/A 下面有个子目录 B（和标签「B」想用的目录同名），
标签 B 的目标文件夹是 /test/B。如果扫描时标签的 dir_path 还是空的（默认
落到「源目录/标签名」= /test/A/B），A/B 里的视频会被误标成「已整理 + 标签 B」；
把 dir_path 改成 /test/B 之后重新扫描，这些记录必须被纠正回「没整理」。
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
            return t
        time.sleep(0.05)
    raise AssertionError("扫描超时")


def test_same_named_subfolder_is_not_tagged(env):
    client, src = env["client"], Path(env["src"])
    _login(client)
    sub = src / "旅行"          # 源目录里有个跟标签同名的子目录
    sub.mkdir(parents=True, exist_ok=True)
    make_video(sub / "同名的.mp4")

    tags = client.get("/api/tags").json()["tags"]
    travel = next(t for t in tags if t["name"] == "旅行")
    # 标签目录放在源目录之外
    out = Path(env["data"]).parent / "归档" / "旅行"
    out.mkdir(parents=True, exist_ok=True)
    make_video(out / "真整理.mp4")
    client.put(f"/api/tags/{travel['id']}", json={"dir_path": str(out)})

    client.post("/api/sources", json={"path": str(src)})
    _scan(client)

    items = {v["filename"]: v for v in client.get("/api/videos?limit=0").json()["items"]}
    assert items["同名的.mp4"]["status"] in ("idle", "tagged")
    assert items["同名的.mp4"]["tag_id"] is None
    assert items["真整理.mp4"]["status"] == "organized"
    assert items["真整理.mp4"]["tag_id"] == travel["id"]


def test_stale_organized_rows_are_reconciled(env):
    """已经误标成 organized 的源目录文件，重扫时要被纠正回没整理。"""
    client, src = env["client"], Path(env["src"])
    _login(client)
    sub = src / "旅行"
    sub.mkdir(parents=True, exist_ok=True)
    make_video(sub / "误标的.mp4")

    tags = client.get("/api/tags").json()["tags"]
    travel = next(t for t in tags if t["name"] == "旅行")
    out = Path(env["data"]).parent / "归档" / "旅行"
    out.mkdir(parents=True, exist_ok=True)
    client.put(f"/api/tags/{travel['id']}", json={"dir_path": str(out)})
    client.post("/api/sources", json={"path": str(src)})
    _scan(client)

    # 模拟历史误判：直接把它写成 organized + 标签
    vid = next(v["id"] for v in client.get("/api/videos?limit=0").json()["items"]
               if v["filename"] == "误标的.mp4")
    from videosorter.state import get_state
    get_state().db.execute("UPDATE videos SET status='organized', tag_id=?, organized_at=? WHERE id=?",
               (travel["id"], "2026-01-01T00:00:00+08:00", vid))

    _scan(client)

    v = client.get(f"/api/videos/{vid}").json()
    assert v["organized"] is False
    assert v["status"] in ("tagged", "idle")
    assert v["tag_id"] == travel["id"]      # 标签归属保留，只是不再算「已整理」
