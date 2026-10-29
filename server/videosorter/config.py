"""配置与路径：跨平台（Linux / Windows / macOS）。

数据目录（数据库、缩略图、转码缓存、日志）与安装目录分离，
这样 Windows 上装在 Program Files 也不会因为 UAC 写不进去。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import APP_NAME, __version__

DEFAULTS: dict[str, Any] = {
    "port": 8080,
    "host": "0.0.0.0",          # 局域网内手机也要能连；只本机用可改成 127.0.0.1
    "root_dir": "",             # 整理后的根目录，空=沿用"源目录/标签名"
    "allow_lan": True,
    "theme": "auto",
    "transcode": True,          # 允许按需 HLS 转码
    "transcode_encoder": "auto",  # auto=显卡优先（NVENC/QSV/AMF/VideoToolbox），也可指定 libx264
    "transcode_preset": "veryfast",
    "thumb_position": 0.0,      # 0 = 取视频第一帧作为封面
    "scan_workers": 3,
    "upload_dir": "",           # 手机上传落盘目录，空=整理根目录/手机上传（或第一个源目录/手机上传）
    "discovery": True,          # 局域网 UDP 发现（手机 App 自动找服务器）
    "discovery_port": 38080,
}


def default_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "video-sorter"


class Config:
    def __init__(self, data_dir: Path | str | None = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.data_dir / "config.json"
        self.values: dict[str, Any] = dict(DEFAULTS)
        self.load()

    # ---------- 基本读写 ----------
    def load(self) -> None:
        if self.file.exists():
            try:
                data = json.loads(self.file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k in DEFAULTS:
                        if k in data and data[k] is not None:
                            self.values[k] = data[k]
                    # 旧默认值是 0.15（15% 处截帧），现已改为「第一帧」，老配置自动迁移
                    if self.values.get("thumb_position") == 0.15:
                        self.values["thumb_position"] = 0.0
            except (json.JSONDecodeError, OSError):
                pass
        self._apply_env()

    def _apply_env(self) -> None:
        """用 VIDEOSORTER_<KEY> 环境变量覆盖配置（fnOS/systemd/CI 等场景）。

        只影响本次进程，不会被 save() 写回 config.json；空字符串视为「未设置」。
        """
        for key, default in DEFAULTS.items():
            raw = os.environ.get(f"VIDEOSORTER_{key.upper()}")
            if raw is None or raw.strip() == "":
                continue
            try:
                if isinstance(default, bool):
                    self.values[key] = raw.strip().lower() in ("1", "true", "yes", "on")
                elif isinstance(default, int):
                    self.values[key] = int(raw)
                elif isinstance(default, float):
                    self.values[key] = float(raw)
                else:
                    self.values[key] = raw
            except ValueError:
                pass

    def save(self) -> None:
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.file)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> Any:
        if key in DEFAULTS:
            self.values[key] = value
            self.save()
        return self.values.get(key)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        for k, v in patch.items():
            if k in DEFAULTS:
                self.values[k] = v
        self.save()
        return self.values

    # ---------- 派生路径 ----------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "data.sqlite3"

    @property
    def thumb_dir(self) -> Path:
        d = self.data_dir / "thumbs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def hls_dir(self) -> Path:
        d = self.data_dir / "hls"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def log_dir(self) -> Path:
        d = self.data_dir / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def version(self) -> str:
        return __version__
