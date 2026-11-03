"""四条目录规则：源/标签目录之间不能重叠。

规则
  1. 源目录之间不能重叠（相同或互相包含）；
  2. 源目录不能位于任何标签目录内部；
  3. 标签目录不能位于任何源目录内部；
  4. 标签目录之间不能重叠。

为什么要在写入时拦：扫描范围 = 所有源目录 + 所有标签目录。两处范围一旦重叠，
同一个文件会被扫两次——并发时两边都 INSERT，撞 videos.path 的 UNIQUE 约束，
整轮扫描报 IntegrityError（实测 3 个并发全量扫描，2 个失败）。
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _login(c):
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _mkdir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _assert_400(r, hint: str) -> None:
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert hint in detail, detail


# ---------- 规则 1：源目录之间 ----------

def test_duplicate_source_rejected(env) -> None:
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    r = c.post("/api/sources", json={"path": str(env["src"])}, headers=h)
    _assert_400(r, "已经添加过")


def test_nested_source_rejected(env) -> None:
    """源目录不能嵌套：加了 /a 就不能再加 /a/b。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    inner = _mkdir(Path(env["src"]) / "子目录")
    r = c.post("/api/sources", json={"path": str(inner)}, headers=h)
    _assert_400(r, "源文件夹不能重叠")


def test_parent_of_existing_source_rejected(env) -> None:
    """反过来也不行：加了 /a/b 之后不能再加 /a。"""
    c, h = env["client"], _login(env["client"])
    inner = _mkdir(Path(env["src"]) / "子目录")
    assert c.post("/api/sources", json={"path": str(inner)}, headers=h).status_code == 200
    r = c.post("/api/sources", json={"path": str(env["src"])}, headers=h)
    _assert_400(r, "源文件夹不能重叠")


def test_sibling_sources_allowed(env, tmp_path) -> None:
    """同父目录的两个兄弟目录不算重叠，必须允许。"""
    c, h = env["client"], _login(env["client"])
    a = _mkdir(tmp_path / "磁盘" / "视频A")
    b = _mkdir(tmp_path / "磁盘" / "视频B")
    assert c.post("/api/sources", json={"path": str(a)}, headers=h).status_code == 200
    assert c.post("/api/sources", json={"path": str(b)}, headers=h).status_code == 200


# ---------- 规则 2：源目录不能落在标签目录里 ----------

def test_source_inside_tag_dir_rejected(env, tmp_path) -> None:
    c, h = env["client"], _login(env["client"])
    tags = c.get("/api/tags", headers=h).json()["tags"]
    tag_dir = _mkdir(tmp_path / "归档" / "旅行")
    assert c.put(f"/api/tags/{tags[0]['id']}", json={"dir_path": str(tag_dir)},
                 headers=h).status_code == 200
    inner = _mkdir(tag_dir / "放错地方")
    r = c.post("/api/sources", json={"path": str(inner)}, headers=h)
    _assert_400(r, "源文件夹不能放在标签目录里")


def test_source_equal_to_tag_dir_rejected(env, tmp_path) -> None:
    c, h = env["client"], _login(env["client"])
    tags = c.get("/api/tags", headers=h).json()["tags"]
    tag_dir = _mkdir(tmp_path / "归档" / "旅行")
    assert c.put(f"/api/tags/{tags[0]['id']}", json={"dir_path": str(tag_dir)},
                 headers=h).status_code == 200
    r = c.post("/api/sources", json={"path": str(tag_dir)}, headers=h)
    _assert_400(r, "源文件夹不能放在标签目录里")


# ---------- 规则 3：标签目录不能落在源目录里 ----------

def test_tag_dir_inside_source_rejected(env) -> None:
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    tags = c.get("/api/tags", headers=h).json()["tags"]
    inner = _mkdir(Path(env["src"]) / "旅行")
    r = c.put(f"/api/tags/{tags[0]['id']}", json={"dir_path": str(inner)}, headers=h)
    _assert_400(r, "标签目录不能放在源文件夹里")


def test_tag_dir_equal_to_source_rejected(env) -> None:
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    tags = c.get("/api/tags", headers=h).json()["tags"]
    r = c.put(f"/api/tags/{tags[0]['id']}", json={"dir_path": str(env["src"])}, headers=h)
    _assert_400(r, "标签目录不能放在源文件夹里")


def test_create_tag_inside_source_rejected(env) -> None:
    """新建标签时也要拦。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    inner = _mkdir(Path(env["src"]) / "新标签")
    r = c.post("/api/tags", json={"name": "新标签", "dir_path": str(inner)}, headers=h)
    _assert_400(r, "标签目录不能放在源文件夹里")


# ---------- 规则 4：标签目录之间 ----------

def test_tag_dirs_overlapping_rejected(env, tmp_path) -> None:
    c, h = env["client"], _login(env["client"])
    tags = c.get("/api/tags", headers=h).json()["tags"]
    shared = _mkdir(tmp_path / "归档" / "共用")
    assert c.put(f"/api/tags/{tags[0]['id']}", json={"dir_path": str(shared)},
                 headers=h).status_code == 200
    r = c.put(f"/api/tags/{tags[1]['id']}", json={"dir_path": str(shared)}, headers=h)
    _assert_400(r, "标签之间不能重叠")


def test_nested_tag_dirs_rejected(env, tmp_path) -> None:
    c, h = env["client"], _login(env["client"])
    tags = c.get("/api/tags", headers=h).json()["tags"]
    outer = _mkdir(tmp_path / "归档" / "外层")
    inner = _mkdir(outer / "内层")
    assert c.put(f"/api/tags/{tags[0]['id']}", json={"dir_path": str(outer)},
                 headers=h).status_code == 200
    r = c.put(f"/api/tags/{tags[1]['id']}", json={"dir_path": str(inner)}, headers=h)
    _assert_400(r, "标签之间不能重叠")


def test_sibling_tag_dirs_allowed(env, tmp_path) -> None:
    c, h = env["client"], _login(env["client"])
    tags = c.get("/api/tags", headers=h).json()["tags"]
    assert c.put(f"/api/tags/{tags[0]['id']}",
                 json={"dir_path": str(tmp_path / "归档" / "A")}, headers=h).status_code == 200
    assert c.put(f"/api/tags/{tags[1]['id']}",
                 json={"dir_path": str(tmp_path / "归档" / "B")}, headers=h).status_code == 200


# ---------- 必填 ----------

def test_tag_dir_required_on_create(env) -> None:
    c, h = env["client"], _login(env["client"])
    r = c.post("/api/tags", json={"name": "没填目录", "dir_path": ""}, headers=h)
    _assert_400(r, "请填写这个标签的目标文件夹")


def test_tag_dir_missing_field_is_422(env) -> None:
    """字段干脆不传：Pydantic 直接 422（必填）。"""
    c, h = env["client"], _login(env["client"])
    r = c.post("/api/tags", json={"name": "缺字段"}, headers=h)
    assert r.status_code == 422, r.text


def test_tag_dir_required_on_update(env) -> None:
    c, h = env["client"], _login(env["client"])
    tags = c.get("/api/tags", headers=h).json()["tags"]
    r = c.put(f"/api/tags/{tags[0]['id']}", json={"dir_path": "  "}, headers=h)
    _assert_400(r, "请填写这个标签的目标文件夹")


# ---------- 合规布局能用 ----------

def test_compliant_layout_accepted(env, tmp_path) -> None:
    """源 /videos/inbox 与标签 /videos/sorted/旅行：同父但不嵌套，属于合规布局。"""
    c, h = env["client"], _login(env["client"])
    inbox = _mkdir(tmp_path / "视频" / "inbox")
    sorted_dir = _mkdir(tmp_path / "视频" / "sorted" / "旅行")
    assert c.post("/api/sources", json={"path": str(inbox)}, headers=h).status_code == 200
    tags = c.get("/api/tags", headers=h).json()["tags"]
    r = c.put(f"/api/tags/{tags[0]['id']}", json={"dir_path": str(sorted_dir)}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["tag"]["dir_path"] == str(sorted_dir)


def test_update_source_excludes_itself(env, tmp_path) -> None:
    """改源目录路径时不能跟「自己」判重叠。

    注意：加源目录会自动长出内置上传目录（kind=upload，默认落在「源目录/手机上传」），
    而内置上传目录是允许被源目录包含的例外，所以这里把上传目录挪走，
    让本用例只考察「自己 vs 自己」这一件事。
    """
    c, h = env["client"], _login(env["client"])
    a = _mkdir(tmp_path / "A")
    r = c.post("/api/sources", json={"path": str(a)}, headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["source"]["id"]
    up = c.get("/api/sources", headers=h).json()["sources"]
    up_id = next(s["id"] for s in up if s.get("kind") == "upload")
    moved = _mkdir(tmp_path / "别处" / "手机上传")
    assert c.put(f"/api/sources/{up_id}", json={"path": str(moved)},
                 headers=h).status_code == 200
    # 保存成同一个路径（末尾带斜杠）不算冲突
    r2 = c.put(f"/api/sources/{sid}", json={"path": str(a) + "/"}, headers=h)
    assert r2.status_code == 200, r2.text


def test_update_tag_excludes_itself(env, tmp_path) -> None:
    """改标签目录时不能跟自己判重叠。"""
    c, h = env["client"], _login(env["client"])
    tags = c.get("/api/tags", headers=h).json()["tags"]
    d = _mkdir(tmp_path / "归档" / "旅行")
    assert c.put(f"/api/tags/{tags[0]['id']}", json={"dir_path": str(d)},
                 headers=h).status_code == 200
    r = c.put(f"/api/tags/{tags[0]['id']}", json={"color": "#123456"}, headers=h)
    assert r.status_code == 200, r.text
    assert Path(r.json()["tag"]["dir_path"]) == d


# ---------- 内置上传目录的例外 ----------

def test_upload_source_inside_source_allowed(env) -> None:
    """内置上传目录默认就落在「源目录/手机上传」，这是设计，不能判成冲突。"""
    c, h = env["client"], _login(env["client"])
    assert c.post("/api/sources", json={"path": str(env["src"])}, headers=h).status_code == 200
    srcs = c.get("/api/sources", headers=h).json()["sources"]
    up = [s for s in srcs if s.get("kind") == "upload"]
    assert up, srcs
    assert str(up[0]["path"]).startswith(str(env["src"])), up[0]


def test_upload_source_cannot_contain_others(env, tmp_path) -> None:
    """上传目录可以被源目录包含，但它不能反过来把别的源目录圈进去。"""
    c, h = env["client"], _login(env["client"])
    a = _mkdir(tmp_path / "A")
    assert c.post("/api/sources", json={"path": str(a)}, headers=h).status_code == 200
    srcs = c.get("/api/sources", headers=h).json()["sources"]
    up_id = next(s["id"] for s in srcs if s.get("kind") == "upload")
    # 把上传目录改到 A 的父级：这样它就包含了源目录 A
    r = c.put(f"/api/sources/{up_id}", json={"path": str(tmp_path)}, headers=h)
    assert r.status_code == 400, r.text
    # 具体是哪一条先撞上取决于 data_dir 落在哪儿（这里 tmp_path 同时包含了标签目录），
    # 只要拦住就行——两条都属于「这个位置不能当上传目录」。
    assert ("源文件夹不能重叠" in r.json()["detail"]
            or "标签目录" in r.json()["detail"]), r.json()["detail"]
