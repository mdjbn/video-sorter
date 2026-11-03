"""扫描结果里每个文件夹单列一行统计（前端逐目录弹提示用）。"""
from __future__ import annotations

# ---------- 每个目录的扫描结果 ----------

def test_scan_result_has_per_dir_rows(env) -> None:
    """扫描结果要带每个文件夹的统计，前端靠它弹「每个目录一条」的提示。"""
    from videosorter.media import MediaTools
    from videosorter.scanner import scan_sources
    from videosorter.state import get_state

    state = get_state()
    r = env["client"].post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert env["client"].post("/api/sources", json={"path": str(env["src"])},
                             headers=h).status_code == 200

    tid = state.tasks.create("scan")
    out = scan_sources(state.db, state.cfg, MediaTools(state.cfg), state.tasks, tid)
    assert "dirs" in out, out.keys()
    dirs = out["dirs"]
    assert dirs, "至少应该有一个目录"
    for d in dirs:
        assert set(d) == {"kind", "id", "name", "path", "found",
                          "added", "updated", "skipped", "failed"}, d
        assert d["kind"] in ("source", "tag")
        assert d["found"] >= d["added"] + d["skipped"]
    total_added = sum(d["added"] for d in dirs)
    assert total_added == out["added"], (total_added, out["added"])
