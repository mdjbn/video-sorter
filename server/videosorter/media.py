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

# 手机 App（ExoPlayer + 系统解码器）比浏览器能吃得多：MKV/TS 容器、HEVC/MPEG-4 视频、
# AC3/EAC3/DTS/FLAC 音频在绝大多数机型上都能硬解直放。这类格式直连 raw 既不用转码
# 也不占 NAS 的 CPU，播放器解不了的极端情况会自己退回到 /play 的转码链路。
# 说明：这里只放宽「能不能交给播放器试一下」，网页端仍然用上面那套保守集合。
CLIENT_VCODECS = DIRECT_VCODECS | {"hevc"}
CLIENT_ACODECS = DIRECT_ACODECS | {"ac3", "eac3", "flac"}
CLIENT_EXTS = DIRECT_EXTS | {".mkv", ".ts", ".m2ts", ".mts"}


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

# 转码「多久还没吐出第一个分片就判死」。极少数源会让硬件解码器陷入无限重建 MFX
# session 的循环（实测一个 720x1280 的录屏流，20 秒片源跑了 5 分钟连 2 秒都没转完，
# CPU 反而吃满整核，比软解还慢几百倍），这种文件不值得等，直接告诉用户放不了。
# 正常文件（哪怕 4K HEVC 硬解）第一个分片 3~5 秒就出来了，60 秒足够宽松。
FIRST_SEGMENT_TIMEOUT = 60.0


@dataclass(frozen=True)
class EncoderSpec:
    name: str
    label: str
    hw: bool = True
    hwaccel: tuple[str, ...] = ()   # 放在 -i 之前的硬件初始化参数
    decoder_args: tuple[str, ...] = ()  # 放在 -i 之前的解码加速参数（-hwaccel …）
    vargs: tuple[str, ...] = ()     # 跟在 -c:v 后面的画质参数
    vf_extra: str = ""              # 追加到 -vf 末尾（vaapi 需要 format=nv12,hwupload）
    # 硬件解码器名后缀：源是 h265 就用 hevc_qsv、h264 用 h264_qsv。
    # 只写 "-hwaccel qsv" 时 ffmpeg 会让解码器自己挑；实测在部分源上它会静默回落到
    # 软解（dec0:0 线程吃满 73% CPU），而编码已经上了 GPU —— 用户看到的就是
    # 「GPU 只占 16%，CPU 却 98%」。显式指定解码器才能确保解码也走显卡。
    hw_decoder_suffix: str = ""     # 例如 "_qsv" / "_cuvid" / "_vaapi"
    # 硬件解码后像素留在显存里，滤镜链也要用对应的硬件滤镜（scale_qsv 等），
    # 否则 ffmpeg 会把帧下载回内存，等于白解。
    hw_scale: str = ""              # 例如 "scale_qsv" / "scale_cuda" / "scale_vaapi"

    @property
    def key(self) -> str:
        return self.name


# 源视频编码 → 各硬件解码器的前缀
HW_DECODER_PREFIX = {
    "h264": "h264",
    "hevc": "hevc",
    "h265": "hevc",
    "av1": "av1",
    "vp9": "vp9",
    "mpeg2video": "mpeg2",
}


ENCODER_SPECS: dict[str, EncoderSpec] = {
    "h264_nvenc": EncoderSpec(
        "h264_nvenc", "NVIDIA 显卡（NVENC）",
        decoder_args=("-hwaccel", "cuda", "-hwaccel_output_format", "cuda"),
        vargs=("-preset", "p4", "-rc", "vbr", "-cq", str(QUALITY), "-b:v", "0"),
        hw_decoder_suffix="_cuvid",
        hw_scale="scale_cuda",
    ),
    "h264_qsv": EncoderSpec(
        "h264_qsv", "Intel 核显（Quick Sync）",
        # 实测（fnOS / i3-9100T / ffmpeg 8.1.1-mediasrv）：不指定 -qsv_device 时
        # QSV 自己挑设备，编码器初始化"成功"却完全不上 GPU —— GPU 频率一直停在
        # 350MHz、busy 0%，而 dec 线程吃满一个核、几十分钟不吐一个分片。
        # Jellyfin 在同一台机器上用 QSV 能跑到 GPU 80%，它显式给了设备路径，
        # 所以这里也把 DRM 节点点明。
        decoder_args=("-qsv_device", "/dev/dri/renderD128",
                      "-hwaccel", "qsv", "-hwaccel_output_format", "qsv"),
        vargs=("-global_quality", str(QUALITY)),
        hw_decoder_suffix="_qsv",
        hw_scale="scale_qsv",
    ),
    "h264_amf": EncoderSpec(
        "h264_amf", "AMD 显卡（AMF）",
        decoder_args=("-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11"),
        vargs=("-rc", "cqp", "-qp_i", str(QUALITY), "-qp_p", str(QUALITY)),
        hw_decoder_suffix="_d3d11va",
    ),
    "h264_videotoolbox": EncoderSpec(
        "h264_videotoolbox", "Apple 芯片（VideoToolbox）",
        decoder_args=("-hwaccel", "videotoolbox"),
        vargs=("-q:v", "55"),
    ),
    "h264_vaapi": EncoderSpec(
        "h264_vaapi", "Intel/AMD 核显（VAAPI）",
        hwaccel=("-vaapi_device", "/dev/dri/renderD128"),
        decoder_args=("-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"),
        vargs=("-qp", str(QUALITY)),
        vf_extra=",format=nv12,hwupload",
        hw_decoder_suffix="_vaapi",
        hw_scale="scale_vaapi",
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
# 实测转码失败的硬件编码器 → 冷却截止时间。之前这里是 set()，一次失败就整个进程寿命
# 永久拉黑：核显偶尔抖一下（多路并发、显存紧、驱动刚加载）之后，所有转码都变成 CPU 满载，
# 用户看到的就是「GPU 只占 16%，CPU 却 98%」。改成限时冷却，到期自动重试。
_ENC_BROKEN: dict[str, float] = {}
ENCODER_COOLDOWN = 300.0   # 秒；硬件编码失败后冷却多久再试
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


def _encoder_cooling(name: str) -> bool:
    """这个硬件编码器是否还在失败冷却期内（冷却过期就自动解禁）。"""
    with _ENC_LOCK:
        until = _ENC_BROKEN.get(name)
        if until is None:
            return False
        if time.time() >= until:
            _ENC_BROKEN.pop(name, None)
            return False
        return True


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
        if _encoder_cooling(wanted):
            return CPU_ENCODER
        return wanted if _probe_encoder(ffmpeg, spec) else CPU_ENCODER
    for name in _candidate_encoders():
        spec = ENCODER_SPECS.get(name)
        if spec is None or _encoder_cooling(name):
            continue
        try:
            if _probe_encoder(ffmpeg, spec):
                return name
        except OSError:
            continue
    return CPU_ENCODER


def pick_encoder(cfg: Config, ffmpeg: str | None = None) -> EncoderSpec:
    """决定本次转码用哪个编码器（成功结果带进程级缓存，探测只跑一次）。"""
    choice = str(cfg.get("transcode_encoder", "auto") or "auto").strip().lower()
    if choice not in ENCODER_SPECS and choice != "auto":
        choice = "auto"
    key = (str(ffmpeg or ""), choice)
    with _ENC_LOCK:
        cached = _ENC_CACHE.get(key)
    if cached is not None:
        return ENCODER_SPECS[cached]
    name = _detect_encoder(choice, ffmpeg)
    # 只缓存「找到显卡」的结果。探测失败往往是临时的（开机早期 /dev/dri 还没就绪、
    # 驱动正在加载、临时没权限……），把这种失败也缓存起来就会让整个进程寿命里都用 CPU，
    # 用户看到的就是「明明有核显，设置页却一直显示 CPU」——实测就踩过这个坑。
    # 失败不缓存：下次转码再探一次，代价只是一次几十毫秒的探测。
    if name != CPU_ENCODER:
        with _ENC_LOCK:
            _ENC_CACHE[key] = name
    return ENCODER_SPECS[name]


def mark_encoder_broken(name: str, cooldown: float | None = None) -> None:
    """真实转码时硬件编码失败：冷却一段时间，到期自动重试（**不再永久拉黑**）。

    永久拉黑的问题：i3 这类弱核显在多路并发 / 显存紧张时会偶发初始化失败，一旦拉黑，
    这台机器在进程重启前就只能 CPU 编码（实测 4 路里 2 路走 CPU，整机 CPU 96%）。
    """
    if not name or name == CPU_ENCODER:
        return
    seconds = ENCODER_COOLDOWN if cooldown is None else float(cooldown)
    with _ENC_LOCK:
        _ENC_BROKEN[name] = time.time() + max(0.0, seconds)
        # 缓存里指向它的项一起清掉：冷却结束后重新探测，别让旧结果挡住
        for key in list(_ENC_CACHE):
            if _ENC_CACHE[key] == name:
                _ENC_CACHE.pop(key, None)


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


def can_direct_play(ext: str, vcodec: str, acodec: str, client: str = "web") -> bool:
    """能不能把原文件直接交给播放器。

    client="web"（默认）按浏览器的保守集合判断；client="app" 用手机 App 的放宽集合
    （ExoPlayer 能硬解 MKV/HEVC/AC3 等），避免手机端为能直放的片子白白转码。
    """
    ext = (ext or "").lower()
    if (client or "web").lower() == "app":
        exts, vcodecs, acodecs = CLIENT_EXTS, CLIENT_VCODECS, CLIENT_ACODECS
    else:
        exts, vcodecs, acodecs = DIRECT_EXTS, DIRECT_VCODECS, DIRECT_ACODECS
    return (
        ext in exts
        and (vcodec or "").lower() in vcodecs
        and (acodec or "").lower() in acodecs
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
                 start: float = 0.0,
                 src_w: int = 0, src_h: int = 0):
        self.tools = tools
        self.cfg = cfg
        self.video_id = video_id
        self.src = src
        self.duration = duration
        self.vcodec = str(vcodec or "")
        self.acodec = str(acodec or "")
        # 源分辨率：硬件缩放滤镜只吃字面量尺寸，得自己算目标宽高
        self.src_w = int(src_w or 0)
        self.src_h = int(src_h or 0)
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
        # 最近一次被播放器请求的时间：并发超限时按它挤掉最久没人看的那一路
        self.touched = time.time()
        # 当前正在跑的 ffmpeg 子进程；服务退出时靠它把进程树清干净，否则会留下孤儿进程
        self.proc: subprocess.Popen | None = None
        # 所属的 HlsManager（HlsManager.job_for 里回填）：转码完成后顺带清理缓存时，
        # 用它查出「还有哪些视频正在转码」从而跳过，不让清理删掉正在写的分片
        self.manager: HlsManager | None = None
        # 这次转码是不是因为「迟迟不出分片」被掐掉的：用来区分「放不了」和「转码失败」
        self.stalled = False
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

    def _sweep_after_done(self) -> None:
        """一次转码刚跑完，顺手按上限/保留期清一次缓存。

        ffmpeg 是按需拉起来的，看完一部片子正好是「缓存又长了一点」的时机，
        等每小时那一轮要拖很久。放到 daemon 线程里做，别让播放器等清理：
        sweep_hls 自己会跳过活跃任务，异常也全吞掉，这里只兜底一层。
        """
        def _run() -> None:
            try:
                from .cache import sweep_hls
                res = sweep_hls(self.cfg, getattr(self, "manager", None))
                if res.get("removed_dirs"):
                    print(f"[cache] 转码完成后清理：删了 {res['removed_dirs']} 个目录，"
                          f"释放 {res['freed_bytes']} 字节", flush=True)
            except Exception:  # noqa: BLE001 - 清理失败绝不影响播放
                pass
        threading.Thread(target=_run, name="vs-hls-sweep-once", daemon=True).start()

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
                    self._sweep_after_done()
                    return
            # 卡死（久不出分片）就别再拿 CPU 重试了：这类源软解同样慢到不可用，
            # 重试只会把 NAS 再烧几分钟。用户要的是「直接告诉他放不了」。
            if self.stalled:
                for f in self.dir.glob("seg*.ts"):
                    f.unlink(missing_ok=True)
                self.playlist.unlink(missing_ok=True)
                self.status = "error"
                self.error = "该视频格式无法播放"
                self._progress(1.0, self.error)
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
                    self._sweep_after_done()
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

    def _hw_decoder(self, spec: EncoderSpec) -> str:
        """源视频能硬解就用对应的硬件解码器（hevc_qsv / h264_cuvid …），否则返回空。

        VAAPI 是个例外：ffmpeg 里没有 *_vaapi 解码器，VAAPI 解码是「-hwaccel vaapi +
        普通的 hevc/h264 解码器名」，解码器自己会把帧放到显存里。所以 vaapi 返回空，
        靠 decoder_args 里的 -hwaccel vaapi 生效。
        """
        if not spec.hw or not spec.hw_decoder_suffix:
            return ""
        if spec.hw_decoder_suffix == "_vaapi":
            return ""
        pref = HW_DECODER_PREFIX.get(str(self.vcodec or "").strip().lower(), "")
        if not pref:
            return ""
        return f"{pref}{spec.hw_decoder_suffix}"

    def _hw_scale_filter(self, spec: EncoderSpec) -> str:
        """拼硬件缩放滤镜：限制到 1920 宽、高度按原比例。

        scale_qsv / scale_vaapi 的 w/h 是字符串表达式（ffmpeg -h filter=scale_qsv：
        "w <string> (0=input width, -1=keep input aspect)"），所以可以写
        w=min(1920,iw):h=-1 —— 但**表达式里的逗号必须转义成 \,**，
        否则 ffmpeg 会把逗号当成滤镜链分隔符，报
        「No option name near '-1'」/「Error parsing a filterchain」，
        整条转码直接废掉，现场表现就是 ffmpeg 空转、GPU 一直 350MHz、不吐分片。
        注意这里不加引号：引号是给 shell 的，我们直接 exec 传参数，加了反而变成值的一部分。
        h=-1 表示保持输入宽高比（普通 scale 的 -2「对齐偶数」硬件滤镜不认）。
        """
        return f"{spec.hw_scale}=w=min(1920\\,iw):h=-1"

    def _run_ffmpeg_once(self, ffmpeg: str, copy: bool, override: str = "") -> tuple[int, str, str]:
        spec = self._encoder(override)
        cmd = [ffmpeg, "-y", "-v", "error", *spec.hwaccel, *spec.decoder_args]
        # 显式点名硬件解码器：只给 -hwaccel qsv 时解码器可能静默回落软解，
        # 那一路解码线程会吃满一个核（实测 dec0:0 73%），而编码已经在 GPU 上，
        # 用户看到的就是「GPU 不怎么动、CPU 却快 100%」。
        hw_dec = "" if copy else self._hw_decoder(spec)
        if hw_dec:
            cmd += ["-c:v", hw_dec]
        if self.start > 0:
            # 输入端 seek（在 -i 之前）走关键帧，秒级就绪；输出时间轴仍然从 0 起
            cmd += ["-ss", f"{self.start:.3f}"]
        cmd += ["-i", str(self.src)]
        if copy:
            cmd += ["-c", "copy"]
        else:
            # 硬件解码后帧留在显存里，缩放也要用硬件滤镜，否则会被下载回内存（等于白解）。
            # 注意只有「确实用上了硬件解码」才换成硬件滤镜：源编码没有对应硬解（如 mpeg4）
            # 时画帧在内存里，套 scale_qsv 会直接报错。
            # VAAPI 走的是 -hwaccel vaapi（没有独立的 *_vaapi 解码器，所以 hw_dec 为空），
            # 但帧同样在显存里，缩放和上传仍要用 VAAPI 滤镜链。
            use_hw_vf = bool(spec.hw_scale) and (bool(hw_dec) or spec.hw_decoder_suffix == "_vaapi")
            if use_hw_vf:
                # 硬件缩放滤镜不能用普通 scale 的表达式写法！
                #   scale_qsv=w=min(1920,iw):h=-2  →  "No option name near '-2'"，
                #                                    整条 filterchain 解析失败
                #   scale_qsv=w=1920:h=-1          →  w/h 必须是不带引号、不带 min() 的
                #                                    简单表达式，照普通 scale 那样写会
                #                                    「Error parsing a filter description」
                # 这两次踩坑的现场表现完全相同：ffmpeg 空转、GPU 一直 350MHz、不吐分片。
                # 所以这里先按源分辨率算好目标尺寸再拼字符串（见 _hw_scale_filter）。
                vf = self._hw_scale_filter(spec) + spec.vf_extra
            else:
                vf = "scale='min(1920,iw)':-2" + spec.vf_extra
            vargs = _vargs_for(spec.name)
            if spec.name == CPU_ENCODER:
                # CPU 编码沿用设置里的「转码预设」（ultrafast…slow）
                vargs = ("-preset", str(self.cfg.get("transcode_preset", "veryfast")),
                         "-crf", str(QUALITY))
            cmd += ["-c:v", spec.name, *vargs]
            if not spec.vf_extra and not hw_dec:
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
        # 记下来：服务退出（stop_all）时才能直接掐掉还在跑的 ffmpeg
        self.proc = proc
        # 转码卡死时（进程不退、也不出分片）只有日志能告诉我们 ffmpeg 在等什么，
        # 这是排查「GPU 没工作、CPU 却满」的唯一线索，所以把命令和 stderr 都落一条。
        print(f"[hls] video={self.video_id} start={self.start:g} enc={spec.name} "
              f"cmd={' '.join(cmd)}", flush=True)
        err_lines: list[str] = []

        def _drain() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                err_lines.append(line.rstrip())
                if len(err_lines) > 60:
                    del err_lines[0]

        th = threading.Thread(target=_drain, daemon=True)
        th.start()
        # 取消不能只靠「读 stdout 时顺便看一眼」：ffmpeg 卡在解码/IO 时可能很久不吐进度行，
        # 那条路就永远等不到 cancel。这里独立轮询，一旦取消先 TERM、3 秒不退就 KILL。
        cancel_watch = threading.Thread(target=self._watch_cancel, args=(proc,), daemon=True)
        cancel_watch.start()
        # 卡死看门狗：久不出分片就判定这个文件放不了，别让它在后台烧 CPU
        stall_watch = threading.Thread(target=self._watch_stall, args=(proc,), daemon=True)
        stall_watch.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_ms=") and self.duration > 0:
                    try:
                        sec = self.start + int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    self._progress(sec / self.duration, "转码中")
            proc.wait()
            # 被取消时 TERM 可能没生效（大文件 IO / 部分驱动），这里补一刀确保进程真的没了
            if self.cancel.is_set() and proc.poll() is None:
                self._kill_proc(proc)
        finally:
            # 无论怎么退出（异常/取消/正常结束）都要保证子进程已收、引用已清
            self._kill_proc(proc)
            th.join(timeout=2)
            cancel_watch.join(timeout=1)
            stall_watch.join(timeout=1)
            self.proc = None
        if err_lines:
            print(f"[hls] video={self.video_id} enc={spec.name} rc={proc.returncode} "
                  f"stderr={' | '.join(err_lines[-4:])}", flush=True)
        return proc.returncode, "\n".join(err_lines[-6:]), spec.name

    @staticmethod
    def _kill_proc(proc: subprocess.Popen) -> None:
        """先 TERM 再 KILL：ffmpeg 收 TERM 后偶发不退出，不补一刀就变成孤儿进程占满 CPU。"""
        try:
            if proc.poll() is not None:
                return
            proc.terminate()
            try:
                proc.wait(timeout=3)
                return
            except subprocess.TimeoutExpired:
                pass
            proc.kill()
            proc.wait(timeout=2)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    def _watch_cancel(self, proc: subprocess.Popen) -> None:
        while proc.poll() is None:
            if self.cancel.wait(0.3):
                self._kill_proc(proc)
                return

    def _watch_stall(self, proc: subprocess.Popen) -> None:
        """FIRST_SEGMENT_TIMEOUT 秒内连一个分片都没出 → 掐掉并标记 stalled。

        有的源会让 hevc_qsv 反复重建 MFX session（每几帧一次），GPU 完全用不上、
        CPU 却吃满，转码进度几乎为零。这种不值得再等，直接判「无法播放」。
        """
        deadline = time.time() + FIRST_SEGMENT_TIMEOUT
        while proc.poll() is None:
            if time.time() >= deadline:
                if not any(self.dir.glob("seg*.ts")):
                    self.stalled = True
                    print(f"[hls] video={self.video_id} 超过 {FIRST_SEGMENT_TIMEOUT:g} 秒"
                          f"没有产出分片，判定无法转码", flush=True)
                    self._kill_proc(proc)
                return
            time.sleep(0.5)


class HlsManager:
    """按需转码：同一视频只有一个后台转码任务；播放器轮询 m3u8 是否已出现。"""

    def __init__(self, tools: MediaTools, cfg: Config):
        self.tools = tools
        self.cfg = cfg
        self.jobs: dict[int, HlsJob] = {}
        self.lock = threading.Lock()

    def _job_limit(self) -> int:
        """同时跑几个转码任务（配置项 transcode_jobs，0/非法=不限，最小 1）。"""
        try:
            n = int(self.cfg.get("transcode_jobs", 2))
        except (TypeError, ValueError):
            n = 2
        return max(0, n)

    def _claim_slot(self, keep: HlsJob) -> bool:
        """给 keep 抢一个转码槽位；槽满时挤掉「最久没人请求」的另一个视频那一路。

        必须在同一把锁里「数 + 判 + 挤」：以前是先数完再在锁外杀进程，
        4 个请求同时进来时彼此都看到「还没满」，结果同时起了 4 个 ffmpeg，
        磁头/IO 全被打满（实测 3 路同时卡在 D 状态、CPU 0%、分片迟迟不出来）。
        返回 False 表示没抢到槽位，调用方别起任务。
        """
        limit = self._job_limit()
        stale: list[HlsJob] = []
        with self.lock:
            running = [j for j in self.jobs.values() if j.status == "running"]
            if limit <= 0 or len(running) <= limit:
                return True
            # 只挤别人的（同视频的多路已在 job_for 里处理过）
            others = [j for j in running if j.video_id != keep.video_id]
            overflow = len(running) - limit
            others.sort(key=lambda j: j.touched)
            for other in others[:overflow]:
                other.cancel.set()
                self.jobs.pop((other.video_id, int(other.start)), None)
                stale.append(other)
            got = len(running) - len(stale) <= limit
        # 杀进程在锁外做（别持锁打 IO），但槽位已经算清了
        for other in stale:
            proc = other.proc
            if proc is not None:
                HlsJob._kill_proc(proc)
        return got

    def job_for(self, video_id: int, src: Path, duration: float,
                vcodec: str, acodec: str, start: float = 0.0,
                src_w: int = 0, src_h: int = 0) -> HlsJob:
        key = (video_id, int(max(0.0, float(start or 0.0))))
        stale: list[HlsJob] = []
        with self.lock:
            job = self.jobs.get(key)
            if job is None or job.src != src:
                job = HlsJob(self.tools, self.cfg, video_id, src, duration, vcodec, acodec,
                             start=key[1], src_w=src_w, src_h=src_h)
                # 转码完成后的顺带清理要知道「谁还在跑」，否则可能把正在写的那一路删掉
                job.manager = self
                self.jobs[key] = job
                # 同一个视频换了起点：把其它「拖动出来」的转码任务停掉（一次拖动只留最新那一路）。
                # s0（整片那一路）分两种情况：
                #   · 还在起头、没吐出任何分片 → 用户已经跳到别处，它纯属白烧 CPU，收掉；
                #   · 已经 ready → 正片可能还在播它，掐了会直接黑屏，必须留着。
                # 以前是一律不动 s0，结果每次拖动都白留一个满负荷的 ffmpeg，
                # 实测同一视频同时跑 2 个进程、其中一个完全是在做无用功。
                if key[1] > 0:
                    for (vid, other_start), other in self.jobs.items():
                        if vid != video_id or other_start == key[1]:
                            continue
                        if other.status != "running":
                            continue
                        if other_start > 0:
                            other.cancel.set()
                            stale.append(other)
                        elif not other.ready:
                            # s0 还没被播到：可以直接收
                            other.cancel.set()
                            stale.append(other)
        # 光置 cancel 不够：ffmpeg 可能正卡在 IO 上，得把子进程直接收掉（在锁外做，别持锁打 IO）
        for other in stale:
            proc = other.proc
            if proc is not None:
                HlsJob._kill_proc(proc)
        return job

    def ensure(self, video_id: int, src: Path, duration: float,
               vcodec: str, acodec: str, start: float = 0.0,
               src_w: int = 0, src_h: int = 0) -> HlsJob:
        job = self.job_for(video_id, src, duration, vcodec, acodec, start,
                           src_w=src_w, src_h=src_h)
        job.touched = time.time()
        # 卡死判死的任务：别再自动重试，重试一次又要烧一份 CPU，
        # 直接让 /play 返回「该视频格式无法播放」。
        if job.stalled and job.status == "error":
            return job
        if job.status in {"done", "error"} and job.finished:
            return job
        if job.status == "running":
            return job
        # 起新任务前先抢一个槽位（顺手挤掉别人最久没看的那一路），免得 4 核机器被 N 个 ffmpeg 拖死
        job.status = "running"      # 先标 running 再抢槽，锁内计数才准
        if not self._claim_slot(job):
            job.status = "pending"  # 没抢到：先挂着，播放器下次请求再试
            return job
        t = threading.Thread(target=job.run, name=f"hls-{video_id}-{int(job.start)}", daemon=True)
        t.start()
        return job

    def job_for_video(self, video_id: int) -> HlsJob | None:
        """给状态接口用：优先全片任务（start=0），没有就返回任意一个。"""
        with self.lock:
            return self.jobs.get((video_id, 0)) or next(
                (j for (vid, _), j in self.jobs.items() if vid == video_id), None)

    def stop_all(self) -> None:
        """停止所有转码任务并杀掉它们的 ffmpeg（服务退出时调用）。

        以前这里什么都不做：应用停用后 ffmpeg 的父进程没了，子进程被 init 收养，
        继续按 100% CPU 跑下去（实测残留 4 个、跑了半小时）。所以退出时必须显式清理。
        """
        with self.lock:
            jobs = list(self.jobs.values())
            self.jobs.clear()
        for job in jobs:
            job.cancel.set()
            proc = job.proc
            if proc is not None:
                HlsJob._kill_proc(proc)

    def active_video_ids(self) -> set[int]:
        """正在转码的视频 id 集合（s0 与拖动产生的 sN 那一路都算）。

        转码缓存清理（`cache.sweep_hls`）靠它跳过「正在被写」的目录：
        jobs 的键是 `(video_id, start)` 双键，所以按第一项取集合。
        """
        with self.lock:
            return {int(k[0]) for k in self.jobs if isinstance(k, tuple) and k}

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
            jobs = [j for k, j in self.jobs.items() if k[0] == video_id]
            for key in [k for k in self.jobs if k[0] == video_id]:
                self.jobs.pop(key, None)
        # 删目录前先把这一部的 ffmpeg 停掉，不然它会把刚删掉的目录又写回来
        for job in jobs:
            job.cancel.set()
            if job.proc is not None:
                HlsJob._kill_proc(job.proc)
