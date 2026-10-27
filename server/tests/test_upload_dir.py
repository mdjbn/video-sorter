"""上传目录默认路径的回归测试：它自己也是一条源目录，不能拿自己当基准再套一层。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from videosorter.app import create_app  # noqa: E402
from videosorter.config import Config  # noqa: E402
from videosorter.state import get_state  # noqa: E402


def _start(data: Path) -> Path:
    """模拟一次服务启动（lifespan 里会登记上传目录），返回登记后的上传源路径。"""
    app = create_app(Config(data))
    with TestClient(app):
        st = get_state()
        row = st.db.query_one("SELECT path FROM sources WHERE kind='upload'")
        assert row is not None, "启动后应当登记一条 kind='upload' 的源目录"
        return Path(row["path"])


def test_upload_dir_stays_put_across_restarts(tmp_path: Path) -> None:
    data = tmp_path / "data"
    first = _start(data)
    for _ in range(3):
        assert _start(data) == first
    assert "手机上传/手机上传" not in str(first)


def test_legacy_nested_upload_source_is_collapsed(tmp_path: Path) -> None:
    data = tmp_path / "data"
    _start(data)
    legacy = data / "uploads" / "手机上传" / "手机上传" / "手机上传"
    get_state().db.execute("UPDATE sources SET path=? WHERE kind='upload'", (str(legacy),))
    expected = data / "uploads" / "手机上传"
    assert _start(data) == expected
    # 收敛之后要保持稳定，不会又被套一层
    assert _start(data) == expected


def test_upload_dir_follows_first_regular_source(tmp_path: Path) -> None:
    data = tmp_path / "data"
    src = tmp_path / "videos"
    src.mkdir()
    with TestClient(create_app(Config(data))):
        st = get_state()
        st.db.execute("DELETE FROM sources")
        st.db.execute(
            "INSERT INTO sources (path, enabled, kind, created_at) VALUES (?, 1, '', ?)",
            (str(src), "2026-01-01T00:00:00"))
    assert _start(data) == src / "手机上传"
