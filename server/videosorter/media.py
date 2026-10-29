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
            attempts = [True, False] if self.copy_mode else [False]
            last_rc, last_err = 0, ""
            for copy in attempts:
                for f in self.dir.glob("seg*.ts"):
                    f.unlink(missing_ok=True)
                self.playlist.unlink(missing_ok=True)
                last_rc, last_err = self._run_ffmpeg(ffmpeg, copy)
                if last_rc == 0 and self.ready and self.playlist.stat().st_size > 0:
                    self.status = "done"
                    (self.dir / ".done").write_text(str(time.time()), encoding="utf-8")
                    self._progress(1.0, "转码完成")
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

    def _run_ffmpeg(self, ffmpeg: str, copy: bool) -> tuple[int, str]:
        rc, err = self._run_ffmpeg_once(ffmpeg, copy)
        if rc == self.LAUNCH_FAILED and not err.strip():
            time.sleep(0.3)
            rc, err = self._run_ffmpeg_once(ffmpeg, copy)
        return rc, err

    def _run_ffmpeg_once(self, ffmpeg: str, copy: bool) -> tuple[int, str]:
        cmd = [ffmpeg, "-y", "-v", "error"]
        if self.start > 0:
            # 输入端 seek（在 -i 之前）走关键帧，秒级就绪；输出时间轴仍然从 0 起
            cmd += ["-ss", f"{self.start:.3f}"]
        cmd += ["-i", str(self.src)]
        if copy:
            cmd += ["-c", "copy"]
        else:
            cmd += [
                "-c:v", "libx264", "-preset", str(self.cfg.get("transcode_preset", "veryfast")),
                "-crf", "23", "-pix_fmt", "yuv420p",
                "-vf", "scale='min(1920,iw)':-2",
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
            return 1, str(e)
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
        return proc.returncode, "\n".join(err_lines[-6:])


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
