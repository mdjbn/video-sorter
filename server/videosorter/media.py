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


def probe(tools: MediaTools, path: Path) -> dict[str, Any]:
    """用 ffprobe 读元数据。失败时返回尽可能多的默认值，不抛异常。"""
    ffmpeg, ffprobe = tools.require()
    cmd = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        data = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
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
        r = subprocess.run(cmd, capture_output=True, timeout=90, check=False)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return True
        # 取首帧兜底
        cmd[4] = "0"
        r = subprocess.run(cmd, capture_output=True, timeout=90, check=False)
        return r.returncode == 0 and out.exists() and out.stat().st_size > 0
    except (subprocess.SubprocessError, OSError):
        return False


class HlsJob:
    """把一个视频切成 HLS。h264+aac 直接 -c copy（秒级），其余转码。"""

    def __init__(self, tools: MediaTools, cfg: Config, video_id: int, src: Path,
                 duration: float, vcodec: str, acodec: str,
                 on_progress: Callable[[float, str], None] | None = None):
        self.tools = tools
        self.cfg = cfg
        self.video_id = video_id
        self.src = src
        self.duration = duration
        self.on_progress = on_progress
        self.lock = threading.Lock()
        self.status = "pending"     # pending | running | done | error
        self.error = ""
        self.dir = cfg.hls_dir / str(video_id)
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
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(self.src)]
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
            line = line.strip()
            if line.startswith("out_time_ms=") and self.duration > 0:
                try:
                    sec = int(line.split("=", 1)[1]) / 1_000_000
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
                vcodec: str, acodec: str) -> HlsJob:
        with self.lock:
            job = self.jobs.get(video_id)
            if job is None or job.src != src:
                job = HlsJob(self.tools, self.cfg, video_id, src, duration, vcodec, acodec)
                self.jobs[video_id] = job
            return job

    def ensure(self, video_id: int, src: Path, duration: float,
               vcodec: str, acodec: str) -> HlsJob:
        job = self.job_for(video_id, src, duration, vcodec, acodec)
        if job.status in {"done", "error"} and job.finished:
            return job
        if job.status == "running":
            return job
        t = threading.Thread(target=job.run, name=f"hls-{video_id}", daemon=True)
        job.status = "running"
        t.start()
        return job

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
            self.jobs.pop(video_id, None)
