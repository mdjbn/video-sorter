"""ffmpeg / ffprobe 封装：探测元数据、生成封面、按需 HLS 转码。

ffmpeg 查找顺序：环境变量 VIDEOSORTER_FFMPEG → 程序目录/tools → 数据目录/tools
→ PATH。Windows 桌面版会把 ffmpeg.exe 放在 tools/ 里随包分发。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import Config

IS_WIN = sys.platform.startswith("win")
EXE = ".exe" if IS_WIN else ""

# 浏览器 / ExoPlayer 能直接播的组合（其余走按需转码）
DIRECT_VCODECS = {"h264", "vp8", "vp9", "av1"}
DIRECT_ACODECS = {"aac", "mp3", "opus", "vorbis", "none", ""}
DIRECT_EXTS = {".mp4", ".m4v", ".webm", ".mov"}


class MediaError(RuntimeError):
    pass


def _tool_dirs(cfg: Config | None) -> list[Path]:
    dirs: list[Path] = []
    if os.environ.get("VIDEOSORTER_TOOLS"):
        dirs.append(Path(os.environ["VIDEOSORTER_TOOLS"]))
    here = Path(__file__).resolve().parent
    dirs.append(here.parent / "tools")             # server/tools（开发时）
    dirs.append(here / "tools")
    # 打包后：<安装目录>/tools/ffmpeg.exe（Windows 桌面端与绿色版都这么放）
    exe_dir = Path(sys.executable).resolve().parent
    dirs.append(exe_dir / "tools")
    # 安装包布局是 <安装目录>/binaries/videosorter-server/videosorter-server.exe，
    # tools 落在安装根目录，所以要往上多看两层才够（以前只看到 parent，
    # 结果装好的应用扫描时永远报「未找到 ffmpeg」）。
    dirs.extend(parent / "tools" for parent in list(exe_dir.parents)[:2])
    if getattr(sys, "_MEIPASS", None):             # PyInstaller 解包目录
        dirs.append(Path(sys._MEIPASS) / "tools")
    if cfg is not None:
        dirs.append(cfg.data_dir / "tools")
    return dirs


def find_tool(name: str, cfg: Config | None = None) -> str | None:
    env_key = "VIDEOSORTER_" + name.upper()
    if os.environ.get(env_key):
        p = Path(os.environ[env_key])
        if p.exists():
            return str(p)
    for d in _tool_dirs(cfg):
        cand = d / (name + EXE)
        if cand.exists():
            return str(cand)
    return shutil.which(name)


class MediaTools:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ffmpeg = find_tool("ffmpeg", cfg)
        self.ffprobe = find_tool("ffprobe", cfg)

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe)

    def require(self) -> tuple[str, str]:
        if not self.available:
            raise MediaError(
                "未找到 ffmpeg/ffprobe。请安装 ffmpeg 并加入 PATH，"
                "或把 ffmpeg.exe、ffprobe.exe 放到程序目录的 tools/ 下。"
            )
        return self.ffmpeg, self.ffprobe  # type: ignore[return-value]


def _run_tool(cmd: list[str], timeout: int, attempts: int = 2) -> subprocess.CompletedProcess | None:
    """跑一个外部命令并捕获输出；超时就重试一次。

    这台机器上偶发「子进程启动即挂住」（HLS 那边观察到的 0xC0000142
    STATUS_DLL_INIT_FAILED 一类），挂住时要等满超时才返回。以前 ffprobe 单次超时是
    60s，扫描就会整体卡住一分钟、验收脚本跟着超时误报失败；现在把单次超时压短，
    失败再重试一次（重试几乎总是立刻成功），最坏耗时反而更短。
    """
    for i in range(max(1, attempts)):
        try:
            return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            if i + 1 >= attempts:
                return None
        except OSError:
            return None
    return None


# ---------------------------------------------------------------------------
# 转码编码器：能用显卡就用显卡，探测不到（没驱动 / 没权限 / 容器里没设备）自动回落 CPU。
#
# 为什么要探测而不是先验判断：硬件编码器「有没有被编译进 ffmpeg」和「这台机器能不能用」
# 是两件事——Windows 包里 ffmpeg 同时带 nvenc/qsv/amf，但机器只有 NVIDIA 时 qsv 会报
# `Error creating a MFX session: -9`、amf 会报 `DLL amfrt64.dll failed to open`；
# fnOS 上 /dev/dri 存在但应用用户不在 render 组时 qsv 也是同样的错。所以统一用一次
# 极小的 lavfi 编码试跑（256x144 一帧）来判定，结果按 (ffmpeg, 用户选择) 缓存。
# ---------------------------------------------------------------------------

QUALITY = 23  # 画质基准：x264 的 crf / qsv 的 global_quality / nvenc 的 cq 都用它


@dataclass(frozen=True)
class EncoderSpec:
    name: str
    label: str
    hw: bool = True
    hwaccel: tuple[str, ...] = ()   # 放在 -i 之前的硬件初始化参数
    decoder_args: tuple[str, ...] = ()  # 放在 -i 之前的解码加速参数（-hwaccel …）
    vargs: tuple[str, ...] = ()     # 跟在 -c:v 后面的画质参数
    vf_extra: str = ""              # 追加到 -vf 末尾（vaapi 需要 format=nv12,hwupload）

    @property
    def key(self) -> str:
        return self.name


ENCODER_SPECS: dict[str, EncoderSpec] = {
    "h264_nvenc": EncoderSpec(
        "h264_nvenc", "NVIDIA 显卡（NVENC）",
        decoder_args=("-hwaccel", "cuda"),
        vargs=("-preset", "p4", "-rc", "vbr", "-cq", str(QUALITY), "-b:v", "0"),
    ),
    "h264_qsv": EncoderSpec(
        "h264_qsv", "Intel 核显（Quick Sync）",
        decoder_args=("-hwaccel", "qsv"),
        vargs=("-global_quality", str(QUALITY)),
    ),
    "h264_amf": EncoderSpec(
        "h264_amf", "AMD 显卡（AMF）",
        decoder_args=("-hwaccel", "d3d11va"),
        vargs=("-rc", "cqp", "-qp_i", str(QUALITY), "-qp_p", str(QUALITY)),
    ),
    "h264_videotoolbox": EncoderSpec(
        "h264_videotoolbox", "Apple 芯片（VideoToolbox）",
        decoder_args=("-hwaccel", "videotoolbox"),
        vargs=("-q:v", "55"),
    ),
    "h264_vaapi": EncoderSpec(
        "h264_vaapi", "Intel/AMD 核显（VAAPI）",
        hwaccel=("-vaapi_device", "/dev/dri/renderD128"),
        decoder_args=("-hwaccel", "vaapi"),
        vargs=("-qp", str(QUALITY)),
        vf_extra=",format=nv12,hwupload",
    ),
    "libx264": EncoderSpec(
        "libx264", "CPU（libx264）", hw=False,
        # 即使编码在 CPU 上，解码也可以交给显卡（实测 1080p HEVC 解码 CPU 时间减半）；
        # 硬件解不了的编码 ffmpeg 会自动回落软解，不会因此失败。
        decoder_args=("-hwaccel", "auto"),
        vargs=("-preset", "veryfast", "-crf", str(QUALITY)),
    ),
}

CPU_ENCODER = "libx264"

# 每台机器的候选顺序：显卡厂商不同，先试最可能的那个，探测失败再下一个
def _candidate_encoders() -> list[str]:
    if IS_WIN:
        return ["h264_nvenc", "h264_qsv", "h264_amf"]
    if sys.platform == "darwin":
        return ["h264_videotoolbox"]
    return ["h264_qsv", "h264_vaapi"]


_ENC_LOCK = threading.Lock()
_ENC_CACHE: dict[tuple[str, str], str] = {}   # (ffmpeg 路径, 用户选择) -> 实际编码器名
_ENC_BROKEN: set[str] = set()                 # 本进程里实测转码失败的硬件编码器
# 少数老显卡不认新参数（Pascal 及更早的 NVENC 没有 p1..p7 预设名），探测时按「先新后旧」
# 试一遍，把能用的那档记下来；真实转码用同一档，避免「探测通过、转码失败」。
_VARIANTS: dict[str, dict[str, str]] = {}
NVENC_PRESETS = ("p4", "medium", "slow")


def _vargs_for(name: str) -> tuple[str, ...]:
    if name == "h264_nvenc":
        preset = _VARIANTS.get("h264_nvenc", {}).get("preset", "p4")
        return ("-preset", preset, "-rc", "vbr", "-cq", str(QUALITY), "-b:v", "0")
    return ENCODER_SPECS[name].vargs


def _probe_attempts(spec: EncoderSpec) -> list[tuple[str, ...]]:
    """探测要试的参数组合（一般只有一种，NVENC 会逐档降级）。"""
    if spec.name == "h264_nvenc":
        return [(("-preset", p, "-rc", "vbr", "-cq", str(QUALITY), "-b:v", "0"))
                for p in NVENC_PRESETS]
    return [spec.vargs]


def reset_encoder_cache() -> None:
    """设置改了编码器、或想重新探测时调用（测试也靠它清缓存）。"""
    with _ENC_LOCK:
        _ENC_CACHE.clear()
        _ENC_BROKEN.clear()
        _VARIANTS.clear()


def encoder_choices() -> list[dict[str, Any]]:
    """给设置页用的候选列表（顺序按当前平台的可能程度排）。"""
    out = [{"name": "auto", "label": "自动（优先用显卡）", "hw": False}]
    for name in _candidate_encoders():
        spec = ENCODER_SPECS.get(name)
        if spec is not None:
            out.append({"name": name, "label": spec.label, "hw": True})
    out.append({"name": CPU_ENCODER, "label": ENCODER_SPECS[CPU_ENCODER].label, "hw": False})
    return out


def _probe_encoder(ffmpeg: str, spec: EncoderSpec, timeout: int = 20) -> bool:
    """用一帧 testsrc2 试编码，退出码 0 才算可用。"""
    for vargs in _probe_attempts(spec):
        vf = "format=nv12,hwupload" if spec.vf_extra else ""
        args = [ffmpeg, "-hide_banner", "-v", "error", *spec.hwaccel,
                "-f", "lavfi", "-i", "testsrc2=size=256x144:rate=5", "-t", "1"]
        if vf:
            args += ["-vf", vf]
        args += ["-c:v", spec.name, *vargs]
        if not spec.vf_extra:
            args += ["-pix_fmt", "yuv420p"]
        args += ["-f", "null", "-"]
        r = _run_tool(args, timeout=timeout, attempts=1)
        if r is not None and r.returncode == 0:
            if spec.name == "h264_nvenc" and vargs and "-preset" in vargs:
                _VARIANTS.setdefault("h264_nvenc", {})["preset"] = vargs[1]
            return True
    return False


def _detect_encoder(choice: str, ffmpeg: str | None) -> str:
    """在给定选择下判定实际编码器；任何异常都回落 libx264。"""
    if not ffmpeg:
        return CPU_ENCODER
    wanted = str(choice or "auto").strip().lower()
    if wanted not in {"", "auto"}:
        spec = ENCODER_SPECS.get(wanted)
        if spec is None:
            return CPU_ENCODER
        if not spec.hw:
            return CPU_ENCODER
        if wanted in _ENC_BROKEN:
            return CPU_ENCODER
        return wanted if _probe_encoder(ffmpeg, spec) else CPU_ENCODER
    for name in _candidate_encoders():
        spec = ENCODER_SPECS.get(name)
        if spec is None or name in _ENC_BROKEN:
            continue
        try:
            if _probe_encoder(ffmpeg, spec):
                return name
        except OSError:
            continue
    return CPU_ENCODER


def pick_encoder(cfg: Config, ffmpeg: str | None = None) -> EncoderSpec:
    """决定本次转码用哪个编码器（带进程级缓存，探测只跑一次）。"""
    choice = str(cfg.get("transcode_encoder", "auto") or "auto").strip().lower()
    if choice not in ENCODER_SPECS and choice != "auto":
        choice = "auto"
    key = (str(ffmpeg or ""), choice)
    with _ENC_LOCK:
        cached = _ENC_CACHE.get(key)
    if cached is not None:
        return ENCODER_SPECS[cached]
    name = _detect_encoder(choice, ffmpeg)
    with _ENC_LOCK:
        _ENC_CACHE[key] = name
    return ENCODER_SPECS[name]


def mark_encoder_broken(name: str) -> None:
    """真实转码时硬件编码失败：本进程内不再尝试它（下次直接 CPU，免得每次都白跑一遍）。"""
    if not name or name == CPU_ENCODER:
        return
    with _ENC_LOCK:
        _ENC_BROKEN.add(name)
        for key in list(_ENC_CACHE):
            if _ENC_CACHE[key] == name:
                _ENC_CACHE[key] = CPU_ENCODER


def encoder_info(cfg: Config, tools: MediaTools) -> dict[str, Any]:
    """当前生效的编码器（给 /api/info 与设置页显示）。"""
    spec = pick_encoder(cfg, tools.ffmpeg)
    return {
        "configured": str(cfg.get("transcode_encoder", "auto") or "auto"),
        "resolved": spec.name,
        "label": spec.label,
        "hardware": spec.hw,
        "choices": encoder_choices(),
    }


def probe(tools: MediaTools, path: Path) -> dict[str, Any]:
    """用 ffprobe 读元数据。失败时返回尽可能多的默认值，不抛异常。"""
    ffmpeg, ffprobe = tools.require()
    cmd = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    out = _run_tool(cmd, timeout=20)
    try:
        data = json.loads((out.stdout if out is not None else b"").decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "duration": 0.0, "width": 0, "height": 0,
                "vcodec": "", "acodec": "", "bitrate": 0}

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})

    def _f(x: Any) -> float:
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0

    duration = _f(fmt.get("duration")) or _f(v.get("duration"))
    fps = 0.0
    rate = v.get("avg_frame_rate") or v.get("r_frame_rate") or ""
    if "/" in str(rate):
        num, _, den = str(rate).partition("/")
        if _f(den):
            fps = round(_f(num) / _f(den), 3)
    return {
        "ok": bool(v or a),
        "duration": duration,
        "width": int(_f(v.get("width"))),
        "height": int(_f(v.get("height"))),
        "vcodec": (v.get("codec_name") or "").lower(),
        "acodec": (a.get("codec_name") or "").lower(),
        "bitrate": int(_f(fmt.get("bit_rate"))),
        "fps": fps,
    }


def can_direct_play(ext: str, vcodec: str, acodec: str) -> bool:
    ext = (ext or "").lower()
    return (
        ext in DIRECT_EXTS
        and (vcodec or "").lower() in DIRECT_VCODECS
        and (acodec or "").lower() in DIRECT_ACODECS
    )


def needs_transcode(ext: str, vcodec: str, acodec: str) -> bool:
    """这个文件是不是必须转码才能在浏览器里播。"""
    return not can_direct_play(ext, vcodec, acodec)


CODEC_LABEL = {
    "h264": "H.264", "hevc": "HEVC", "h265": "HEVC", "vp8": "VP8", "vp9": "VP9", "av1": "AV1",
    "mpeg4": "MPEG-4", "msmpeg4v3": "MS MPEG-4", "wmv3": "WMV3", "vc1": "VC-1", "theora": "Theora",
    "aac": "AAC", "mp3": "MP3", "ac3": "AC3", "eac3": "E-AC3", "dts": "DTS", "opus": "Opus",
    "vorbis": "Vorbis", "flac": "FLAC", "truehd": "TrueHD", "pcm_s16le": "PCM", "wmav2": "WMA",
}


def transcode_reason(ext: str, vcodec: str, acodec: str) -> str:
    """给「转码标记」用的中文原因，例如「HEVC 视频编码 浏览器不能直放…」。"""
    ext = (ext or "").lower()
    vcodec = (vcodec or "").lower()
    acodec = (acodec or "").lower()
    parts: list[str] = []
    if ext not in DIRECT_EXTS:
        parts.append(f"{ext or '未知格式'} 容器")
    if vcodec not in DIRECT_VCODECS:
        parts.append(f"{CODEC_LABEL.get(vcodec, vcodec or '未知')} 视频编码")
    if acodec not in DIRECT_ACODECS:
        parts.append(f"{CODEC_LABEL.get(acodec, acodec or '未知')} 音频编码")
    if not parts:
        return "浏览器不能直放，边转码边播放（H.264/AAC）"
    return "、".join(parts) + "，浏览器不能直放 → 边转码边播放（H.264/AAC）"


def make_thumb(tools: MediaTools, src: Path, out: Path, duration: float, ratio: float = 0.0) -> bool:
    ffmpeg, _ = tools.require()
    out.parent.mkdir(parents=True, exist_ok=True)
    # ratio=0（默认）即取视频第一帧作为封面
    at = max(0.0, min(duration * ratio, max(duration - 1, 0))) if (duration > 1 and ratio > 0) else 0.0
    cmd = [
        ffmpeg, "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(src),
        "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(out),
    ]
    try:
        r = _run_tool(cmd, timeout=45)
        if r is not None and r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return True
        # 取首帧兜底
        cmd[4] = "0"
        r = _run_tool(cmd, timeout=45)
        return r is not None and r.returncode == 0 and out.exists() and out.stat().st_size > 0
    except OSError:
        return False


class HlsJob:
    """把一个视频切成 HLS。h264+aac 直接 -c copy（秒级），其余转码。"""

    def __init__(self, tools: MediaTools, cfg: Config, video_id: int, src: Path,
                 duration: float, vcodec: str, acodec: str,
                 on_progress: Callable[[float, str], None] | None = None,
                 start: float = 0.0):
        self.tools = tools
        self.cfg = cfg
        self.video_id = video_id
        self.src = src
        self.duration = duration
        self.on_progress = on_progress
        # start > 0：从这一秒开始切（拖动进度条时用），产物放在 s<秒> 子目录，
        # 时间轴从 0 开始，播放器那边把「媒体时间 + start」当作绝对位置。
        self.start = max(0.0, float(start or 0.0))
        self.lock = threading.Lock()
        # 拖动进度条会连续换起点：新起点起来时要把旧那一路掐掉，别在 NAS 上跑一堆 ffmpeg
        self.cancel = threading.Event()
        self.status = "pending"     # pending | running | done | error
        self.error = ""
        self.encoder = ""           # 实际用的编码器（转码结束后填，便于排查）
        sub = "" if self.start <= 0 else f"/s{int(self.start)}"
        self.dir = cfg.hls_dir / str(video_id) if not sub else cfg.hls_dir / str(video_id) / f"s{int(self.start)}"
        self.playlist = self.dir / "index.m3u8"
        # -c copy 只对「mp4/mkv 家族 + h264 + aac/无音轨」安全；.avi/.wmv 这类老容器
        # 直接 copy 到 MPEG-TS 常被 ffmpeg 拒掉（真机调试时 镜头语言笔记.avi 就挂了），宁可转码。
        copy_exts = {".mp4", ".m4v", ".mov", ".mkv"}
        self.copy_mode = (
            (vcodec or "").lower() == "h264"
            and (acodec or "").lower() in {"aac", ""}
            and src.suffix.lower() in copy_exts
        )

    @property
    def ready(self) -> bool:
        return self.playlist.exists() and self.playlist.stat().st_size > 0

    @property
    def finished(self) -> bool:
        return (self.dir / ".done").exists()

    def _progress(self, pct: float, msg: str = "") -> None:
        if self.on_progress:
            try:
                self.on_progress(max(0.0, min(1.0, pct)), msg)
            except Exception:
                pass

    def run(self) -> None:
        with self.lock:
            if self.finished and self.ready:
                self.status = "done"
                return
            self.dir.mkdir(parents=True, exist_ok=True)
            for f in self.dir.glob("seg*.ts"):
                f.unlink(missing_ok=True)
            self.playlist.unlink(missing_ok=True)
            (self.dir / ".done").unlink(missing_ok=True)
            ffmpeg, _ = self.tools.require()
            self.status = "running"
            # copy 失败时自动回退到完整转码：容器/编码稍有不对劲，copy 就会整段失败，
            # 而用户只看到「转码失败」——多试一次能救回绝大多数文件。
            attempts: list[tuple[bool, str]] = []
            if self.copy_mode:
                attempts.append((True, ""))
            attempts.append((False, ""))   # 空 override = 自动（显卡优先）
            last_rc, last_err, last_enc = 0, "", ""
            for copy, override in attempts:
                for f in self.dir.glob("seg*.ts"):
                    f.unlink(missing_ok=True)
                self.playlist.unlink(missing_ok=True)
                last_rc, last_err, last_enc = self._run_ffmpeg(ffmpeg, copy, override)
                if last_rc == 0 and self.ready and self.playlist.stat().st_size > 0:
                    self.status = "done"
                    self.encoder = last_enc
                    (self.dir / ".done").write_text(str(time.time()), encoding="utf-8")
                    self._progress(1.0, "转码完成")
                    return
            # 硬件编码器在实际转码里挂了（驱动刚更新、显存不够、权限变了……探测那一下
            # 试不出来），再用 CPU 补一次，不让用户看到「转码失败」。
            if not self.copy_mode and last_enc and last_enc != CPU_ENCODER:
                mark_encoder_broken(last_enc)
                for f in self.dir.glob("seg*.ts"):
                    f.unlink(missing_ok=True)
                self.playlist.unlink(missing_ok=True)
                last_rc, last_err, last_enc = self._run_ffmpeg(ffmpeg, False, CPU_ENCODER)
                if last_rc == 0 and self.ready and self.playlist.stat().st_size > 0:
                    self.status = "done"
                    self.encoder = last_enc
                    (self.dir / ".done").write_text(str(time.time()), encoding="utf-8")
                    self._progress(1.0, "转码完成（已回落 CPU）")
                    return
            if self.cancel.is_set():
                # 被更新的起点取代：不算失败，也别喊「转码失败」
                self.status = "error"
                self.error = "已切换到更近的转码位置"
                self._progress(1.0, self.error)
                return
            # 全部尝试失败：清掉半截产物，别让播放器拿到坏 playlist
            for f in self.dir.glob("seg*.ts"):
                f.unlink(missing_ok=True)
            self.playlist.unlink(missing_ok=True)
            self.status = "error"
            tail = last_err.strip().splitlines()[-1] if last_err.strip() else ""
            self.error = f"转码失败（ffmpeg 退出码 {last_rc}）" + (f"：{tail}" if tail else "")
            self._progress(1.0, self.error)

    # Windows 上偶尔会碰上 ffmpeg 还没跑到自己的 main 就 0xC0000142（STATUS_DLL_INIT_FAILED）
    # 的情况：stderr 一个字节都没有，同样的命令行重跑一次就好；两个转码同时启动时更容易撞上
    # （实测 20 轮里约一半）。用户看到的就是「转码失败（ffmpeg 退出码 3221225794）」且怎么
    # 重试都一样，所以这里对「启动即失败」自动补一次。
    LAUNCH_FAILED = 3221225794

    def _run_ffmpeg(self, ffmpeg: str, copy: bool, override: str = "") -> tuple[int, str, str]:
        rc, err, enc = self._run_ffmpeg_once(ffmpeg, copy, override)
        if rc == self.LAUNCH_FAILED and not err.strip():
            time.sleep(0.3)
            rc, err, enc = self._run_ffmpeg_once(ffmpeg, copy, override)
        return rc, err, enc

    def _encoder(self, override: str = "") -> EncoderSpec:
        if override:
            return ENCODER_SPECS.get(override, ENCODER_SPECS[CPU_ENCODER])
        return pick_encoder(self.cfg, self.tools.ffmpeg)

    def _run_ffmpeg_once(self, ffmpeg: str, copy: bool, override: str = "") -> tuple[int, str, str]:
        spec = self._encoder(override)
        cmd = [ffmpeg, "-y", "-v", "error", *spec.hwaccel, *spec.decoder_args]
        if self.start > 0:
            # 输入端 seek（在 -i 之前）走关键帧，秒级就绪；输出时间轴仍然从 0 起
            cmd += ["-ss", f"{self.start:.3f}"]
        cmd += ["-i", str(self.src)]
        if copy:
            cmd += ["-c", "copy"]
        else:
            vf = "scale='min(1920,iw)':-2" + spec.vf_extra
            vargs = _vargs_for(spec.name)
            if spec.name == CPU_ENCODER:
                # CPU 编码沿用设置里的「转码预设」（ultrafast…slow）
                vargs = ("-preset", str(self.cfg.get("transcode_preset", "veryfast")),
                         "-crf", str(QUALITY))
            cmd += ["-c:v", spec.name, *vargs]
            if not spec.vf_extra:
                cmd += ["-pix_fmt", "yuv420p"]
            cmd += [
                "-vf", vf,
                "-c:a", "aac", "-b:a", "128k", "-ac", "2",
            ]
        cmd += [
            "-hls_time", "4", "-hls_playlist_type", "event",
            "-hls_segment_filename", str(self.dir / "seg%05d.ts"),
            "-progress", "pipe:1", "-nostats", str(self.playlist),
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, bufsize=1)
        except (OSError, subprocess.SubprocessError) as e:
            return 1, str(e), spec.name
        err_lines: list[str] = []

        def _drain() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                err_lines.append(line.rstrip())
                if len(err_lines) > 60:
                    del err_lines[0]

        th = threading.Thread(target=_drain, daemon=True)
        th.start()
        assert proc.stdout is not None
        for line in proc.stdout:
            if self.cancel.is_set():
                proc.terminate()
                break
            line = line.strip()
            if line.startswith("out_time_ms=") and self.duration > 0:
                try:
                    sec = self.start + int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                self._progress(sec / self.duration, "转码中")
        proc.wait()
        th.join(timeout=2)
        return proc.returncode, "\n".join(err_lines[-6:]), spec.name


class HlsManager:
    """按需转码：同一视频只有一个后台转码任务；播放器轮询 m3u8 是否已出现。"""

    def __init__(self, tools: MediaTools, cfg: Config):
        self.tools = tools
        self.cfg = cfg
        self.jobs: dict[int, HlsJob] = {}
        self.lock = threading.Lock()

    def job_for(self, video_id: int, src: Path, duration: float,
                vcodec: str, acodec: str, start: float = 0.0) -> HlsJob:
        key = (video_id, int(max(0.0, float(start or 0.0))))
        with self.lock:
            job = self.jobs.get(key)
            if job is None or job.src != src:
                job = HlsJob(self.tools, self.cfg, video_id, src, duration, vcodec, acodec,
                             start=key[1])
                self.jobs[key] = job
                # 同一个视频换了起点：把其它「拖动出来」的转码任务停掉（一次拖动只留最新那一路）。
                # 注意不能停 s0 那一路：正片可能还在播它，掐了会直接黑屏。
                if key[1] > 0:
                    for (vid, other_start), other in self.jobs.items():
                        if (vid == video_id and other_start > 0 and other_start != key[1]
                                and other.status == "running"):
                            other.cancel.set()
            return job

    def ensure(self, video_id: int, src: Path, duration: float,
               vcodec: str, acodec: str, start: float = 0.0) -> HlsJob:
        job = self.job_for(video_id, src, duration, vcodec, acodec, start)
        if job.status in {"done", "error"} and job.finished:
            return job
        if job.status == "running":
            return job
        t = threading.Thread(target=job.run, name=f"hls-{video_id}-{int(job.start)}", daemon=True)
        job.status = "running"
        t.start()
        return job

    def job_for_video(self, video_id: int) -> HlsJob | None:
        """给状态接口用：优先全片任务（start=0），没有就返回任意一个。"""
        with self.lock:
            return self.jobs.get((video_id, 0)) or next(
                (j for (vid, _), j in self.jobs.items() if vid == video_id), None)

    def clear_all(self) -> None:
        """清空所有转码产物与任务状态（「清除缓存」用）。"""
        root = self.cfg.hls_dir
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        with self.lock:
            self.jobs.clear()

    def cleanup(self, video_id: int) -> None:
        d = self.cfg.hls_dir / str(video_id)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        with self.lock:
            for key in [k for k in self.jobs if k[0] == video_id]:
                self.jobs.pop(key, None)
