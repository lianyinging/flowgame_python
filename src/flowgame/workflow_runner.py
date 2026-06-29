"""工作流执行并发控制（阶段 0：有界信号量，默认不限制以保持兼容）。"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator, Optional


class WorkflowQueueFullError(Exception):
    """并发槽位已满且排队超时。"""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return float(raw)


class WorkflowConcurrencyLimiter:
    """限制同时执行的工作流数量；max_concurrent<=0 时不限制。"""

    def __init__(self, max_concurrent: int, queue_timeout_sec: float) -> None:
        self._max_concurrent = max(0, int(max_concurrent))
        self._queue_timeout_sec = max(0.0, float(queue_timeout_sec))
        self._semaphore: Optional[threading.BoundedSemaphore] = None
        if self._max_concurrent > 0:
            self._semaphore = threading.BoundedSemaphore(self._max_concurrent)

    @property
    def enabled(self) -> bool:
        return self._semaphore is not None

    @contextmanager
    def slot(self) -> Iterator[None]:
        if self._semaphore is None:
            yield
            return

        if self._queue_timeout_sec <= 0:
            acquired = self._semaphore.acquire(blocking=False)
        else:
            acquired = self._semaphore.acquire(timeout=self._queue_timeout_sec)
        if not acquired:
            raise WorkflowQueueFullError(
                "当前执行中的工作流过多，请稍后重试"
            )
        try:
            yield
        finally:
            self._semaphore.release()


_limiter: Optional[WorkflowConcurrencyLimiter] = None
_limiter_lock = threading.Lock()


def get_workflow_concurrency_limiter() -> WorkflowConcurrencyLimiter:
    global _limiter
    if _limiter is not None:
        return _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = WorkflowConcurrencyLimiter(
                max_concurrent=_env_int("FLOWGAME_MAX_CONCURRENT_WORKFLOWS", 0),
                queue_timeout_sec=_env_float("FLOWGAME_WORKFLOW_QUEUE_TIMEOUT_SEC", 60.0),
            )
        return _limiter


@contextmanager
def workflow_run_slot() -> Iterator[None]:
    with get_workflow_concurrency_limiter().slot():
        yield
