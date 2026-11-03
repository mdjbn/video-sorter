"""扫描用的全局线程池。

以前每次扫描各自 `ThreadPoolExecutor(max_workers=scan_workers)`：一次全量扫描
自己开 3 个线程跑 ffprobe。两个扫描并发（网页端一次、手机端一次）就变成 6 个
ffprobe 同时跑——机械盘上扫描会明显变慢，而且每个 ffprobe 都是独立进程，峰值
内存也跟着翻倍。

改成进程内共享一个池：`scan_workers` 变成**全局上限**，不管同时有几个扫描，
ffprobe 的并发数都不会超过它。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

__all__ = ["scan_pool", "reset_scan_pool"]

_POOL: ThreadPoolExecutor | None = None
_POOL_SIZE: int = 0
_LOCK = threading.Lock()


def scan_pool(max_workers: int) -> ThreadPoolExecutor:
    """拿到全局扫描线程池；第一次调用时按 `max_workers` 创建。

    之后即使配置改了也不重建——重建会丢掉正在跑的任务。要换大小得重启进程
    （`scan_workers` 本来就只在启动时读）。
    """
    global _POOL, _POOL_SIZE
    size = max(1, int(max_workers or 1))
    with _LOCK:
        if _POOL is None:
            _POOL = ThreadPoolExecutor(max_workers=size, thread_name_prefix="scan")
            _POOL_SIZE = size
        return _POOL


def reset_scan_pool() -> None:
    """关掉全局池并清空（单测用；进程退出时也会被解释器收走）。"""
    global _POOL, _POOL_SIZE
    with _LOCK:
        if _POOL is not None:
            _POOL.shutdown(wait=False)
        _POOL = None
        _POOL_SIZE = 0
