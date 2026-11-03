"""扫描任务队列：任务之间串行，任务内部目录并行。

为什么任务要串行：
  扫描是**写库**的操作（入库、改状态、生成封面、标 missing）。两个扫描并发时
  实测会出现 `IntegrityError: UNIQUE constraint failed: videos.path`——`_upsert`
  是「先查快照、再插入」，两轮扫描都看不到对方刚插入的文件，于是都 INSERT，撞
  `videos.path` 的 UNIQUE 约束，整轮扫描直接失败（3 个并发全量扫描，2 个报错）。
  串行之后同一时刻只有一个扫描在写，这类竞态从根上消失。

为什么任务内部不串行：
  一次「扫描全部」可能覆盖十几个目录，每个目录都要 ffprobe 一遍。如果按目录
  排队串行跑，用户得干等好几分钟。目录之间本来是独立的，并行跑才合理——并发度
  由 `concurrency.scan_pool()` 这个全局池控制，不会因为任务变多而翻倍。

合并规则（队列里已有同样的事就不必再排一次）：
  - 签名完全相同（源目录集合、标签集合、是否全量都一样）→ 复用那个任务，不重复入队；
  - 全量扫描（既没指定源目录也没指定标签）→ 只要队列里已经有一个全量在等，新的就合并进去；
  - 其余（比如先扫标签 A、再扫标签 B）签名不同，各排各的，都会跑。
"""

from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from . import tasks as tasks_mod

__all__ = ["ScanQueue", "signature"]


def signature(source_ids: list[int] | None, tag_ids: list[int] | None) -> tuple:
    """任务的「同一件事」判定依据（全量与否由两个列表都为空表示）。"""
    return (tuple(sorted(source_ids or [])), tuple(sorted(tag_ids or [])))


class ScanQueue:
    def __init__(self, registry: tasks_mod.TaskRegistry):
        self._reg = registry
        self._lock = threading.RLock()
        self._pending: list[dict[str, Any]] = []   # 待执行：[{tid, sig, fn, extra}]
        self._running_tid: str | None = None
        self._worker: threading.Thread | None = None

    # ---------- 对外 ----------
    def submit(self, *, label: str, fn: Callable[[str], Any], source_ids: list[int] | None = None,
               tag_ids: list[int] | None = None, **extra: Any) -> dict[str, Any]:
        """入队一个扫描。返回 {task_id, queued, position, merged}。

        merged=True 表示队列里已有同一件事，直接把那个任务交给前端等。
        """
        sig = signature(source_ids, tag_ids)
        with self._lock:
            # ① 队列里有同一件事 → 复用（前端拿到的 task_id 是那个已在排队的）
            for item in self._pending:
                if item["sig"] == sig:
                    return {"task_id": item["tid"], "queued": True,
                            "position": self._position(item["tid"]), "merged": True}
            tid = self._reg.create("scan", label=label, **extra)
            self._reg.update(tid, status="queued", message="排队中…")
            self._pending.append({"tid": tid, "sig": sig, "fn": fn,
                                  "source_ids": list(source_ids or []),
                                  "tag_ids": list(tag_ids or [])})
            position = self._position(tid)
            self._pump()
            return {"task_id": tid, "queued": True, "position": position, "merged": False}

    def cancel(self, task_id: str) -> bool:
        """取消任务：还在排队的直接从队列摘掉，已开跑的交给 TaskRegistry 走取消标志。"""
        with self._lock:
            for idx, item in enumerate(self._pending):
                if item["tid"] == task_id:
                    self._pending.pop(idx)
                    self._reg.finish(task_id, result=None, message="已取消（未开始）",
                                     status="cancelled")
                    return True
        self._reg.cancel(task_id)
        return True

    def pending(self) -> list[dict[str, Any]]:
        """排队快照（给接口展示「还有几个在等」）。"""
        with self._lock:
            out = []
            for i in self._pending:
                t = self._reg.get(i["tid"]) or {}
                out.append({
                    "task_id": i["tid"],
                    "position": self._position(i["tid"]),
                    "label": t.get("label") or "扫描",
                    "source_ids": list(i.get("source_ids") or []),
                    "tag_ids": list(i.get("tag_ids") or []),
                    "created_at": t.get("started_at") or "",
                })
            return out

    def running_task_id(self) -> str | None:
        with self._lock:
            return self._running_tid

    # ---------- 内部 ----------
    def _position(self, task_id: str) -> int:
        """还有几个任务在它前面（1 表示下一个就跑）。"""
        for idx, item in enumerate(self._pending):
            if item["tid"] == task_id:
                return idx + 1
        return 0

    def _pump(self) -> None:
        """有活且没有消费线程 → 起一个。消费线程只在队列空时退出。"""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            if not self._pending:
                return
            self._worker = threading.Thread(target=self._run, name="scan-queue", daemon=True)
            self._worker.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._worker = None
                    self._running_tid = None
                    return
                item = self._pending.pop(0)
                self._running_tid = item["tid"]
            tid = item["tid"]
            if self._reg.is_cancelled(tid):
                self._reg.finish(tid, result=None, message="已取消（未开始）", status="cancelled")
                continue
            self._reg.update(tid, status="running", message="正在扫描…")
            try:
                result = item["fn"](tid)
                with self._reg.lock:
                    t = self._reg.tasks.get(tid)
                    if t and t["status"] == "running":
                        status, message = "done", ""
                        if isinstance(result, dict):
                            status = str(result.get("task_status") or "done")
                            message = str(result.get("message") or "")
                        self._reg.finish(tid, result=result, message=message, status=status)
            except Exception as e:  # noqa: BLE001 — 队列线程必须兜住所有异常，否则整条队列卡死
                traceback.print_exc()
                self._reg.fail(tid, f"{type(e).__name__}: {e}")
