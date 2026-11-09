"""上传接口的路径安全：文件名不能改变落点，目录参数不能带 ".."。

背景：fnOS 应用中心上架自查第 4 条要求「有文件读写相关接口，需校验路径安全性，
避免路径穿越等问题」。这里覆盖两条入口 —— multipart 里的 filename，以及 dir 表单字段。
"""
from __future__ import annotations

from pathlib import Path

from videosorter.api.upload_routes import safe_dir, safe_upload_name


# ---------- 纯函数 ----------

def test_name_keeps_only_last_segment() -> None:
    assert safe_upload_name("../../etc/passwd.mp4") == "passwd.mp4"
    assert safe_upload_name("C:\\Users\\me\\假期.mp4") == "假期.mp4"
    assert safe_upload_name("a/b\\c.mp4") == "c.mp4"


def test_name_rejects_dot_only() -> None:
    assert safe_upload_name("..") == ""
    assert safe_upload_name(".") == ""
    assert safe_upload_name("") == ""
    assert safe_upload_name(None) == ""
    assert safe_upload_name("...") == ""


def test_name_strips_control_chars_and_leading_dots() -> None:
    assert safe_upload_name("a\x00b\x1f.mp4") == "ab.mp4"
    assert safe_upload_name(".hidden.mp4") == "hidden.mp4"
    assert safe_upload_name("  空格开头.mp4  ") == "空格开头.mp4"


def test_name_truncates_but_keeps_ext() -> None:
    name = safe_upload_name("长" * 300 + ".mp4")
    assert len(name) == 120
    assert name.endswith(".mp4")


def test_dir_requires_absolute_without_dotdot(tmp_path: Path) -> None:
    assert safe_dir(str(tmp_path)) == tmp_path
    assert safe_dir("") is None
    assert safe_dir("相对/路径") is None
    assert safe_dir("/tmp/../etc") is None
    assert safe_dir("/tmp/ok/../../etc") is None


# ---------- 走接口 ----------

def _login(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin1234",
                                             "remember": True})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _upload(client, headers, name: str, dir_: str = ""):
    return client.post(
        "/api/upload",
        files={"file": (name, b"\x00" * 2048, "video/mp4")},
        data={"dir": dir_},
        headers=headers,
    )


def test_upload_with_traversal_name_lands_in_upload_dir(env) -> None:
    """文件名带 ../.. 时文件必须仍然落在上传目录里，不能跑到父目录。"""
    c = env["client"]
    h = _login(c)
    src = Path(env["src"])
    assert c.post("/api/sources", json={"path": str(src)}, headers=h).status_code == 200
    r = _upload(c, h, "../../evil.mp4")
    assert r.status_code == 200, r.text
    got = Path(r.json()["path"])
    upload_dir = (src / "手机上传").resolve()
    assert got.resolve().parent == upload_dir, got
    assert got.name == "evil.mp4"
    assert not (src.parent / "evil.mp4").exists()


def test_upload_with_dotdot_name_falls_back_to_timestamp(env) -> None:
    """名字不可用（".."）时不能报错，改成一个安全名字入库。"""
    c = env["client"]
    h = _login(c)
    r = _upload(c, h, "..")
    assert r.status_code == 200, r.text
    name = Path(r.json()["path"]).name
    assert name.startswith("upload_")
    assert name.endswith(".mp4")


def test_upload_rejects_relative_or_dotdot_dir(env) -> None:
    c = env["client"]
    h = _login(c)
    assert _upload(c, h, "ok.mp4", dir_="../../etc").status_code == 400
    assert _upload(c, h, "ok.mp4", dir_="相对目录").status_code == 400
    # 正常绝对路径仍然可以
    target = Path(env["src"]) / "自定义上传"
    r = _upload(c, h, "ok.mp4", dir_=str(target))
    assert r.status_code == 200, r.text
    assert (target / "ok.mp4").exists()
