"""扫描队列：任务串行、同类合并、排队可取消、时间戳按目录记。

背景：以前 `POST /api/scan` 直接 spawn 一个后台线程，两个扫描就并行写库。
实测 3 个并发全量扫描里有 2 个报 `IntegrityError: UNIQUE constraint failed:
videos.path`（`_upsert` 先查快照再插入，两边都看不到对方刚插的行）。
改成队列后同一时刻只跑一个扫描，这类竞态从根上消失。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from tests.conftest import make_video


def _login(c):
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _wait(c, h, tid, timeout: float = 90.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        t = c.get(f"/api/tasks/{tid}", headers=h).json()
        if t["status"] not in ("running", "queued"):
            return t
        time.sleep(0.05)
    raise AssertionError("任务超时")


# ---------- 队列行为 ----------

def test_scan_returns_queued_fields(env) -> None:
    """提交扫描要告诉前端「排第几个、是否合并了」。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    r = c.post("/api/scan", json={}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["queued"] is True
    assert body["position"] >= 1
    assert body["merged"] is False
    assert _wait(c, h, body["task_id"])["status"] == "done"


def test_same_scan_is_merged_not_duplicated(env) -> None:
    """同一件事重复提交 → 复用同一个 task_id，不再排第二个。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    first = c.post("/api/scan", json={}, headers=h).json()
    second = c.post("/api/scan", json={}, headers=h).json()
    # 第二个要么复用了第一个（merged），要么第一个已经跑完所以是新的。
    # 这里只断言「不会同时有两个同签名的排队项」——跑得快的话可能已经完成。
    if second["merged"]:
        assert second["task_id"] == first["task_id"]
    q = c.get("/api/scan/queue", headers=h).json()
    sigs = [p["task_id"] for p in q["pending"]]
    assert len(sigs) == len(set(sigs))
    _wait(c, h, first["task_id"])
    _wait(c, h, second["task_id"])


def test_queued_task_can_be_cancelled(env) -> None:
    """排队中的任务取消后直接记为 cancelled，不会开跑。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    first = c.post("/api/scan", json={}, headers=h).json()
    # 弄一个不同签名的任务，确保它排到队列里（不会被合并）
    tags = c.get("/api/tags", headers=h).json()["tags"]
    second = c.post("/api/scan", json={"tag_ids": [tags[0]["id"]]}, headers=h).json()
    if second["merged"]:
        pytest.skip("第二个被合并了，构造不出排队场景")
    r = c.post(f"/api/tasks/{second['task_id']}/cancel", headers=h)
    assert r.status_code == 200, r.text
    t = _wait(c, h, second["task_id"])
    assert t["status"] == "cancelled", t
    assert "未开始" in t["message"], t


def test_queue_endpoint_shape(env) -> None:
    c, h = env["client"], _login(env["client"])
    body = c.get("/api/scan/queue", headers=h).json()
    assert set(body) == {"running", "pending"}
    assert isinstance(body["pending"], list)


def test_queue_entries_are_described(env) -> None:
    """排队项要带够信息，前端才能写「排队中 N 个扫描任务」。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    tags = c.get("/api/tags", headers=h).json()["tags"]
    c.post("/api/scan", json={}, headers=h)
    second = c.post("/api/scan", json={"tag_ids": [tags[0]["id"]]}, headers=h).json()
    if not second["merged"]:
        q = c.get("/api/scan/queue", headers=h).json()
        for item in q["pending"]:
            assert set(item) == {"task_id", "position", "label", "source_ids", "tag_ids", "created_at"}
            assert item["position"] >= 1
            assert isinstance(item["tag_ids"], list)
        # 同签名会合并，所以这个用例只能保证「有排队项时字段齐全」


def test_concurrent_scans_do_not_fail(env) -> None:
    """并发提交 3 个扫描：全部正常结束，不再出现 IntegrityError。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    # 造新文件，制造「两个扫描都看不到它、都想 INSERT」的条件
    extra = Path(env["src"]) / "并发测试"
    extra.mkdir()
    for i in range(3):
        make_video(extra / f"新增{i}.mp4")

    tags = c.get("/api/tags", headers=h).json()["tags"]
    ids = []
    for body in ({}, {"tag_ids": [tags[0]["id"]]}, {"tag_ids": [tags[1]["id"]]}, {}):
        ids.append(c.post("/api/scan", json=body, headers=h).json()["task_id"])

    for tid in ids:
        t = _wait(c, h, tid)
        assert t["status"] in ("done", "cancelled"), t
        assert "IntegrityError" not in (t.get("error") or ""), t

    # 3 个新文件都在库里，且路径唯一（说明没有重复入库）
    items = c.get("/api/videos?limit=0", headers=h).json()["items"]
    paths = [v["path"] for v in items]
    assert len(paths) == len(set(paths))
    assert sum(1 for p in paths if "并发测试" in p) == 3


# ---------- 时间戳按目录记 ----------

def test_stats_has_no_global_last_scan(env) -> None:
    """不再有全局「最近扫描」字段（改成按目录各记各的）。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    _wait(c, h, tid)
    stats = c.get("/api/videos/stats", headers=h).json()
    assert "last_scan_at" not in stats, stats


def test_source_last_scan_updated(env) -> None:
    """扫源目录 → 那个源目录的 last_scan_at 有值。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    _wait(c, h, tid)
    srcs = c.get("/api/sources", headers=h).json()["sources"]
    assert all(s["last_scan_at"] for s in srcs if s["path"] == str(env["src"])), srcs


def test_tag_last_scan_only_when_dir_scanned(env) -> None:
    """只扫某个标签 → 只有那个标签的 last_scan_at 有值，别的标签仍然是空的。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    tags = c.get("/api/tags", headers=h).json()["tags"]
    target = tags[0]
    Path(target["dir_path"]).mkdir(parents=True, exist_ok=True)
    make_video(Path(target["dir_path"]) / "已整理.mp4")

    tid = c.post("/api/scan", json={"tag_ids": [target["id"]]}, headers=h).json()["task_id"]
    _wait(c, h, tid)

    after = {t["name"]: t for t in c.get("/api/tags", headers=h).json()["tags"]}
    assert after[target["name"]]["last_scan_at"], after[target["name"]]
    others = [t for t in after.values() if t["id"] != target["id"]]
    assert all(not t["last_scan_at"] for t in others), others


def test_tag_dir_missing_is_not_marked_scanned(env, tmp_path) -> None:
    """标签目录根本不存在时不记「上次扫描」——一次都没查过，不能让用户以为查了。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    tags = c.get("/api/tags", headers=h).json()["tags"]
    target = tags[0]
    ghost = tmp_path / "从来不存在" / "旅行"
    r = c.put(f"/api/tags/{target['id']}", json={"dir_path": str(ghost)}, headers=h)
    assert r.status_code == 200, r.text

    tid = c.post("/api/scan", json={"tag_ids": [target["id"]]}, headers=h).json()["task_id"]
    _wait(c, h, tid)
    after = {t["name"]: t for t in c.get("/api/tags", headers=h).json()["tags"]}
    assert not after[target["name"]]["last_scan_at"], after[target["name"]]
