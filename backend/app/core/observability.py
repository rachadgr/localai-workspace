"""Structured logging and observability.

Captures task id, tool, model, duration, status, errors, artifact ids and
token/cost metadata. Secrets are always redacted before they reach the sink.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from backend.app.core.security import redact, redact_mapping

_EVENTS_BUFFER: list[dict[str, Any]] = []
_MAX_BUFFER = 2000


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact_mapping(extra))
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"localai.{name}")


@dataclass
class Observation:
    task_id: str = ""
    project_id: str = ""
    tool: str = ""
    model: str = ""
    status: str = "ok"
    error: str = ""
    artifact_ids: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return redact_mapping(
            {
                "task_id": self.task_id,
                "project_id": self.project_id,
                "tool": self.tool,
                "model": self.model,
                "status": self.status,
                "error": self.error,
                "artifact_ids": self.artifact_ids,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "cost_usd": round(self.cost_usd, 6),
                "duration_ms": self.duration_ms,
                **self.extra,
            }
        )


def record_observation(obs: Observation) -> dict[str, Any]:
    payload = obs.to_dict()
    _EVENTS_BUFFER.append(payload)
    if len(_EVENTS_BUFFER) > _MAX_BUFFER:
        del _EVENTS_BUFFER[: len(_EVENTS_BUFFER) - _MAX_BUFFER]
    get_logger("observability").info("observation", extra={"extra_fields": payload})
    return payload


def recent_observations(limit: int = 100) -> list[dict[str, Any]]:
    return list(reversed(_EVENTS_BUFFER[-limit:]))


@contextmanager
def timer() -> Iterator[dict[str, Any]]:
    box: dict[str, Any] = {"start": time.perf_counter()}
    try:
        yield box
    finally:
        box["duration_ms"] = int((time.perf_counter() - box["start"]) * 1000)
