"""Context assembler: builds the working context for a task.

Gathers project metadata, conversation history, memory, prior artifacts and
uploaded-file summaries, bounded to a token-conscious budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from backend.app.core.observability import get_logger
from database.models import Artifact, FileRecord, Message, Project, session_scope

logger = get_logger("context")


@dataclass
class TaskContext:
    project_id: str
    user_id: str = ""
    conversation_id: str = ""
    request: str = ""
    project_name: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    memory_block: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "conversation_id": self.conversation_id,
            "history_turns": len(self.history),
            "artifacts": len(self.artifacts),
            "files": len(self.files),
            "memory_chars": len(self.memory_block),
            "extra": self.extra,
        }

    def planner_context(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "history": self.history[-12:],
            "memory": self.memory_block,
            "artifacts": self.artifacts[:10],
            **self.extra,
        }


class ContextAssembler:
    def __init__(self, memory: Any = None) -> None:
        self.memory = memory

    def build(
        self,
        project_id: str,
        user_id: str,
        conversation_id: str,
        request: str,
        history_limit: int = 16,
        extra: dict[str, Any] | None = None,
    ) -> TaskContext:
        ctx = TaskContext(project_id=project_id, user_id=user_id, conversation_id=conversation_id, request=request, extra=extra or {})

        try:
            with session_scope() as db:
                project = db.get(Project, project_id)
                if project is not None:
                    ctx.project_name = project.name

                if conversation_id:
                    rows = (
                        db.execute(
                            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).limit(history_limit)
                        )
                        .scalars()
                        .all()
                    )
                    ctx.history = [{"role": r.role, "content": r.content[:4000]} for r in reversed(rows) if r.role in ("user", "assistant")]

                artifacts = (
                    db.execute(select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at.desc()).limit(20)).scalars().all()
                )
                ctx.artifacts = [
                    {"id": a.id, "name": a.name, "type": a.type, "mime_type": a.mime_type, "size": a.size, "created_at": a.created_at.isoformat() if a.created_at else ""}
                    for a in artifacts
                ]

                files = (
                    db.execute(select(FileRecord).where(FileRecord.project_id == project_id).order_by(FileRecord.created_at.desc()).limit(30)).scalars().all()
                )
                ctx.files = [{"id": f.id, "name": f.name, "category": f.category, "size": f.size, "mime_type": f.mime_type} for f in files]
        except Exception as exc:  # noqa: BLE001
            logger.debug("context assembly degraded: %s", exc)

        if self.memory is not None:
            try:
                ctx.memory_block = self.memory.context_block(project_id, user_id, conversation_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("memory recall failed: %s", exc)

        return ctx


__all__ = ["ContextAssembler", "TaskContext"]
