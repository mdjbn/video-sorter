"""转码缓存（HLS 分片）的自动清理。

以前 `data/hls/` 只能靠缓存页手动「清除缓存」，看久了会无限涨：一部 1080p 片子
切出来通常 300~800 MB，NAS 上几块盘来回看，几个月就能吃掉几十 GB。这里给出一条
「有上限、会过期」的清理策略，由三处共用：

* `app.py` 的 lifespan：启动后延迟一次 + 之后定时（后台守护线程）；
* `POST /api/cache/sweep`：网页 / 安卓上点「立即清理超额缓存」；
* 转码任务跑完（`media.HlsJob.run` 收尾）。

规则（两步，先时间后容量）：

1. **按时间**：`<video_id>/` 目录里最新文件的 mtime 早于 `hls_cache_max_age_hours`
   的直接把整个目录删掉 —— 一星期没看过的片子，分片留着也只是占地方。
2. **按容量**：总量仍超过 `hls_cache_limit_mb` 时，把剩下的目录按「最近访问时间」
   （目录内最大 mtime）从旧到新删，直到降到上限以下。

两个配置项都为 0 时不做任何事（返回零值），这样想彻底关掉自动清理也没问题。

**正在转码的视频一律跳过**：ffmpeg 还在往里写 seg%05d.ts，删掉目录会让播放器
拿到半截 playlist；而且删除失败也是白忙。跳过的判定取自 `HlsManager.jobs`
（键是 `(video_id, start)` 双键，拖动进度条产生的 sN 那一路也算在内）以及
`HlsManager.active_video_ids()`。

所有 OSError 都吞掉：缓存目录本来就可能是「删到一半被 ffmpeg 重新创建」「权限
突然变了」「盘被拔了」，清理失败绝不能把调用方（定时线程 / 接口）带崩。
"""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .config import Config

# 定时清理的节奏：启动后先等一会儿再跑第一次（避开启动时的封面迁移/扫描抢 IO），
# 之后每小时跑一次。放在这里而不是 app.py，测试里可以直接引用。
SWEEP_START_DELAY = 90.0
SWEEP_INTERVAL = 3600.0

# 跳过「刚写入不久」的目录：ffmpeg 写分片时 mtime 一直在动，但刚写完最后一个分片
# 时 mtime 就是「现在」，留一点余量，免得把正在被播放器读的整片目录也清掉。
# 只在按容量清理里起作用（按时间清理已经天然有 hours 级别的余量）。
SWEEP_RECENT_GUARD = 60.0


def _dir_stats(d: Path) -> tuple[int, float]:
    """返回 (目录内所有文件总字节数, 目录内最新文件 mtime)。

    读不到的条目直接跳过（可能正在被删除）。空目录返回 (0, 目录自身 mtime)。
    """
    size = 0
    newest = 0.0
    try:
        for f in d.rglob("*"):
            try:
                stt = f.stat()
            except OSError:
                continue
            if f.is_dir():
                continue
            size += stt.st_size
            if stt.st_mtime > newest:
                newest = stt.st_mtime
    except OSError:
        pass
    if newest <= 0:
        try:
            newest = d.stat().st_mtime
        except OSError:
            newest = 0.0
    return size, newest


def _active_video_ids(hls_manager: Any) -> set[int]:
    """取 HlsManager 里所有「正在用」的 video_id（含 sN 拖动那一路）。

    jobs 的键是 `(video_id, start)`，所以按元组第一项取集合即可；不同起点要算成
    同一个视频。加锁读一份快照，别在锁里打 IO。
    """
    if hls_manager is None:
        return set()
    ids: set[int] = set()
    getter = getattr(hls_manager, "active_video_ids", None)
    if callable(getter):
        try:
            return {int(v) for v in getter()}
        except Exception:  # noqa: BLE001 - 拿不到活跃集合就别猜，退回直接用 jobs
            pass
    lock = getattr(hls_manager, "lock", None)
    jobs = getattr(hls_manager, "jobs", None)
    if jobs is None:
        return ids
    try:
        if lock is not None:
            with lock:
                keys = list(jobs.keys())
        else:
            keys = list(jobs.keys())
    except Exception:  # noqa: BLE001
        return ids
    for key in keys:
        vid = key[0] if isinstance(key, tuple) else key
        try:
            ids.add(int(vid))
        except (TypeError, ValueError):
            continue
    return ids


def _remove_dir(d: Path) -> int:
    """删掉一个缓存目录，返回释放的字节数；失败返回 0（不抛 OSError）。"""
    freed = 0
    try:
        for f in d.rglob("*"):
            try:
                if f.is_file():
                    freed += f.stat().st_size
            except OSError:
                continue
    except OSError:
        freed = 0
    try:
        shutil.rmtree(d)
    except OSError:
        # 被 ffmpeg 占用 / 权限问题：跳过，下一轮再说
        return 0
    except Exception:  # noqa: BLE001 - 极端情况下 Path 本身的怪错误也别抛
        return 0
    return freed


def sweep_hls(cfg: Config, hls_manager: Any = None,
              extra_active: Iterable[int] | None = None) -> dict[str, Any]:
    """清理 `cfg.hls_dir` 下的转码缓存，返回统计。永远不抛异常。"""
    try:
        limit_mb = int(cfg.get("hls_cache_limit_mb", 4096) or 0)
    except (TypeError, ValueError):
        limit_mb = 0
    try:
        age_hours = int(cfg.get("hls_cache_max_age_hours", 168) or 0)
    except (TypeError, ValueError):
        age_hours = 0
    limit_mb = max(0, limit_mb)
    age_hours = max(0, age_hours)

    result: dict[str, Any] = {
        "freed_bytes": 0, "removed_dirs": 0, "kept_dirs": 0,
        "limit_mb": limit_mb, "age_hours": age_hours,
    }
    # 两个都为 0 = 用户关掉了自动清理，什么都不做
    if limit_mb <= 0 and age_hours <= 0:
        return result

    root = Path(cfg.hls_dir)
    try:
        if not root.is_dir():
            return result
        entries = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return result

    active = _active_video_ids(hls_manager)
    for vid in extra_active or ():
        try:
            active.add(int(vid))
        except (TypeError, ValueError):
            continue

    now = time.time()
    age_seconds = age_hours * 3600.0
    freed = 0
    removed = 0
    kept: list[tuple[float, Path, int]] = []

    # ---------- 第一步：按时间清 ----------
    for d in entries:
        name = d.name
        try:
            vid = int(name)
        except ValueError:
            # 不是 <video_id>/ 形状的目录（比如调试时手工放的），不归这里管
            result["kept_dirs"] += 1
            continue
        size, newest = _dir_stats(d)
        if vid in active:
            kept.append((newest, d, size))
            continue
        if age_hours > 0 and newest > 0 and (now - newest) > age_seconds:
            got = _remove_dir(d)
            if got > 0 or not d.exists():
                freed += got
                removed += 1
                continue
            # 删不掉（多半是还在写）：当作保留
            kept.append((newest, d, size))
            continue
        kept.append((newest, d, size))

    # ---------- 第二步：按容量清 ----------
    if limit_mb > 0:
        limit_bytes = limit_mb * 1024 * 1024
        total = sum(size for _, _, size in kept)
        if total > limit_bytes:
            # 最久没被访问的（目录内最大 mtime 最小）先删
            for newest, d, size in sorted(kept, key=lambda x: x[0]):
                if total <= limit_bytes:
                    break
                # 正在转码的这一路（s0 或拖动的 sN）一律不动：删了播放器会拿到半截 playlist，
                # 而且 ffmpeg 立刻又把目录写回来，白删一次还会让本轮容量算错
                try:
                    if int(d.name) in active:
                        continue
                except ValueError:
                    continue
                # 刚写完的那一份留着，别和正在进行的转码抢
                if newest > 0 and (now - newest) < SWEEP_RECENT_GUARD:
                    continue
                got = _remove_dir(d)
                if got <= 0 and d.exists():
                    continue
                freed += got
                removed += 1
                total -= got if got > 0 else size
                kept = [k for k in kept if k[1] != d]

    result["freed_bytes"] = freed
    result["removed_dirs"] = removed
    result["kept_dirs"] = len(kept)
    return result


# ---------------------------------------------------------------------------
# 后台定时清理（app.py 的 lifespan 用）
# ---------------------------------------------------------------------------

class HlsSweeper:
    """启动后延迟跑一次、之后按间隔重复的守护线程；stop() 能立刻把它唤醒退出。

    写法对齐 `DiscoveryService`：一个 threading.Event 做「可退出的等待」，
    退出路径上只 set + join（**不 join 无限期**），绝不把进程卡住。
    """

    def __init__(self, cfg: Config, hls_manager: Any = None,
                 start_delay: float = SWEEP_START_DELAY,
                 interval: float = SWEEP_INTERVAL):
        self.cfg = cfg
        self.hls_manager = hls_manager
        self.start_delay = max(0.0, float(start_delay))
        self.interval = max(60.0, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last: dict[str, Any] | None = None

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vs-hls-sweep", daemon=True)
        self._thread.start()
        return True

    def run_once(self) -> dict[str, Any]:
        """同步跑一次并记下结果（异常一律吞掉，定时线程不能死）。"""
        try:
            self.last = sweep_hls(self.cfg, self.hls_manager)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 转码缓存清理失败：{e}")
            self.last = None
        return self.last or {}

    def _loop(self) -> None:
        # 第一次先等 start_delay：启动时还有封面规则迁移、目录登记在跑，别去抢 IO
        if self._stop.wait(self.start_delay):
            return
        while not self._stop.is_set():
            res = self.run_once()
            if res.get("removed_dirs"):
                print(f"[cache] 清理转码缓存：删了 {res['removed_dirs']} 个目录，"
                      f"释放 {res['freed_bytes']} 字节", flush=True)
            if self._stop.wait(self.interval):
                return

    def stop(self, timeout: float = 3.0) -> None:
        """叫停后台线程：set 事件立刻唤醒 wait，join 一个短超时就行。"""
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout)
        self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())
