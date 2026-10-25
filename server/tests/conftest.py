"""测试夹具：临时数据目录 + 临时源目录 + 真实小视频（用 ffmpeg 生成）。"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videosorter.app import create_app  # noqa: E402
from videosorter.config import Config  # noqa: E402


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def make_video(path: Path, kind: str = "mp4") -> Path:
    """kind: mp4(h264/aac 可直放) / mkv(h264/aac 需转 HLS copy) / avi(mpeg4 需转码)"""
    exe = _ffmpeg()
    if not exe:
        path.write_bytes(b"\x00" * 1024)
        return path
    args = [exe, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2"]
    if kind == "avi":
        args += ["-c:v", "mpeg4", "-c:a", "mp3"]
    else:
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    args.append(str(path))
    subprocess.run(args, check=True, capture_output=True)
    return path


@pytest.fixture()
def env(tmp_path: Path):
    data = tmp_path / "data"
    src = tmp_path / "videos"
    src.mkdir()
    make_video(src / "海边日落延时摄影.mp4", "mp4")
    make_video(src / "周末骑行.mkv", "mkv")
    make_video(src / "美食制作.avi", "avi")
    cfg = Config(data)
    app = create_app(cfg)
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        yield {"client": client, "cfg": cfg, "src": src, "data": data, "app": app}
