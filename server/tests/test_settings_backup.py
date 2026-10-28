"""备份 / 导入设置的接口测试。"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT = {"username": "admin", "password": "admin1234", "remember": True}


def login(c):
    r = c.post("/api/auth/login", json=DEFAULT)
    assert r.status_code == 200, r.text


def test_export_settings_payload(env):
    c = env["client"]
    login(c)
    c.put("/api/settings", json={"root_dir": "/volume1/videos", "thumb_position": 1.5})
    r = c.get("/api/settings/export")
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-type"].startswith("application/json")
    data = json.loads(r.text)
    assert data["app"] == "videosorter"
    assert data["format"] == "videosorter-settings"
    assert data["format_version"] == 1
    assert data["settings"]["root_dir"] == "/volume1/videos"
    assert data["settings"]["thumb_position"] == 1.5
    # 端口/监听地址只放在 server 段做参考
    assert "port" in data["server"] and "port" not in data["settings"]
    # 上传目录是内置源，不该出现在 sources 里
    assert all(s["kind"] != "upload" for s in data["sources"])
    names = [t["name"] for t in data["tags"]]
    assert "旅行" in names and "美食" in names


def test_import_merges_without_deleting(env):
    c = env["client"]
    login(c)
    payload = {
        "format": "videosorter-settings",
        "format_version": 1,
        "settings": {
            "root_dir": "/volume1/videos/整理",
            "thumb_position": 3,
            "transcode": False,
            "theme": "dark",
        },
        "sources": [
            {"path": "/volume1/videos/新加的目录", "enabled": 1},
            {"path": "/volume1/videos/新加的目录", "enabled": 1},  # 重复的应当只加一次
        ],
        "tags": [
            {"name": "旅行", "color": "#123456", "dir_path": "/volume1/videos/旅行"},
            {"name": "宠物", "color": "#abcdef", "dir_path": "/volume1/videos/宠物", "sort_order": 9},
        ],
    }
    r = c.post("/api/settings/import", json=payload)
    assert r.status_code == 200, r.text
    applied = r.json()["applied"]
    assert applied["sources_added"] == 1
    assert applied["tags_added"] == 1
    assert applied["tags_updated"] == 1
    assert set(applied["settings"]) >= {"root_dir", "thumb_position", "transcode", "theme"}

    settings = c.get("/api/settings").json()["settings"]
    assert settings["root_dir"] == "/volume1/videos/整理"
    assert settings["transcode"] is False
    assert settings["theme"] == "dark"

    tags = {t["name"]: t for t in c.get("/api/tags").json()["tags"]}
    assert tags["旅行"]["color"] == "#123456"
    assert tags["旅行"]["dir_path"] == "/volume1/videos/旅行"
    assert tags["宠物"]["dir_path"] == "/volume1/videos/宠物"

    paths = [s["path"] for s in c.get("/api/sources").json()["sources"]]
    assert "/volume1/videos/新加的目录" in paths
    # 再导一次：两条同路径的源目录都算「已存在」跳过、两个标签都只更新不新增
    r2 = c.post("/api/settings/import", json=payload)
    assert r2.status_code == 200
    again = r2.json()["applied"]
    assert again["sources_added"] == 0 and again["sources_skipped"] == 2
    assert again["tags_added"] == 0 and again["tags_updated"] == 2


def test_import_rejects_foreign_file(env):
    c = env["client"]
    login(c)
    r = c.post("/api/settings/import", json={"format": "something-else"})
    assert r.status_code == 400
    assert "视频整理" in r.json()["detail"]


def test_import_rejects_newer_format(env):
    c = env["client"]
    login(c)
    r = c.post("/api/settings/import", json={"format": "videosorter-settings", "format_version": 999})
    assert r.status_code == 400
    assert "升级" in r.json()["detail"]


def test_import_ignores_bad_values(env):
    c = env["client"]
    login(c)
    r = c.post(
        "/api/settings/import",
        json={
            "format": "videosorter-settings",
            "format_version": 1,
            "settings": {"theme": "紫色", "discovery_port": 999999, "port": 9999, "unknown_key": 1},
        },
    )
    assert r.status_code == 200, r.text
    applied = r.json()["applied"]
    assert applied["settings"] == []  # 主题非法、端口越界、port 不在白名单、未知键都丢弃
    settings = c.get("/api/settings").json()["settings"]
    assert settings["port"] == 8080


def test_export_requires_auth(env):
    assert env["client"].get("/api/settings/export").status_code == 401


def test_fs_roots_lists_dirs(env):
    c = env["client"]
    login(c)
    r = c.get("/api/fs/roots")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roots"], "至少应当有主目录"
    home = str(Path.home())
    assert any(x["path"] == home for x in body["roots"])
    assert body["home"] == home
