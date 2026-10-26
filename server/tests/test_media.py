"""HLS/转码相关的纯逻辑测试：不依赖真实视频也能跑（第二项需要 ffmpeg）。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from videosorter.config import Config
from videosorter.media import MediaTools, HlsJob, can_direct_play


def _tools(tmp_path: Path) -> tuple[MediaTools, Config]:
    cfg = Config(str(tmp_path / "data"))
    return MediaTools(cfg), cfg


def test_copy_mode_matrix(tmp_path: Path) -> None:
    """只有 mp4/mkv 家族 + h264 + (aac|无音轨) 才走 -c copy；.avi/.wmv 一律转码。"""
    tools, cfg = _tools(tmp_path)
    cases = [
        ("clip.mp4", "h264", "aac", True),
        ("clip.mkv", "h264", "aac", True),
        ("clip.mp4", "h264", "", True),     # 无音轨也能 copy
        ("clip.mp4", "hevc", "aac", False),  # 编码不支持 copy
        ("clip.avi", "h264", "aac", False),  # 老容器：真机实测 copy 会失败
        ("clip.wmv", "h264", "", False),
    ]
    for name, vcodec, acodec, expected in cases:
        job = HlsJob(tools, cfg, 1, tmp_path / name, 1.0, vcodec, acodec)
        assert job.copy_mode is expected, f"{name}/{vcodec}/{acodec} 期望 copy_mode={expected}"


def test_can_direct_play() -> None:
    assert can_direct_play(".mp4", "h264", "aac")
    assert not can_direct_play(".mkv", "h264", "aac")
    assert not can_direct_play(".mp4", "hevc", "aac")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="需要 ffmpeg")
def test_hls_avi_falls_back_to_transcode(tmp_path: Path, env) -> None:  # noqa: ANN001
    """avi（老容器）即使编码是 h264 也要转码成功，不能只报错退出。"""
    tools, cfg = _tools(tmp_path)
    # conftest 的 env fixture 是 dict：{"client","cfg","src","data","app"}
    video = next(Path(env["src"]).rglob("*.avi"), None)
    assert video is not None
    job = HlsJob(tools, cfg, 1, video, 2.0, "h264", "aac")
    job.run()
    assert job.status == "done", job.error
    assert job.playlist.exists() and job.playlist.stat().st_size > 0
