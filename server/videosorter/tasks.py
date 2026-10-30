"""后台任务进度登记表。

扫描、整理、转码这类耗时操作放到后台线程执行，前端轮询 /api/tasks/{id}
拿进度。任务只在内存里，进程重启即失效（数据库里另有持久结果）。
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class TaskRegistry:
    def __init__(self, keep: int = 50):
        self.tasks: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.keep = keep
        self.lock = threading.RLock()

    def create(self, kind: str, **extra: Any) -> str:
        tid = uuid.uuid4().hex[:12]
        with self.lock:
            self.tasks[tid] = {
                "id": tid,
                "kind": kind,
                "status": "running",       # running | done | error | cancelled
                "total": 0,
                "done": 0,
                "percent": 0.0,
                "message": "",
                "result": None,
                "error": "",
                "started_at": _now(),
                "finished_at": None,
                "cancelled": False,
                **extra,
            }
            self.order.append(tid)
            while len(self.order) > self.keep:
                old = self.order.pop(0)
                self.tasks.pop(old, None)
        return tid

    def update(self, tid: str, **fields: Any) -> None:
        with self.lock:
            t = self.tasks.get(tid)
            if not t:
                return
            t.update(fields)
            total, done = t.get("total") or 0, t.get("done") or 0
            if total:
                t["percent"] = round(min(1.0, done / total) * 100, 1)

    def set_total(self, tid: str, total: int) -> None:
        self.update(tid, total=total, done=0, percent=0.0)

    def step(self, tid: str, message: str = "", **fields: Any) -> None:
        with self.lock:
            t = self.tasks.get(tid)
            if not t:
                return
            t["done"] = (t.get("done") or 0) + 1
            if message:
                t["message"] = message
            t.update(fields)
            total = t.get("total") or 0
            if total:
                t["percent"] = round(min(1.0, t["done"] / total) * 100, 1)

    def finish(self, tid: str, result: Any = None, message: str = "",
               status: str = "done") -> None:
        """收尾。status 默认 done；整理全部失败这类「跑完了但没成功」的情况由调用方指定 error
        （spawn 的默认行为不变：谁也没指定就是 done）。"""
        with self.lock:
            total = self.tasks.get(tid, {}).get("total", 0)
            extra: dict[str, Any] = {}
            if status == "error":
                extra["error"] = message or "任务失败"
            self.update(tid, status=status, result=result, finished_at=_now(),
                        percent=100.0, message=message or "完成", done=total, **extra)

    def fail(self, tid: str, error: str) -> None:
        self.update(tid, status="error", error=error, finished_at=_now(), message=error)

    def get(self, tid: str) -> dict[str, Any] | None:
        with self.lock:
            t = self.tasks.get(tid)
            return dict(t) if t else None

    def cancel(self, tid: str) -> None:
        with self.lock:
            t = self.tasks.get(tid)
            if t and t["status"] == "running":
                t["cancelled"] = True
                t["message"] = "正在取消…"

    def is_cancelled(self, tid: str) -> bool:
        with self.lock:
            t = self.tasks.get(tid)
            return bool(t and t.get("cancelled"))

    def spawn(self, kind: str, fn: Callable[[str], Any], **extra: Any) -> str:
        """建任务并在后台线程跑 fn(task_id)，异常自动记为 error。

        fn 的返回值若是带 `"task_status": "error" | "cancelled"` 的 dict，收尾时就用那个状态
        （缺省仍是 done），并把里面的 `"message"` 当任务消息——整理全部失败就是这样报给前端的。
        """
        tid = self.create(kind, **extra)

        def runner() -> None:
            try:
                result = fn(tid)
                with self.lock:
                    t = self.tasks.get(tid)
                    if t and t["status"] == "running":
                        status, message = "done", ""
                        if isinstance(result, dict):
                            status = str(result.get("task_status") or "done")
                            message = str(result.get("message") or "")
                        self.finish(tid, result=result, message=message, status=status)
            except Exception as e:  # noqa: BLE001 — 后台线程必须兜住所有异常
                traceback.print_exc()
                self.fail(tid, f"{type(e).__name__}: {e}")

        threading.Thread(target=runner, name=f"task-{kind}-{tid}", daemon=True).start()
        return tid
