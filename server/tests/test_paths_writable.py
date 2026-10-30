"""扫描/整理前的目录可写性预检（线上踩坑：服务用户对源目录不可写，整理时才 Permission denied，前端还静默）。

当前测试以非 root 用户运行（uid 825），chmod 0o555 之后 os.access(W_OK) 会返回 False，可以真实地测。

两条容易踩的语义，测试里都按真实行为断言：
  · 「源目录」必须事先存在，不存在就是真问题 → 报「目录不存在」；
  · 「标签目录」是整理时才 mkdir 出来的（默认「源目录/标签名」），还没整理过时它本来就不存在，
    这时看最近的已存在祖先目录能不能写：能写 = 可写，不报（否则界面上满屏误报）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

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


def _state():
    from videosorter.state import get_state
    return get_state()


def _add_source(env, h, path=None):
    """通过接口加一个源目录（会顺带创建「手机上传」子目录）。"""
    p = str(path or env["src"])
    assert env["client"].post("/api/sources", json={"path": p}, headers=h).status_code == 200
    return p


def _prepare(env, h, count: int = 3):
    """加源 → 扫描 → 给前 count 个视频打「旅行」标签；返回 (tag, videos, tag_dir)。

    tag_dir 走接口算出来的默认目标目录（源目录/旅行），此时它还不存在。
    """
    c = env["client"]
    _add_source(env, h)
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    assert _wait_task(c, h, tid)["status"] == "done"
    tag = next(t for t in c.get("/api/tags", headers=h).json()["tags"] if t["name"] == "旅行")
    videos = c.get("/api/videos", headers=h).json()["items"]
    assert videos, "扫描应当扫到 conftest 生成的视频"
    for v in videos[:count]:
        assert c.post(f"/api/videos/{v['id']}/tag", json={"tag_id": tag["id"]}, headers=h).status_code == 200
    return tag, c.get("/api/videos", headers=h).json()["items"], Path(env["src"]) / "旅行"


def _ro_subdir(base: Path) -> Path:
    """在 base 下建一个 0o555 的子目录，用完恢复 0o755 好让 tmp_path 能清理。"""
    d = base / "readonly"
    d.mkdir()
    os.chmod(d, 0o555)
    return d


# ---------- check_roots_writable 本身 ----------

def test_readonly_source_dir_is_reported(env, tmp_path) -> None:
    """源目录本身不可写 → 报出来（kind=source，说明原因）。"""
    st = _state()
    ro = _ro_subdir(tmp_path)
    try:
        from videosorter.db import now_iso
        st.db.execute("INSERT INTO sources (path, enabled, kind, created_at) VALUES (?,1,'',?)",
                      (str(ro), now_iso()))
        bad = organizer.check_roots_writable(st.db, st.cfg)
        paths = [b["path"] for b in bad]
        assert str(ro) in paths, bad
        hit = next(b for b in bad if b["path"] == str(ro))
        assert hit["kind"] == "source"
        assert hit["reason"], "要说明为什么不可写"
        assert set(hit) == {"path", "kind", "reason"}
    finally:
        os.chmod(ro, 0o755)


def test_writable_dirs_are_not_reported(env) -> None:
    """可写的源目录 + 还没建出来的标签目录（父目录可写）都不该报。"""
    c, h = env["client"], _login(env["client"])
    st = _state()
    tag, _videos, tag_dir = _prepare(env, h, count=1)
    assert not tag_dir.exists(), "默认标签目录这时还没建"
    assert organizer.check_roots_writable(st.db, st.cfg) == []


def test_missing_source_dir_is_reported(env, tmp_path) -> None:
    """源目录指向一个不存在的路径 → 报「目录不存在」（源目录必须事先存在）。"""
    st = _state()
    ghost = tmp_path / "不存在的源目录"
    from videosorter.db import now_iso
    st.db.execute("INSERT INTO sources (path, enabled, kind, created_at) VALUES (?,1,'',?)",
                  (str(ghost), now_iso()))
    bad = {b["path"]: b for b in organizer.check_roots_writable(st.db, st.cfg)}
    assert str(ghost) in bad, bad
    assert bad[str(ghost)]["kind"] == "source"
    assert "不存在" in bad[str(ghost)]["reason"]
    assert not ghost.exists(), "预检不能在用户目录里创建任何东西"


def test_missing_tag_dir_under_unwritable_parent_is_reported(env, tmp_path) -> None:
    """标签目录还没建、但它的父目录不可写 → 报出来（整理时一定 mkdir 不出来）。"""
    c, h = env["client"], _login(env["client"])
    st = _state()
    _add_source(env, h)
    ro = _ro_subdir(tmp_path)
    ghost = ro / "旅行"
    try:
        tag = next(t for t in c.get("/api/tags", headers=h).json()["tags"] if t["name"] == "旅行")
        assert c.put(f"/api/tags/{tag['id']}", json={"dir_path": str(ghost)}, headers=h).status_code == 200
        bad = {b["path"]: b for b in organizer.check_roots_writable(st.db, st.cfg)}
        assert str(ghost) in bad, bad
        assert bad[str(ghost)]["kind"] == "tag"
        assert "写权限" in bad[str(ghost)]["reason"]
        assert not ghost.exists(), "预检不能建目录"
    finally:
        os.chmod(ro, 0o755)


def test_duplicate_paths_are_reported_once(env, tmp_path) -> None:
    """同一个目录既是源目录又是两个标签的目标目录时只报一次，且输出按路径排序。"""
    c, h = env["client"], _login(env["client"])
    st = _state()
    shared = _ro_subdir(tmp_path)
    try:
        _add_source(env, h, shared)
        tags = c.get("/api/tags", headers=h).json()["tags"][:2]
        for t in tags:  # 一个带尾部分隔符，验证归一化
            assert c.put(f"/api/tags/{t['id']}", json={"dir_path": str(shared) + os.sep},
                         headers=h).status_code == 200
        bad = organizer.check_roots_writable(st.db, st.cfg)
        hits = [b for b in bad if b["path"] == str(shared)]
        assert len(hits) == 1, bad
        assert hits[0]["kind"] == "source", "同一路径既是源又是标签时按源判定"
        assert [b["path"] for b in bad] == sorted(b["path"] for b in bad), "输出要按路径排序才稳定"
    finally:
        os.chmod(shared, 0o755)


def test_no_probe_files_created(env, tmp_path) -> None:
    """预检任何东西都不能往用户目录里写（不能靠建探针文件来判断）。"""
    c, h = env["client"], _login(env["client"])
    st = _state()
    _add_source(env, h)
    tag = next(t for t in c.get("/api/tags", headers=h).json()["tags"] if t["name"] == "旅行")
    c.put(f"/api/tags/{tag['id']}", json={"dir_path": str(tmp_path / "还没建的" / "旅行")}, headers=h)
    before = sorted(p.name for p in tmp_path.rglob("*"))
    organizer.check_roots_writable(st.db, st.cfg)
    after = sorted(p.name for p in tmp_path.rglob("*"))
    assert before == after


# ---------- /api/scan：不可写不拦扫描，但结果里带上 ----------

def test_scan_still_runs_and_reports_unwritable(env, tmp_path) -> None:
    c, h = env["client"], _login(env["client"])
    ro = _ro_subdir(tmp_path)
    try:
        _add_source(env, h)                      # 正常源目录：3 个视频照常扫到
        _add_source(env, h, ro)                  # 不可写源目录：只是提示，不拦
        r = c.post("/api/scan", json={}, headers=h).json()
        assert any(u["path"] == str(ro) for u in r["unwritable"]), r
        body = _wait_task(c, h, r["task_id"])
        assert body["status"] == "done", body
        assert body["result"]["added"] == 3
        assert "没有写权限" in body["warning"], body["warning"]
        assert "不可写" not in body["message"], body["message"]
        assert any(u["path"] == str(ro) for u in body["result"]["unwritable"])
    finally:
        os.chmod(ro, 0o755)


def test_scan_has_no_warning_when_all_writable(env) -> None:
    c, h = env["client"], _login(env["client"])
    _add_source(env, h)
    r = c.post("/api/scan", json={}, headers=h).json()
    assert r["unwritable"] == [], r["unwritable"]
    body = _wait_task(c, h, r["task_id"])
    assert body["status"] == "done"
    assert not body.get("warning")


# ---------- /api/organize/preview：unwritable / blocked ----------

def test_preview_returns_unwritable(env, tmp_path) -> None:
    c, h = env["client"], _login(env["client"])
    tag, _videos, tag_dir = _prepare(env, h, count=1)

    # 默认目标目录（源目录/旅行）还没建出来 → 不算问题
    plan = c.post("/api/organize/preview", json={"tag_ids": [tag["id"]]}, headers=h).json()
    assert plan["unwritable"] == [], plan["unwritable"]
    assert plan["blocked"] == [] and plan["blocked_count"] == 0
    assert plan["total"] == 1

    # 把标签目标目录指到一个不可写目录：预览要提前提示，并把这些项算进 blocked
    ro = _ro_subdir(tmp_path)
    target = ro / "旅行"
    os.chmod(ro, 0o755)
    target.mkdir()
    os.chmod(target, 0o555)
    try:
        assert c.put(f"/api/tags/{tag['id']}", json={"dir_path": str(target)}, headers=h).status_code == 200
        plan = c.post("/api/organize/preview", json={"tag_ids": [tag["id"]]}, headers=h).json()
        assert any(u["path"] == str(target) for u in plan["unwritable"]), plan["unwritable"]
        assert plan["total"] == 1, "预览本身不删项，只是把 blocked 标出来"
        assert plan["blocked_count"] == 1, plan
        assert plan["blocked"][0]["path"] == str(target)
        assert plan["blocked"][0]["count"] == 1
        assert plan["blocked"][0]["reason"]
    finally:
        os.chmod(target, 0o755)
        os.chmod(ro, 0o755)


# ---------- /api/organize/execute ----------

def test_execute_400_when_every_target_is_unwritable(env, tmp_path) -> None:
    """计划里的目标目录全都不可写 → 400，文案要点明是哪个目录、让用户去改权限。"""
    c, h = env["client"], _login(env["client"])
    tag, _videos, _tag_dir = _prepare(env, h, count=1)
    ro = _ro_subdir(tmp_path)
    target = ro / "旅行"
    os.chmod(ro, 0o755)
    target.mkdir()
    os.chmod(target, 0o555)
    try:
        assert c.put(f"/api/tags/{tag['id']}", json={"dir_path": str(target)}, headers=h).status_code == 200
        r = c.post("/api/organize/execute", json={"tag_ids": [tag["id"]]}, headers=h)
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "不可写" in detail and str(target) in detail, detail
        assert "权限" in detail
    finally:
        os.chmod(target, 0o755)
        os.chmod(ro, 0o755)


def test_execute_skips_unwritable_tag_and_runs_the_rest(env, tmp_path) -> None:
    """两个标签，一个目标目录不可写：只跳过那一个，另一个照常整理，响应里带 skipped 信息。"""
    c, h = env["client"], _login(env["client"])
    _add_source(env, h)
    tid = c.post("/api/scan", json={}, headers=h).json()["task_id"]
    assert _wait_task(c, h, tid)["status"] == "done"
    tags = {t["name"]: t for t in c.get("/api/tags", headers=h).json()["tags"]}
    ok_tag, bad_tag = tags["旅行"], tags["美食"]
    items = c.get("/api/videos", headers=h).json()["items"]
    assert len(items) >= 2
    c.post(f"/api/videos/{items[0]['id']}/tag", json={"tag_id": ok_tag["id"]}, headers=h)
    c.post(f"/api/videos/{items[1]['id']}/tag", json={"tag_id": bad_tag["id"]}, headers=h)

    ro = _ro_subdir(tmp_path)
    target = ro / "美食"
    os.chmod(ro, 0o755)
    target.mkdir()
    os.chmod(target, 0o555)
    try:
        assert c.put(f"/api/tags/{bad_tag['id']}", json={"dir_path": str(target)},
                     headers=h).status_code == 200
        r = c.post("/api/organize/execute", json={}, headers=h)
        assert r.status_code == 200, r.text
        info = r.json()
        assert info["skipped"] == 1, info
        assert info["planned"] == 1, info
        assert info["skipped_reasons"][0]["path"] == str(target)
        assert info["skipped_reasons"][0]["count"] == 1
        assert info["excluded"] and info["excluded"][0]["video_id"] == items[1]["id"]

        body = _wait_task(c, h, info["task_id"])
        assert body["status"] == "done", body
        assert body["result"]["moved"] == 1
        assert body["result"]["message"] == "已整理 1 个视频"
        # 任务 extra 里也带上，前端轮询任务就能提示哪些被跳过
        assert body["skipped"] == 1
        assert body["skipped_reasons"][0]["path"] == str(target)
        assert body["skipped_video_ids"] == [items[1]["id"]]
        assert not (target / Path(items[1]["path"]).name).exists()
    finally:
        os.chmod(target, 0o755)
        os.chmod(ro, 0o755)


def test_execute_normal_path_unchanged(env) -> None:
    """可写环境（含还没建出来的默认标签目录）行为不变：skipped=0，照常搬走。"""
    c, h = env["client"], _login(env["client"])
    tag, videos, tag_dir = _prepare(env, h, count=1)
    assert not tag_dir.exists()
    r = c.post("/api/organize/execute", json={"tag_ids": [tag["id"]]}, headers=h)
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["skipped"] == 0 and info["skipped_reasons"] == [] and info["unwritable"] == []
    body = _wait_task(c, h, info["task_id"])
    assert body["status"] == "done" and body["result"]["moved"] == 1
    assert body["result"]["message"] == "已整理 1 个视频"
    assert (tag_dir / Path(videos[0]["path"]).name).exists()


# ---------- execute_plan 里不可写失败要带 hint ----------

def test_execute_plan_marks_hint_for_unwritable_target(env, tmp_path) -> None:
    """绕过路由直接跑 execute_plan：预检结果已给出、真搬时才失败，失败项要带 hint。"""
    c, h = env["client"], _login(env["client"])
    st = _state()
    tag, _videos, _tag_dir = _prepare(env, h, count=1)
    ro = _ro_subdir(tmp_path)
    target = ro / "旅行"
    os.chmod(ro, 0o755)
    target.mkdir()
    os.chmod(target, 0o555)
    try:
        assert c.put(f"/api/tags/{tag['id']}", json={"dir_path": str(target)}, headers=h).status_code == 200
        unwritable = organizer.check_roots_writable(st.db, st.cfg)
        assert any(u["path"] == str(target) for u in unwritable), unwritable
        tid = st.tasks.create("organize")
        result = organizer.execute_plan(st.db, st.cfg, st.tasks, tid, tag_ids=[tag["id"]],
                                        unwritable=unwritable)
        assert result["task_status"] == "error", result
        assert result["message"].startswith("1 个视频全部整理失败")
        failure = result["failed"][0]
        assert "hint" in failure and "不可写" in failure["hint"], failure
    finally:
        os.chmod(target, 0o755)
        os.chmod(ro, 0o755)
