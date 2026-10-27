"""SQLite 存储层。单文件数据库，WAL 模式，适合单人使用。

连接策略：每次操作取一条新连接（SQLite 开销极小），避免多线程共享句柄。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  username   TEXT UNIQUE NOT NULL,
  pass_hash  TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
  token        TEXT PRIMARY KEY,
  user_id      INTEGER NOT NULL,
  created_at   TEXT NOT NULL,
  last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS sources (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  path         TEXT UNIQUE NOT NULL,
  enabled      INTEGER NOT NULL DEFAULT 1,
  kind         TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL,
  last_scan_at TEXT
);

CREATE TABLE IF NOT EXISTS tags (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT UNIQUE NOT NULL,
  color      TEXT NOT NULL,
  dir_path   TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  path         TEXT UNIQUE NOT NULL,
  filename     TEXT NOT NULL,
  ext          TEXT NOT NULL DEFAULT '',
  size         INTEGER NOT NULL DEFAULT 0,
  duration     REAL NOT NULL DEFAULT 0,
  width        INTEGER NOT NULL DEFAULT 0,
  height       INTEGER NOT NULL DEFAULT 0,
  vcodec       TEXT NOT NULL DEFAULT '',
  acodec       TEXT NOT NULL DEFAULT '',
  bitrate      INTEGER NOT NULL DEFAULT 0,
  thumb        TEXT NOT NULL DEFAULT '',
  tag_id       INTEGER REFERENCES tags(id) ON DELETE SET NULL,
  status       TEXT NOT NULL DEFAULT 'idle',      -- idle | tagged | organized | missing
  direct_play  INTEGER NOT NULL DEFAULT 1,        -- 是否可直连播放（否则按需转码）
  mtime        REAL NOT NULL DEFAULT 0,
  scanned_at   TEXT NOT NULL,
  organized_at TEXT,
  added_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_tag    ON videos(tag_id);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_path   ON videos(path);

CREATE TABLE IF NOT EXISTS organize_batches (
  id         TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  undone     INTEGER NOT NULL DEFAULT 0,
  note       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS organize_logs (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id  TEXT NOT NULL,
  video_id  INTEGER NOT NULL,
  tag_id    INTEGER,
  from_path TEXT NOT NULL,
  to_path   TEXT NOT NULL,
  moved_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_batch ON organize_logs(batch_id);

CREATE TABLE IF NOT EXISTS play_history (
  video_id   INTEGER PRIMARY KEY,
  position   REAL NOT NULL DEFAULT 0,
  duration   REAL NOT NULL DEFAULT 0,
  watched_at TEXT NOT NULL,
  filename   TEXT NOT NULL DEFAULT '',
  deleted    INTEGER NOT NULL DEFAULT 0
);
"""

DEFAULT_TAGS = [
    ("旅行", "#f4a259"),
    ("美食", "#ef5b7b"),
    ("运动", "#4cc9f0"),
    ("学习", "#9b8cff"),
    ("待整理", "#8d98a8"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.path = cfg.db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ---------- 连接 ----------
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- 便捷查询 ----------
    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self.tx() as c:
            return list(c.execute(sql, params))

    def query_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        with self.tx() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid or cur.rowcount

    # ---------- 初始化 ----------
    def _init_schema(self) -> None:
        with self.tx() as c:
            c.executescript(SCHEMA)
            # 老库升级：play_history 补 filename / deleted（视频被删后播放记录仍要保留并标注「已删除」）
            cols = {r["name"] for r in c.execute("PRAGMA table_info(play_history)").fetchall()}
            if "filename" not in cols:
                c.execute("ALTER TABLE play_history ADD COLUMN filename TEXT NOT NULL DEFAULT ''")
            if "deleted" not in cols:
                c.execute("ALTER TABLE play_history ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
            scols = {r["name"] for r in c.execute("PRAGMA table_info(sources)").fetchall()}
            if "kind" not in scols:
                c.execute("ALTER TABLE sources ADD COLUMN kind TEXT NOT NULL DEFAULT ''")
            row = c.execute("SELECT COUNT(*) AS n FROM tags").fetchone()
            if row and row["n"] == 0:
                for i, (name, color) in enumerate(DEFAULT_TAGS):
                    c.execute(
                        "INSERT INTO tags (name, color, dir_path, sort_order, created_at) VALUES (?,?,?,?,?)",
                        (name, color, "", i, now_iso()),
                    )

    # ---------- settings ----------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.query_one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
