"""Celery application for distributed job execution.

Enabled only when ``LAIW_WORKER_MODE=celery`` and ``REDIS_URL`` is set. The
in-process ``workers.runtime.JobManager`` remains the default so the workspace
runs with zero infrastructure. Celery is an optional scale-out path.
"""

from __future__ import annotations

import os

from configs.settings import settings

try:  # Celery is optional: not required for the default inline mode.
    from celery import Celery

    CELERY_AVAILABLE = True
except Exception:  # pragma: no cover - celery not installed
    Celery = None  # type: ignore[assignment]
    CELERY_AVAILABLE = False


def make_app():
    if not CELERY_AVAILABLE:
        raise RuntimeError("Celery is not installed. `pip install celery redis` to enable LAIW_WORKER_MODE=celery.")
    app = Celery("localai", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
    )

    @app.task(name="localai.run_agent_task")
    def run_agent_task(request: str, project_id: str, user_id: str, conversation_id: str = "", task_id: str = "") -> dict:
        from agents.orchestrator import orchestrator

        result = orchestrator.run(
            request=request,
            project_id=project_id,
            user_id=user_id,
            conversation_id=conversation_id,
            task_id=task_id or None,
            persist_assistant_message=True,
        )
        return result.to_dict()

    return app


celery_app = make_app() if (CELERY_AVAILABLE and settings.worker_mode == "celery") else None

__all__ = ["celery_app", "make_app", "CELERY_AVAILABLE"]
