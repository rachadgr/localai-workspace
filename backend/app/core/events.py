"""In-process pub/sub event bus used to stream task progress via SSE.

Events are persisted to the ``events`` table and broadcast to live subscribers.
The bus is intentionally dependency-free so it works with the inline worker
(no Redis required) and can later be fanned out across processes.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict, deque
from typing import Any, AsyncIterator, Deque

from backend.app.core.errors import ErrorClass
from backend.app.core.observability import get_logger

logger = get_logger("events")


class EventBus:
    def __init__(self, history: int = 500) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._history: dict[str, Deque[dict]] = defaultdict(lambda: deque(maxlen=history))
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ------------------------------------------------------------- publish
    def publish(self, task_id: str, event: dict[str, Any]) -> dict[str, Any]:
        payload = {"task_id": task_id, "ts": time.time(), **event}
        with self._lock:
            self._history[task_id].append(payload)
            queues = list(self._subscribers.get(task_id, []))
        for q in queues:
            self._safe_put(q, payload)
        self._persist(payload)
        return payload

    def _safe_put(self, q: asyncio.Queue, payload: dict[str, Any]) -> None:
        loop = self._loop
        try:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(self._put_nowait, q, payload)
            else:
                self._put_nowait(q, payload)
        except RuntimeError:  # pragma: no cover - loop torn down
            pass

    @staticmethod
    def _put_nowait(q: asyncio.Queue, payload: dict[str, Any]) -> None:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:  # pragma: no cover
            pass

    def _persist(self, payload: dict[str, Any]) -> None:
        try:
            from database.models import EventRecord, session_scope

            with session_scope() as db:
                db.add(
                    EventRecord(
                        task_id=payload.get("task_id"),
                        project_id=payload.get("project_id"),
                        type=str(payload.get("type", "info")),
                        message=str(payload.get("message", ""))[:2000],
                        data_json={k: v for k, v in payload.items() if k not in {"message", "data"}},
                    )
                )
        except Exception as exc:  # pragma: no cover - never break streaming
            logger.debug("event persist failed: %s", exc)

    # ----------------------------------------------------------- subscribe
    async def subscribe(self, task_id: str, replay: bool = True) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers[task_id].append(queue)
            backlog = list(self._history.get(task_id, [])) if replay else []
        try:
            for item in backlog:
                yield item
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield {"type": "heartbeat", "task_id": task_id, "ts": time.time()}
                    continue
                yield item
                if item.get("type") in {"task.completed", "task.failed", "task.cancelled"}:
                    break
        finally:
            with self._lock:
                subs = self._subscribers.get(task_id, [])
                if queue in subs:
                    subs.remove(queue)
                if not subs:
                    self._subscribers.pop(task_id, None)

    def history(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history.get(task_id, []))

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            merged: list[dict] = []
            for items in self._history.values():
                merged.extend(items)
        merged.sort(key=lambda e: e.get("ts", 0))
        return merged[-limit:]


bus = EventBus()


def emit_status(task_id: str, status: str, message: str = "", progress: float | None = None, **extra: Any) -> None:
    bus.publish(task_id, {"type": "task.status", "status": status, "message": message, "progress": progress, **extra})


def emit_plan(task_id: str, plan: dict[str, Any]) -> None:
    bus.publish(task_id, {"type": "task.plan", "plan": plan, "message": "Plan ready"})


def emit_step(task_id: str, step: dict[str, Any]) -> None:
    bus.publish(task_id, {"type": "task.step", **step})


def emit_token(task_id: str, text: str) -> None:
    bus.publish(task_id, {"type": "token", "text": text})


def emit_error(task_id: str, error: dict[str, Any]) -> None:
    bus.publish(task_id, {"type": "task.error", **error})


def emit_artifact(task_id: str, artifact: dict[str, Any]) -> None:
    bus.publish(task_id, {"type": "task.artifact", "artifact": artifact, "message": artifact.get("name", "artifact")})


def emit_done(task_id: str, result: dict[str, Any]) -> None:
    bus.publish(task_id, {"type": "task.completed", "message": "Task completed", "result": result})


def emit_failed(task_id: str, error: dict[str, Any]) -> None:
    bus.publish(task_id, {"type": "task.failed", "message": error.get("error", "failed"), "error": error})


__all__ = [
    "bus",
    "emit_status",
    "emit_plan",
    "emit_step",
    "emit_token",
    "emit_error",
    "emit_artifact",
    "emit_done",
    "emit_failed",
    "ErrorClass",
]
