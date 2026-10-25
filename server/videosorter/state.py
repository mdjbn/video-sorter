"""进程级共享状态：配置、数据库、认证、媒体工具、任务表、HLS 管理器。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .auth import AuthService
from .config import Config
from .db import Database
from .media import HlsManager, MediaTools
from .discovery import DiscoveryService
from .tasks import TaskRegistry


@dataclass
class AppState:
    cfg: Config
    db: Database
    auth: AuthService
    tools: MediaTools
    tasks: TaskRegistry
    hls: HlsManager
    discovery: DiscoveryService | None = None
    web_dir: Path | None = None

    @classmethod
    def create(cls, cfg: Config, web_dir: Path | None = None) -> "AppState":
        db = Database(cfg)
        auth = AuthService(db)
        tools = MediaTools(cfg)
        return cls(cfg=cfg, db=db, auth=auth, tools=tools,
                   tasks=TaskRegistry(), hls=HlsManager(tools, cfg), web_dir=web_dir)


STATE: AppState | None = None


def init(cfg: Config, web_dir: Path | None = None) -> AppState:
    global STATE
    STATE = AppState.create(cfg, web_dir)
    return STATE


def get_state() -> AppState:
    if STATE is None:
        raise RuntimeError("AppState 尚未初始化")
    return STATE
