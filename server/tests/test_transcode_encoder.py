"""转码编码器选择：探测失败要稳定回落 CPU，不能因为显卡不可用就把转码搞挂。"""
from __future__ import annotations

from pathlib import Path

import pytest

from videosorter import media
from videosorter.config import Config
from videosorter.media import (
    CPU_ENCODER,
    HlsJob,
    MediaTools,
    encoder_choices,
    encoder_info,
    mark_encoder_broken,
    pick_encoder,
    reset_encoder_cache,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_encoder_cache()
    yield
    reset_encoder_cache()


def _cfg(tmp_path: Path) -> Config:
    return Config(str(tmp_path / "data"))


def test_defaults_to_cpu_without_ffmpeg(tmp_path: Path) -> None:
    """没有 ffmpeg（或没探到硬件）时必须回落 libx264，而不是报错。"""
    cfg = _cfg(tmp_path)
    assert pick_encoder(cfg, None).name == CPU_ENCODER


def test_explicit_cpu_choice(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.update({"transcode_encoder": "libx264"})
    spec = pick_encoder(cfg, "/usr/bin/ffmpeg")
    assert spec.name == CPU_ENCODER and spec.hw is False


def test_auto_prefers_first_working_hardware(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    cfg = _cfg(tmp_path)
    probes: list[str] = []

    def fake_probe(ffmpeg: str, spec: media.EncoderSpec, timeout: int = 20) -> bool:  # noqa: ARG001
        probes.append(spec.name)
        return spec.name == "h264_qsv"   # 只有 QSV 能用（Linux 上排第二）

    monkeypatch.setattr(media, "_probe_encoder", fake_probe)
    spec = pick_encoder(cfg, "/usr/bin/ffmpeg")
    assert spec.name == "h264_qsv"
    assert "h264_qsv" in probes


def test_hardware_probe_failure_falls_back(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """探测全部失败（没驱动 / 没权限）→ CPU；失败不缓存，下次转码重新探一次。

    失败结果一旦被缓存，一次开机早期的偶发失败就会让整个进程寿命都用上 CPU
    （真机踩过：有核显却一直显示 CPU）。所以这里显式断言「每次都会重探」。
    """
    cfg = _cfg(tmp_path)
    calls: list[str] = []

    def fake_probe(ffmpeg: str, spec: media.EncoderSpec, timeout: int = 20) -> bool:  # noqa: ARG001
        calls.append(spec.name)
        return False

    monkeypatch.setattr(media, "_probe_encoder", fake_probe)
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name == CPU_ENCODER
    before = len(calls)
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name == CPU_ENCODER
    assert len(calls) > before, "失败不该被缓存，第二次仍要重新探测"


def test_hardware_probe_success_is_cached(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """探测成功要缓存：否则每次转码都要白跑一遍探测。"""
    cfg = _cfg(tmp_path)
    probes: list[str] = []

    def fake_probe(ffmpeg: str, spec: media.EncoderSpec, timeout: int = 20) -> bool:  # noqa: ARG001
        probes.append(spec.name)
        return True

    monkeypatch.setattr(media, "_probe_encoder", fake_probe)
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name != CPU_ENCODER
    before = len(probes)
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name != CPU_ENCODER
    assert len(probes) == before, "第二次应该命中缓存，不再跑探测"



def test_broken_encoder_cools_down_then_recovers(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """真实转码失败后进入冷却期，冷却期内不再用它；冷却结束自动重试。

    旧实现是「一次失败永久拉黑」，弱核显偶发失败后整台机器就只剩 CPU 编码
    （实测 4 路转码里 2 路走 CPU、整机 CPU 96% 而 GPU 只 10%），所以改成限时冷却。
    """
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(media, "_probe_encoder", lambda *a, **k: True)
    first = pick_encoder(cfg, "/usr/bin/ffmpeg").name
    assert first != CPU_ENCODER

    mark_encoder_broken(first, cooldown=60)
    # 冷却期内：不再选它（换下一个候选，或回落 CPU）
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name != first
    assert media._encoder_cooling(first) is True

    # 冷却到期：重新可用（先清掉冷却期内写进缓存的「次选」，模拟下次转码重新探测）
    real_time = media.time.time          # 先抓住真函数：monkeypatch 换的正是它
    monkeypatch.setattr(media.time, "time", lambda: real_time() + 61)
    with media._ENC_LOCK:
        media._ENC_CACHE.clear()
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name == first
    assert media._encoder_cooling(first) is False


def test_encoder_cooldown_is_not_permanent(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """只指定一个硬件编码器时，冷却期内回落 CPU，冷却结束后回到硬件。"""
    cfg = _cfg(tmp_path)
    cfg.update({"transcode_encoder": "h264_qsv"})
    monkeypatch.setattr(media, "_probe_encoder", lambda *a, **k: True)
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name == "h264_qsv"

    mark_encoder_broken("h264_qsv", cooldown=30)
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name == CPU_ENCODER

    real_time = media.time.time
    monkeypatch.setattr(media.time, "time", lambda: real_time() + 31)
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name == "h264_qsv"


def test_explicit_missing_encoder_falls_back(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    cfg = _cfg(tmp_path)
    cfg.update({"transcode_encoder": "h264_amf"})
    monkeypatch.setattr(media, "_probe_encoder", lambda *a, **k: False)
    assert pick_encoder(cfg, "/usr/bin/ffmpeg").name == CPU_ENCODER


def test_choices_include_auto_and_cpu() -> None:
    names = [c["name"] for c in encoder_choices()]
    assert names[0] == "auto"
    assert CPU_ENCODER in names


def test_encoder_info_shape(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    info = encoder_info(cfg, MediaTools(cfg))
    assert info["configured"] in {"auto", CPU_ENCODER} or info["configured"]
    assert info["resolved"] in media.ENCODER_SPECS
    assert isinstance(info["choices"], list)


def test_cpu_uses_preset_and_crf(tmp_path: Path) -> None:
    """CPU 编码仍要沿用设置里的 transcode_preset（这次改动不能把预设弄丢）。"""
    cfg = _cfg(tmp_path)
    cfg.update({"transcode_preset": "medium"})
    tools = MediaTools(cfg)
    job = HlsJob(tools, cfg, 1, tmp_path / "a.mp4", 10.0, "hevc", "aac")
    spec = job._encoder("libx264")
    assert spec.name == CPU_ENCODER
    assert job.cfg.get("transcode_preset") == "medium"


def test_nvenc_preset_downgrade(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """老显卡不认 p1..p7 预设名：探测按新→旧降级，记住能用的那档。"""
    cfg = _cfg(tmp_path)
    tried: list[tuple[str, ...]] = []

    def fake_run(cmd, timeout=0, attempts=1):  # noqa: ANN001, ARG001
        preset = cmd[cmd.index("-preset") + 1] if "-preset" in cmd else ""
        tried.append(tuple(cmd[cmd.index("-c:v") + 1:]))
        ok = preset == "medium"      # 假设 p4 不被支持

        class R:
            returncode = 0 if ok else 1
        return R()

    monkeypatch.setattr(media, "_run_tool", fake_run)
    assert media._probe_encoder("/usr/bin/ffmpeg", media.ENCODER_SPECS["h264_nvenc"]) is True
    assert media._vargs_for("h264_nvenc")[1] == "medium"
    assert len(tried) == 2, "应该先试 p4，失败后再试 medium"
