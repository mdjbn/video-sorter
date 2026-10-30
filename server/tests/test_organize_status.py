"""整理任务的结论要传到任务状态上：全部失败 = error，部分失败 = done + 「已移动 X 个，失败 Y 个」。

网页 Player.vue 的 `if (task.status === 'error')` 靠这个才能提示用户，
数据库里的 organize_logs 之前是唯一能看到失败的地方。
"""
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


def _prepared(env, count: int = 3):
    """加源目录 → 扫描 → 给前 count 个视频打「旅行」标签（标签目录默认在源目录下）。"""
    c, h, src = env["client"], _login(env["client"]), env["src"]
    assert c.post("/api/sources", json={"path": str(src)}, headers=h).status_code == 200
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    assert _wait_task(c, h, tid)["status"] == "done"
    tag = next(t for t in c.get("/api/tags", headers=h).json()["tags"] if t["name"] == "旅行")
    vids = [v["id"] for v in c.get("/api/videos", headers=h).json()["items"]][:count]
    for vid in vids:
        assert c.post(f"/api/videos/{vid}/tag", json={"tag_id": tag["id"]}, headers=h).status_code == 200
    return c, h, src, tag, vids


# ---------- A. 全部失败 → error ----------

def test_all_failed_marks_task_error(env, monkeypatch) -> None:
    c, h, _src, tag, vids = _prepared(env)

    def boom(*_a, **_k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(organizer, "move_file", boom)
    r = c.post("/api/organize/execute", json={"tag_ids": [tag["id"]]}, headers=h)
    assert r.status_code == 200, r.text
    body = _wait_task(c, h, r.json()["task_id"])

    assert body["status"] == "error", body
    assert "全部整理失败" in body["message"], body["message"]
    assert body["message"].startswith(f"{len(vids)} 个视频全部整理失败"), body["message"]
    # 同一句文案也要在 error 字段里（前端有的地方读 error）
    assert body["error"] == body["message"]
    result = body["result"]
    assert result["moved"] == 0
    assert result["task_status"] == "error"
    assert len(result["failed"]) == len(vids)
    for item in result["failed"]:
        assert set(("video_id", "name", "error")) <= set(item)
    # 源文件一个都没动
    assert all(Path(v["path"]).exists() for v in c.get("/api/videos", headers=h).json()["items"])


def test_all_failed_missing_files_marks_task_error(env, monkeypatch) -> None:
    """文件在预览之后、真正搬的时候才消失（FileNotFoundError）同样算「全部失败」。

    注意场景要卡在 execute_plan 里失败：build_plan 阶段不存在的文件会被算进 skipped，
    根本不会进 items，那属于「没有要整理的」而不是「整理失败」。
    """
    c, h, _src, tag, vids = _prepared(env)
    real = organizer._move_with_retry

    def gone(src, dst, *a, **k):
        Path(src).unlink(missing_ok=True)  # 模拟「预览时还在，搬的时候没了」
        return real(src, dst, *a, **k)

    monkeypatch.setattr(organizer, "_move_with_retry", gone)
    r = c.post("/api/organize/execute", json={"tag_ids": [tag["id"]]}, headers=h)
    assert r.status_code == 200, r.text
    body = _wait_task(c, h, r.json()["task_id"])
    assert body["status"] == "error", body
    assert "全部整理失败" in body["message"]
    assert len(body["result"]["failed"]) == len(vids)
    assert "No such file" in body["result"]["failed"][0]["error"], body["result"]["failed"][0]


# ---------- A. 部分失败 → done ----------

def test_partial_failure_stays_done_with_summary(env, monkeypatch) -> None:
    """只有一个搬失败（其余正常）：任务仍是 done，message 说明「已移动 X 个，失败 Y 个」。

    失败发生在 _move_with_retry 里（预览之后才失效），这时它已经进了 items，
    才会被算进 failed；build_plan 阶段就消失的文件属于 skipped（见上一个用例的注释）。
    """
    c, h, src, tag, vids = _prepared(env)
    victim = next(v for v in c.get("/api/videos", headers=h).json()["items"] if v["id"] == vids[0])
    victim_path = victim["path"]
    real = organizer._move_with_retry

    def fail_one(s, d, *a, **k):
        if str(s) == victim_path:
            raise PermissionError(13, "Permission denied")
        return real(s, d, *a, **k)

    monkeypatch.setattr(organizer, "_move_with_retry", fail_one)
    r = c.post("/api/organize/execute", json={"tag_ids": [tag["id"]]}, headers=h)
    assert r.status_code == 200, r.text
    body = _wait_task(c, h, r.json()["task_id"])

    assert body["status"] == "done", body
    assert body["message"] == "已移动 2 个，失败 1 个", body["message"]
    result = body["result"]
    assert result["moved"] == 2 and len(result["failed"]) == 1
    assert result["task_status"] == "done"
    assert result["failed"][0]["video_id"] == vids[0]
    # 成功的两个确实搬到了标签目录
    target = src / "旅行"
    assert len(list(target.glob("*"))) == 2


def test_all_success_message(env) -> None:
    c, h, src, tag, vids = _prepared(env, count=2)
    r = c.post("/api/organize/execute", json={"tag_ids": [tag["id"]]}, headers=h)
    assert r.status_code == 200, r.text
    body = _wait_task(c, h, r.json()["task_id"])
    assert body["status"] == "done"
    assert body["message"] == "已整理 2 个视频", body["message"]
    assert body["result"]["moved"] == 2 and not body["result"]["failed"]


# ---------- A. 用户取消（0 移动 0 失败）→ 不是 error ----------

def test_cancelled_before_start_is_not_error(env) -> None:
    """一个都没移动也没失败（用户取消 / 计划里没有可搬的）→ 保持 done，不算失败。"""
    from videosorter.tasks import TaskRegistry

    tasks = TaskRegistry()
    tid = tasks.create("organize", total=1)
    moved, failed = [], []
    message, status = organizer.summarize_outcome(len(moved), failed)
    assert status == "done", "0 移动 0 失败不能算 error"
    tasks.finish(tid, result={"moved": 0, "failed": [], "message": message, "task_status": status},
                 message=message, status=status)
    t = tasks.get(tid)
    assert t["status"] == "done"
    assert t["error"] == ""


def test_execute_plan_cancel_deletes_empty_batch(env) -> None:
    """真跑一遍 execute_plan：开工前就取消，既不移动也不失败，批次记录要删掉、任务不是 error。"""
    from videosorter.state import get_state

    c, h, _src, tag, _vids = _prepared(env, count=1)
    st = get_state()
    tid = st.tasks.create("organize")
    st.tasks.cancel(tid)
    result = organizer.execute_plan(st.db, st.cfg, st.tasks, tid, tag_ids=[tag["id"]])
    assert result["moved"] == 0 and result["failed"] == []
    assert result["task_status"] == "done", result
    batch = st.db.query_one("SELECT id FROM organize_batches WHERE id=?", (result["batch_id"],))
    assert batch is None, "空批次应当被删掉"
    c.post(f"/api/tasks/{tid}/cancel", headers=h)  # 无副作用，只是确认接口不炸


# ---------- TaskRegistry.finish 兼容性 ----------

def test_finish_default_still_done() -> None:
    from videosorter.tasks import TaskRegistry

    tasks = TaskRegistry()
    tid = tasks.create("scan")
    tasks.finish(tid, result={"added": 1})
    t = tasks.get(tid)
    assert t["status"] == "done" and t["message"] == "完成"
    assert t["percent"] == 100.0


def test_spawn_uses_task_status_from_result() -> None:
    """spawn 的默认行为不变（done），只有 fn 明确返回 task_status=error 才标 error。"""
    from videosorter.tasks import TaskRegistry

    def wait(tasks, tid):
        end = time.time() + 10
        while time.time() < end:
            t = tasks.get(tid)
            if t["status"] != "running":
                return t
            time.sleep(0.02)
        raise AssertionError("超时")

    tasks = TaskRegistry()
    tid = tasks.spawn("organize", lambda _t: {"moved": 0, "failed": [{"error": "x"}],
                                              "message": "1 个视频全部整理失败：x",
                                              "task_status": "error"})
    t = wait(tasks, tid)
    assert t["status"] == "error" and "全部整理失败" in t["error"]

    tid2 = tasks.spawn("scan", lambda _t: {"added": 3})
    t2 = wait(tasks, tid2)
    assert t2["status"] == "done" and t2["message"] == "完成"
