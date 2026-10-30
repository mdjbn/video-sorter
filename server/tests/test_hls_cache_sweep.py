"""转码缓存（HLS 分片）自动清理：策略、接口、设置夹取。

造目录的方式和 HlsJob 的真实布局一致：`<hls_dir>/<video_id>/seg%05d.ts`，
拖动进度条产生的 sN 那一路是 `<hls_dir>/<video_id>/s<秒>/seg%05d.ts`。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from videosorter.cache import HlsSweeper, sweep_hls
from videosorter.config import Config

HOUR = 3600.0


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    c = Config(tmp_path / "data")
    # 每个用例自己设上下限，避免被别的测试/环境变量带偏
    c.update({"hls_cache_limit_mb": 0, "hls_cache_max_age_hours": 0})
    return c


def make_cache_dir(cfg: Config, video_id: int, nbytes: int,
                   age_seconds: float = 0.0, parts: int = 2) -> Path:
    """造一个 `<hls_dir>/<video_id>/` 目录：parts 个文件，总共 nbytes 字节。

    age_seconds 是「最近访问距今多少秒」——写完之后用 os.utime 把 mtime 往回拨。
    """
    d = cfg.hls_dir / str(video_id)
    d.mkdir(parents=True, exist_ok=True)
    per = max(1, nbytes // parts)
    for i in range(parts):
        f = d / f"seg{i:05d}.ts"
        f.write_bytes(b"\0" * per)
        if age_seconds:
            ts = time.time() - age_seconds
            os.utime(f, (ts, ts))
    (d / "index.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    if age_seconds:
        ts = time.time() - age_seconds
        os.utime(d / "index.m3u8", (ts, ts))
        os.utime(d, (ts, ts))
    return d


class FakeManager:
    """假 HlsManager：只要有 jobs 字典 + lock，sweep_hls 就该跳过这些 video_id。"""

    def __init__(self, keys: list[tuple[int, int]]):
        self.jobs = {k: object() for k in keys}
        self.lock = threading.Lock()


# ---------------------------------------------------------------------------
# 策略
# ---------------------------------------------------------------------------

def test_expired_dirs_removed_by_age(cfg):
    cfg.update({"hls_cache_max_age_hours": 24, "hls_cache_limit_mb": 0})
    old = make_cache_dir(cfg, 1, 4096, age_seconds=48 * HOUR)
    fresh = make_cache_dir(cfg, 2, 4096, age_seconds=1 * HOUR)

    res = sweep_hls(cfg)

    assert not old.exists(), "超过保留期的目录应该整个删掉"
    assert fresh.exists(), "没到期的目录不能删"
    assert res["removed_dirs"] == 1
    assert res["kept_dirs"] == 1
    assert res["freed_bytes"] >= 4096
    assert res["age_hours"] == 24 and res["limit_mb"] == 0


def test_limit_removes_oldest_first(cfg):
    cfg.update({"hls_cache_limit_mb": 1, "hls_cache_max_age_hours": 0})
    # 三个 600 KB ≈ 1.8 MB，上限 1 MB → 至少要删掉最旧的两个之一，删到 1 MB 以下
    oldest = make_cache_dir(cfg, 1, 600 * 1024, age_seconds=3000)
    middle = make_cache_dir(cfg, 2, 600 * 1024, age_seconds=2000)
    newest = make_cache_dir(cfg, 3, 600 * 1024, age_seconds=1000)

    res = sweep_hls(cfg)

    assert not oldest.exists(), "最久没访问的应该先被删"
    assert newest.exists(), "最新的那个必须留着"
    assert not (oldest.exists() and middle.exists() and newest.exists())
    total_left = sum(
        f.stat().st_size for d in cfg.hls_dir.iterdir() if d.is_dir()
        for f in d.rglob("*") if f.is_file())
    assert total_left <= 1024 * 1024, "清完必须降到上限以下"
    assert res["removed_dirs"] >= 1
    assert res["limit_mb"] == 1


def test_active_jobs_are_skipped(cfg):
    """正在转码的视频（s0 与拖动的 sN 都算）一律不删，哪怕已经过期。"""
    cfg.update({"hls_cache_max_age_hours": 1, "hls_cache_limit_mb": 0})
    active = make_cache_dir(cfg, 7, 4096, age_seconds=100 * HOUR)
    # 同一视频的「拖动那一路」也在转码：s120 子目录
    sub = active / "s120"
    sub.mkdir()
    (sub / "seg00000.ts").write_bytes(b"\0" * 1024)
    idle = make_cache_dir(cfg, 8, 4096, age_seconds=100 * HOUR)
    mgr = FakeManager([(7, 0), (7, 120)])

    res = sweep_hls(cfg, mgr)

    assert active.exists() and sub.exists(), "正在转码的目录不能删"
    assert not idle.exists()
    assert res["removed_dirs"] == 1 and res["kept_dirs"] == 1


def test_active_skipped_even_over_limit(cfg):
    cfg.update({"hls_cache_limit_mb": 1, "hls_cache_max_age_hours": 0})
    watched = make_cache_dir(cfg, 5, 900 * 1024, age_seconds=5000)   # 最旧但在播
    other = make_cache_dir(cfg, 6, 900 * 1024, age_seconds=4000)

    sweep_hls(cfg, FakeManager([(5, 0)]))

    assert watched.exists(), "占容量最久但正在被播的那一路不能删"
    assert not other.exists()


def test_disabled_when_both_zero(cfg):
    cfg.update({"hls_cache_limit_mb": 0, "hls_cache_max_age_hours": 0})
    a = make_cache_dir(cfg, 1, 8192, age_seconds=1000 * HOUR)
    b = make_cache_dir(cfg, 2, 8192, age_seconds=1000 * HOUR)

    res = sweep_hls(cfg)

    assert a.exists() and b.exists(), "limit 与 age 都为 0 时什么都不做"
    assert res == {"freed_bytes": 0, "removed_dirs": 0, "kept_dirs": 0,
                   "limit_mb": 0, "age_hours": 0}


def test_result_shape(cfg):
    cfg.update({"hls_cache_limit_mb": 4096, "hls_cache_max_age_hours": 168})
    make_cache_dir(cfg, 1, 1024, age_seconds=10)
    res = sweep_hls(cfg)
    assert set(res) == {"freed_bytes", "removed_dirs", "kept_dirs", "limit_mb", "age_hours"}
    assert all(isinstance(res[k], int) for k in res)
    assert res["limit_mb"] == 4096 and res["age_hours"] == 168
    assert res["kept_dirs"] == 1 and res["removed_dirs"] == 0


def test_ignores_non_video_dirs_and_never_raises(cfg):
    cfg.update({"hls_cache_max_age_hours": 1, "hls_cache_limit_mb": 0})
    stray = cfg.hls_dir / "tmp-stuff"       # 不是 <video_id>/ 形状：不归它管
    stray.mkdir()
    (stray / "x.ts").write_bytes(b"\0" * 16)
    old = make_cache_dir(cfg, 3, 16, age_seconds=100 * HOUR)

    res = sweep_hls(cfg)

    assert stray.exists(), "非 <video_id>/ 目录不该被删"
    assert not old.exists()
    assert res["removed_dirs"] == 1


def test_missing_hls_dir_is_ok(tmp_path):
    c = Config(tmp_path / "empty")
    c.update({"hls_cache_limit_mb": 10, "hls_cache_max_age_hours": 10})
    res = sweep_hls(c)
    assert res["removed_dirs"] == 0 and res["freed_bytes"] == 0


# ---------------------------------------------------------------------------
# 后台线程：能立刻停掉
# ---------------------------------------------------------------------------

def test_sweeper_stops_promptly(cfg):
    sweeper = HlsSweeper(cfg, None, start_delay=600.0, interval=3600.0)
    made = make_cache_dir(cfg, 1, 16)
    cfg.update({"hls_cache_max_age_hours": 1})
    ts = time.time() - 100 * HOUR
    for f in made.rglob("*"):
        os.utime(f, (ts, ts))
    sweeper.start()
    t0 = time.time()
    sweeper.stop(timeout=5.0)
    assert time.time() - t0 < 3.0, "stop() 必须立刻退出，不能等满 600 秒"
    assert not sweeper.running
    # 手动 run_once 仍然可用
    res = sweeper.run_once()
    assert res["removed_dirs"] == 1


# ---------------------------------------------------------------------------
# 接口：GET /api/cache 的新字段 + POST /api/cache/sweep
# ---------------------------------------------------------------------------

def _login(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin1234",
                                             "remember": True})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _age_dir(d: Path, seconds: float) -> None:
    ts = time.time() - seconds
    for f in d.rglob("*"):
        os.utime(f, (ts, ts))
    os.utime(d, (ts, ts))


def test_cache_info_exposes_sweep_settings(env):
    client = env["client"]
    h = _login(client)
    cfg = env["cfg"]
    cfg.update({"hls_cache_limit_mb": 2048, "hls_cache_max_age_hours": 72})

    info = client.get("/api/cache", headers=h).json()

    assert info["hls_limit_mb"] == 2048
    assert info["hls_max_age_hours"] == 72
    assert "hls_used_bytes" in info and info["hls_used_bytes"] == info["hls"]["bytes"]
    # 原有字段一个都不能少
    assert set(info) >= {"thumbs", "hls", "total_bytes", "data_dir", "thumb_dir", "hls_dir"}


def test_post_sweep_removes_expired(env):
    client = env["client"]
    h = _login(client)
    cfg = env["cfg"]
    cfg.update({"hls_cache_limit_mb": 0, "hls_cache_max_age_hours": 1})

    expired = cfg.hls_dir / "101"
    expired.mkdir(parents=True, exist_ok=True)
    (expired / "seg00000.ts").write_bytes(b"\0" * 2048)
    _age_dir(expired, 48 * HOUR)
    fresh = cfg.hls_dir / "102"
    fresh.mkdir(parents=True, exist_ok=True)
    (fresh / "seg00000.ts").write_bytes(b"\0" * 2048)

    r = client.post("/api/cache/sweep", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["removed_dirs"] == 1
    assert body["limit_mb"] == 0 and body["age_hours"] == 1
    assert body["freed_bytes"] >= 2048
    assert body["hls_used_bytes"] == body["hls"]["bytes"]
    assert not expired.exists() and fresh.exists()

    # 没登录不能清（登录时带了 remember，cookie 也生效，所以用一个干净的 client 验）
    from fastapi.testclient import TestClient
    with TestClient(env["app"]) as anon:
        assert anon.post("/api/cache/sweep").status_code == 401


# ---------------------------------------------------------------------------
# 设置夹取
# ---------------------------------------------------------------------------

def test_settings_clamps_cache_limits(env):
    client = env["client"]
    h = _login(client)

    r = client.put("/api/settings", json={"hls_cache_limit_mb": 99999999,
                                          "hls_cache_max_age_hours": 999999}, headers=h)
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["hls_cache_limit_mb"] == 1048576, "上限夹到 1048576 MB"
    assert s["hls_cache_max_age_hours"] == 8760, "上限夹到 8760 小时"

    r = client.put("/api/settings", json={"hls_cache_limit_mb": -5,
                                          "hls_cache_max_age_hours": -99}, headers=h)
    s = r.json()["settings"]
    assert s["hls_cache_limit_mb"] == 0, "负数夹到 0（=关闭该维度）"
    assert s["hls_cache_max_age_hours"] == 0

    # 正常值原样存下
    r = client.put("/api/settings", json={"hls_cache_limit_mb": 2048,
                                          "hls_cache_max_age_hours": 336}, headers=h)
    s = r.json()["settings"]
    assert s["hls_cache_limit_mb"] == 2048 and s["hls_cache_max_age_hours"] == 336
    assert client.get("/api/cache", headers=h).json()["hls_limit_mb"] == 2048


def test_defaults_present():
    from videosorter.config import DEFAULTS
    assert DEFAULTS["hls_cache_limit_mb"] == 4096
    assert DEFAULTS["hls_cache_max_age_hours"] == 168
