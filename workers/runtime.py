"""Async job runtime.

Provides a dependency-free, in-process job manager with real lifecycle states
(QUEUED, RUNNING, WAITING, COMPLETED, FAILED, CANCELLED), progress reporting and
cancellation. When ``REDIS_URL`` + a Celery deployment are configured the same
``JobManager.submit`` API can be fronted by Celery (see ``workers/celery_app.py``),
but the default inline mode is fully functional on a single node.
"""

from __future__ import annotations

import enum
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.app.core.events import bus, emit_failed, emit_status
from backend.app.core.observability import get_logger

logger = get_logger("jobs")


class Stage(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class Job:
    id: str
    kind: str
    status: Stage = Stage.QUEUED
    progress: float = 0.0
    message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    started_at: float | None = None
    completed_at: float | None = None
    created_at: float = field(default_factory=time.time)
    cancellable: bool = True
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status.value,
            "progress": round(self.progress, 4),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
        }


class JobManager:
    def __init__(self, max_workers: int = 4) -> None:
        from configs.settings import settings

        workers = max(2, int(settings.worker_concurrency or max_workers))
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="laiw-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()

    # --------------------------------------------------------------- submit
    def submit(self, job_id: str, kind: str, fn: Callable[[Job, threading.Event], dict[str, Any]]) -> Job:
        job = Job(id=job_id, kind=kind)
        with self._lock:
            self._jobs[job_id] = job

        def _runner() -> None:
            if job._cancel.is_set():
                job.status = Stage.CANCELLED
                emit_status(job.id, Stage.CANCELLED.value, "cancelled before start", 0.0)
                return
            job.status = Stage.RUNNING
            job.started_at = time.time()
            emit_status(job.id, Stage.RUNNING.value, "job started", 0.0)
            try:
                result = fn(job, job._cancel)
                if job._cancel.is_set():
                    job.status = Stage.CANCELLED
                    job.completed_at = time.time()
                    emit_status(job.id, Stage.CANCELLED.value, "job cancelled", job.progress)
                    return
                job.result = result or {}
                job.status = Stage.COMPLETED
                job.progress = 1.0
                job.completed_at = time.time()
            except Exception as exc:  # noqa: BLE001
                from backend.app.core.errors import classify

                app_err = classify(exc)
                job.status = Stage.FAILED
                job.error = app_err.message
                job.completed_at = time.time()
                logger.warning("job %s failed: %s", job.id, app_err.message)
                emit_failed(job.id, app_err.to_dict())
                job.result = {"error": app_err.to_dict(), "traceback": traceback.format_exc()[-2000:]}

        self._executor.submit(_runner)
        return job

    # ---------------------------------------------------------------- query
    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.status in (Stage.COMPLETED, Stage.FAILED, Stage.CANCELLED):
            return False
        job._cancel.set()
        job.status = Stage.CANCELLED
        job.completed_at = time.time()
        emit_status(job.id, Stage.CANCELLED.value, "cancellation requested", job.progress)
        return True

    def update(self, job_id: str, progress: float | None = None, message: str = "", status: Stage | None = None) -> None:
        job = self.get(job_id)
        if job is None:
            return
        if progress is not None:
            job.progress = max(0.0, min(1.0, progress))
        if message:
            job.message = message
        if status:
            job.status = status
        emit_status(job.id, job.status.value, message or job.message, job.progress)

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status in (Stage.QUEUED, Stage.RUNNING, Stage.WAITING))


job_manager = JobManager()


__all__ = ["Job", "JobManager", "job_manager", "Stage"]
