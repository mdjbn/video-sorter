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


def test_can_direct_play_for_app_client() -> None:
    """手机 App（ExoPlayer）能直解 MKV/HEVC/AC3，这些不该再白白转码。"""
    assert can_direct_play(".mkv", "h264", "aac", "app")
    assert can_direct_play(".mp4", "hevc", "aac", "app")
    assert can_direct_play(".mkv", "hevc", "ac3", "app")
    assert can_direct_play(".ts", "h264", "eac3", "app")
    # 浏览器判断不受影响
    assert not can_direct_play(".mkv", "h264", "aac")
    # 谁都不认识的容器仍然要转码
    assert not can_direct_play(".avi", "h264", "aac", "app")
    assert not can_direct_play(".mp4", "mpeg4", "aac", "app")


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


def test_kill_proc_terminates_a_live_child() -> None:
    """_kill_proc 必须真的把子进程收掉（以前只 terminate 不 wait，会留孤儿）。"""
    import subprocess
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        HlsJob._kill_proc(proc)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:  # pragma: no cover - 兜底，别把测试进程漏在机器上
            proc.kill()
            proc.wait(timeout=5)


def test_kill_proc_escalates_to_sigkill() -> None:
    """收到 SIGTERM 不退出时，_kill_proc 要补一刀 SIGKILL，不能卡住或放它跑。"""
    import subprocess
    import sys

    # 忽略 SIGTERM 的子进程：只有 SIGKILL 能收掉
    code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        HlsJob._kill_proc(proc)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:  # pragma: no cover
            proc.kill()
            proc.wait(timeout=5)


def test_stop_all_kills_running_jobs(tmp_path: Path) -> None:
    """服务退出时 stop_all 要把所有任务的 ffmpeg 收掉，否则应用停用后它们继续占 CPU。"""
    import subprocess
    import sys

    from videosorter.media import HlsManager

    tools, cfg = _tools(tmp_path)
    manager = HlsManager(tools, cfg)
    procs = []
    for vid in (1, 2):
        job = HlsJob(tools, cfg, vid, tmp_path / f"{vid}.mp4", 10.0, "hevc", "aac")
        job.status = "running"
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        job.proc = proc
        procs.append(proc)
        manager.jobs[(vid, 0)] = job
    try:
        manager.stop_all()
        for proc in procs:
            assert proc.poll() is not None, "stop_all 之后子进程仍在跑"
        assert manager.jobs == {}
    finally:
        for proc in procs:  # pragma: no cover - 兜底
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_encoder_failure_is_not_cached(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """探测失败不写缓存：否则一次开机早期的偶发失败会让整个进程寿命都用 CPU。

    实测现象：有 Intel 核显的机器上设置页一直显示「CPU（libx264）」，
    只有在设置里切一次编码器（会 reset_encoder_cache）才恢复。
    """
    from videosorter import media as media_mod

    media_mod.reset_encoder_cache()
    calls: list[str] = []

    def fake_detect(choice: str, ffmpeg: str | None) -> str:
        calls.append(choice)
        # 第一次探测失败（模拟驱动还没就绪），第二次开始成功
        return "h264_qsv" if len(calls) > 1 else "libx264"

    monkeypatch.setattr(media_mod, "_detect_encoder", fake_detect)
    cfg = Config(str(tmp_path / "data"))
    cfg.values["transcode_encoder"] = "auto"

    assert media_mod.pick_encoder(cfg, "/usr/bin/ffmpeg").name == "libx264"
    # 关键：失败结果不该被缓存，所以这里会重新探测并拿到核显
    assert media_mod.pick_encoder(cfg, "/usr/bin/ffmpeg").name == "h264_qsv"
    assert len(calls) == 2
    # 成功结果要缓存，第三次不再探测
    assert media_mod.pick_encoder(cfg, "/usr/bin/ffmpeg").name == "h264_qsv"
    assert len(calls) == 2
    media_mod.reset_encoder_cache()


def test_s0_killed_when_not_ready(tmp_path: Path) -> None:
    """拖动换起点时：还没吐出分片的 s0 应该被收掉（否则白烧一个 ffmpeg）。"""
    import subprocess
    import sys

    from videosorter.media import HlsManager

    tools, cfg = _tools(tmp_path)
    manager = HlsManager(tools, cfg)
    s0 = HlsJob(tools, cfg, 7, tmp_path / "7.mp4", 100.0, "hevc", "aac", start=0.0)
    s0.status = "running"
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    s0.proc = proc
    manager.jobs[(7, 0)] = s0
    try:
        manager.job_for(7, tmp_path / "7.mp4", 100.0, "hevc", "aac", start=30.0)
        assert s0.cancel.is_set(), "没 ready 的 s0 应该被取消"
        proc.wait(timeout=5)
        assert proc.poll() is not None, "s0 的 ffmpeg 应该被杀掉"
    finally:
        if proc.poll() is None:
            proc.kill()


def test_s0_kept_when_playing(tmp_path: Path) -> None:
    """s0 已经出过分片时不能杀：正片可能还在播它，掐了直接黑屏。"""
    from videosorter.media import HlsManager

    tools, cfg = _tools(tmp_path)
    manager = HlsManager(tools, cfg)
    s0 = HlsJob(tools, cfg, 8, tmp_path / "8.mp4", 100.0, "hevc", "aac", start=0.0)
    s0.status = "running"
    s0.dir.mkdir(parents=True, exist_ok=True)
    s0.playlist.write_text("#EXTM3U\n", encoding="utf-8")   # 变成 ready
    manager.jobs[(8, 0)] = s0
    manager.job_for(8, tmp_path / "8.mp4", 100.0, "hevc", "aac", start=30.0)
    assert not s0.cancel.is_set(), "ready 的 s0 不能被取消"


def test_job_limit_evicts_oldest_video(tmp_path: Path) -> None:
    """并发上限：超过 transcode_jobs 时挤掉「最久没人请求」的另一个视频那一路。"""
    import time as _time

    from videosorter.media import HlsManager

    tools, cfg = _tools(tmp_path)
    cfg.update({"transcode_jobs": 2})
    manager = HlsManager(tools, cfg)
    for vid in (1, 2):
        job = HlsJob(tools, cfg, vid, tmp_path / f"{vid}.mp4", 100.0, "hevc", "aac")
        job.status = "running"
        job.touched = _time.time() - (100 if vid == 1 else 50)
        manager.jobs[(vid, 0)] = job
    newest = HlsJob(tools, cfg, 3, tmp_path / "3.mp4", 100.0, "hevc", "aac")
    # 直接把 keep 任务塞进表里，模拟第 3 路要起
    manager.jobs[(3, 0)] = newest
    newest.status = "running"
    manager._claim_slot(newest)
    assert manager.jobs.get((1, 0)) is None, "最旧的视频 1 应被挤掉"
    assert manager.jobs.get((2, 0)) is not None, "较新的视频 2 应保留"
    assert manager.jobs.get((3, 0)) is newest


def test_job_limit_zero_means_unlimited(tmp_path: Path) -> None:
    """transcode_jobs=0 表示不限并发。"""
    from videosorter.media import HlsManager

    tools, cfg = _tools(tmp_path)
    cfg.update({"transcode_jobs": 0})
    manager = HlsManager(tools, cfg)
    for vid in (1, 2, 3):
        job = HlsJob(tools, cfg, vid, tmp_path / f"{vid}.mp4", 100.0, "hevc", "aac")
        job.status = "running"
        manager.jobs[(vid, 0)] = job
    newest = HlsJob(tools, cfg, 4, tmp_path / "4.mp4", 100.0, "hevc", "aac")
    manager._claim_slot(newest)
    assert len(manager.jobs) == 3, "不限并发时不应挤掉任何任务"


def test_concurrent_ensure_respects_limit(tmp_path: Path) -> None:
    """并发请求不能突破上限：4 个线程同时 ensure，最多只有 transcode_jobs 个真起任务。

    这是实测踩出来的坑：先「数」再在锁外「杀」，4 个请求同时进来彼此都看到没满，
    结果同时起 4 个 ffmpeg，把磁盘 IO 打满、全部卡在 D 状态。
    """
    import threading as _th

    from videosorter.media import HlsManager

    tools, cfg = _tools(tmp_path)
    cfg.update({"transcode_jobs": 2})
    manager = HlsManager(tools, cfg)
    started: list[int] = []
    lock = _th.Lock()

    # 让 run() 只记账不真跑 ffmpeg
    def fake_run(self) -> None:  # noqa: ANN001
        with lock:
            started.append(self.video_id)

    import videosorter.media as media_mod
    orig_run = media_mod.HlsJob.run
    media_mod.HlsJob.run = fake_run
    try:
        threads = []
        for vid in range(1, 5):
            t = _th.Thread(target=lambda v=vid: manager.ensure(v, tmp_path / f"{v}.mp4", 10.0, "hevc", "aac"))
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        running = [j for j in manager.jobs.values() if j.status == "running"]
        assert len(running) <= 2, f"同时运行的任务超过上限：{len(running)}"
    finally:
        media_mod.HlsJob.run = orig_run


def test_stall_watchdog_kills_and_flags(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """久不出分片的转码要被掐掉并标记 stalled —— 有的源会让 hevc_qsv 无限重建
    MFX session（实测 20 秒片源跑 5 分钟连 2 秒都没转完），这种必须判「无法播放」。"""
    import subprocess
    import sys

    from videosorter import media as media_mod

    monkeypatch.setattr(media_mod, "FIRST_SEGMENT_TIMEOUT", 0.6)
    tools, cfg = _tools(tmp_path)
    job = HlsJob(tools, cfg, 7, tmp_path / "7.mp4", 10.0, "hevc", "aac")
    job.dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        job._watch_stall(proc)
        assert job.stalled is True
        assert proc.poll() is not None, "卡死看门狗没有杀掉 ffmpeg"
    finally:
        if proc.poll() is None:  # pragma: no cover - 兜底
            proc.kill()
            proc.wait(timeout=5)


def test_stall_watchdog_leaves_healthy_job_alone(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """已经吐出分片的转码不能被看门狗误杀（大文件转码本来就慢）。"""
    import subprocess
    import sys

    from videosorter import media as media_mod

    monkeypatch.setattr(media_mod, "FIRST_SEGMENT_TIMEOUT", 0.6)
    tools, cfg = _tools(tmp_path)
    job = HlsJob(tools, cfg, 8, tmp_path / "8.mp4", 10.0, "hevc", "aac")
    job.dir.mkdir(parents=True, exist_ok=True)
    (job.dir / "seg00000.ts").write_bytes(b"x")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        job._watch_stall(proc)
        assert job.stalled is False
        assert proc.poll() is None, "有分片在出时不该杀进程"
    finally:
        job._kill_proc(proc)
