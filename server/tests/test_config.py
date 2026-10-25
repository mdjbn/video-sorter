"""配置与环境变量覆盖（fnOS / systemd 部署用）。"""
from __future__ import annotations

import json

from videosorter.config import Config


def test_env_overrides_win_over_file(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(
        json.dumps({"port": 8080, "root_dir": "/tmp/from-file"}), encoding="utf-8"
    )
    monkeypatch.setenv("VIDEOSORTER_PORT", "18931")
    monkeypatch.setenv("VIDEOSORTER_ROOT_DIR", "/vol1/videos/整理")
    monkeypatch.setenv("VIDEOSORTER_DISCOVERY", "false")
    monkeypatch.setenv("VIDEOSORTER_UPLOAD_DIR", "/vol1/videos/手机上传")

    cfg = Config(tmp_path)
    assert cfg.get("port") == 18931
    assert cfg.get("root_dir") == "/vol1/videos/整理"
    assert cfg.get("discovery") is False
    assert cfg.get("upload_dir") == "/vol1/videos/手机上传"


def test_env_override_not_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEOSORTER_PORT", "19001")
    cfg = Config(tmp_path)
    assert cfg.get("port") == 19001
    cfg.save()
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved.get("port") == 19001  # 保存的是内存里的值；清掉 env 后重新落盘不影响既有文件


def test_blank_env_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEOSORTER_PORT", "   ")
    monkeypatch.setenv("VIDEOSORTER_ROOT_DIR", "")
    cfg = Config(tmp_path)
    assert cfg.get("port") == 8080
    assert cfg.get("root_dir") == ""
