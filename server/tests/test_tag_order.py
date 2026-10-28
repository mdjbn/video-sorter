"""标签排序：拖拽后前端把完整 id 顺序发回来，服务端只改 sort_order。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _login(c) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _names(c, h) -> list[str]:
    return [t["name"] for t in c.get("/api/tags", headers=h).json()["tags"]]


def test_reorder_tags_keeps_given_order(env) -> None:
    c, h = env["client"], _login(env["client"])
    before = _names(c, h)
    assert len(before) >= 5  # 内置 5 个默认标签
    new_order = list(reversed(before))
    ids = {t["name"]: t["id"] for t in c.get("/api/tags", headers=h).json()["tags"]}
    r = c.put("/api/tags/order", json={"ids": [ids[n] for n in new_order]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert _names(c, h) == new_order
    # 接口顺带把排好序的完整列表回传，前端可以直接用它覆盖
    assert [t["name"] for t in r.json()["tags"]] == new_order


def test_reorder_ignores_unknown_and_duplicate_ids(env) -> None:
    c, h = env["client"], _login(env["client"])
    tags = c.get("/api/tags", headers=h).json()["tags"]
    ids = [t["id"] for t in tags]
    # 混入重复 id 和不存在的 id，剩下的顺序仍按传入顺序
    payload = {"ids": [ids[2], 9999, ids[0], ids[2], ids[1]]}
    r = c.put("/api/tags/order", json=payload, headers=h)
    assert r.status_code == 200, r.text
    got = [t["id"] for t in c.get("/api/tags", headers=h).json()["tags"]]
    assert got[:3] == [ids[2], ids[0], ids[1]]
    # 没提到的标签排在后面，一个都不少
    assert len(got) == len(ids)
    assert set(got) == set(ids)


def test_reorder_requires_login(env) -> None:
    c = env["client"]
    assert c.put("/api/tags/order", json={"ids": []}).status_code == 401
