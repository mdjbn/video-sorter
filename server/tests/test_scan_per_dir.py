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


def test_last_scan_result_is_persisted_per_dir(env) -> None:
    """扫完之后，源文件夹和标签各自的「上次扫描结果」要能通过接口读回来。"""
    from videosorter.media import MediaTools
    from videosorter.scanner import scan_sources
    from videosorter.state import get_state

    state = get_state()
    c = env["client"]
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200

    tid = state.tasks.create("scan")
    scan_sources(state.db, state.cfg, MediaTools(state.cfg), state.tasks, tid)

    srcs = c.get("/api/sources", headers=h).json()["sources"]
    real = [s for s in srcs if s["path"] == str(env["src"])]
    assert real, srcs
    ls = real[0]["last_scan"]
    assert ls is not None
    assert ls["kind"] == "source"
    assert ls["added"] == 3          # env 里造了 3 个视频
    assert ls["found"] == 3

    # 再扫一次：结果应被覆盖成「没有新增」，而不是堆成两条
    tid2 = state.tasks.create("scan")
    scan_sources(state.db, state.cfg, MediaTools(state.cfg), state.tasks, tid2)
    again = [s for s in c.get("/api/sources", headers=h).json()["sources"]
             if s["path"] == str(env["src"])][0]["last_scan"]
    assert again["added"] == 0 and again["skipped"] == 3, again


def test_tag_last_scan_result_survives_json_roundtrip(env) -> None:
    """标签的 last_scan 要能解析回来；库里存的坏 JSON 不能让接口 500。"""
    from videosorter.state import get_state

    c = env["client"]
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    tags = c.get("/api/tags", headers=h).json()["tags"]
    assert tags[0]["last_scan"] is None      # 没扫过

    st = get_state()
    st.db.execute("UPDATE tags SET last_scan_result=? WHERE id=?",
                  ('{"kind":"tag","name":"x","found":2,"added":1,'
                   '"updated":0,"skipped":1,"failed":0}', tags[0]["id"]))
    got = [t for t in c.get("/api/tags", headers=h).json()["tags"] if t["id"] == tags[0]["id"]][0]
    assert got["last_scan"]["added"] == 1 and got["last_scan"]["found"] == 2

    st.db.execute("UPDATE tags SET last_scan_result=? WHERE id=?", ("{坏掉的", tags[0]["id"]))
    got2 = [t for t in c.get("/api/tags", headers=h).json()["tags"] if t["id"] == tags[0]["id"]][0]
    assert got2["last_scan"] is None         # 坏 JSON 当没有，不报错
