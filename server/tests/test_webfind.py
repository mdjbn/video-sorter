"""打包场景下的网页端目录探测（PyInstaller onedir / 绿色版 / 开发目录）。"""
from __future__ import annotations

import sys
from pathlib import Path

from videosorter.app import default_web_dir


def _make_dist(root: Path, name: str = "webdist") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    return d


def test_finds_webdist_next_to_executable(tmp_path, monkeypatch):
    """绿色版布局：webdist/ 就在 exe 旁边（Tauri sidecar 也用它）。"""
    exe_dir = tmp_path / "app"
    exe_dir.mkdir()
    _make_dist(exe_dir)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "videosorter-server"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert default_web_dir() == exe_dir / "webdist"


def test_finds_webdist_in_meipass(tmp_path, monkeypatch):
    """PyInstaller onedir：datas 落在 _internal/ 下，通过 _MEIPASS 找到。"""
    meipass = tmp_path / "_internal"
    meipass.mkdir()
    _make_dist(meipass)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "videosorter-server"))
    assert default_web_dir() == meipass / "webdist"


def test_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "videosorter-server"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "also-nowhere"), raising=False)
    # 开发目录可能真的存在 web/dist，此时允许命中；否则必须是 None
    found = default_web_dir()
    assert found is None or (found / "index.html").exists()
