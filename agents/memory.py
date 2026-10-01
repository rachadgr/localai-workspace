"""Memory manager: session / project / user scopes + task history + artifact refs.

Secrets are never stored: all values pass through ``redact`` before persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from backend.app.core.security import redact
from backend.app.core.observability import get_logger
from database.models import MemoryEntry, session_scope

logger = get_logger("memory")

SCOPES = ("session", "project", "user")
KINDS = ("note", "preference", "fact", "summary", "artifact_ref", "task_history")


@dataclass
class MemoryItem:
    id: str
    scope: str
    owner_id: str
    kind: str
    key: str
    value: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "scope": self.scope, "owner_id": self.owner_id, "kind": self.kind, "key": self.key, "value": self.value}


class MemoryManager:
    def remember(self, scope: str, owner_id: str, kind: str, key: str, value: str, meta: dict | None = None) -> MemoryItem:
        if scope not in SCOPES:
            scope = "project"
        if kind not in KINDS:
            kind = "note"
        safe_value = redact(str(value))[:20000]
        with session_scope() as db:
            existing = db.execute(
                select(MemoryEntry).where(
                    MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id, MemoryEntry.kind == kind, MemoryEntry.key == key
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.value = safe_value
                existing.meta_json = meta or existing.meta_json
                db.flush()
                return MemoryItem(existing.id, scope, owner_id, kind, key, existing.value)
            entry = MemoryEntry(scope=scope, owner_id=owner_id, kind=kind, key=key[:200], value=safe_value, meta_json=meta or {})
            db.add(entry)
            db.flush()
            return MemoryItem(entry.id, scope, owner_id, kind, key, entry.value)

    def recall(self, scope: str, owner_id: str, kind: str | None = None, query: str = "", limit: int = 40) -> list[MemoryItem]:
        with session_scope() as db:
            stmt = select(MemoryEntry).where(MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id)
            if kind:
                stmt = stmt.where(MemoryEntry.kind == kind)
            stmt = stmt.order_by(MemoryEntry.created_at.desc()).limit(limit)
            rows = db.execute(stmt).scalars().all()
        items = [MemoryItem(r.id, r.scope, r.owner_id, r.kind, r.key, r.value) for r in rows]
        if query:
            q = query.lower()
            items = [i for i in items if q in i.key.lower() or q in i.value.lower()] or items
        return items

    def delete(self, memory_id: str) -> bool:
        with session_scope() as db:
            row = db.get(MemoryEntry, memory_id)
            if row is None:
                return False
            db.delete(row)
            return True

    def context_block(self, project_id: str, user_id: str, conversation_id: str, limit: int = 20) -> str:
        """Compact text block injected into LLM prompts."""
        parts: list[str] = []
        for scope, owner in (("project", project_id), ("user", user_id), ("session", conversation_id)):
            if not owner:
                continue
            items = self.recall(scope, owner, limit=limit // 2 or 5)
            if items:
                parts.append(f"[{scope} memory]")
                parts += [f"- ({i.kind}) {i.key}: {i.value[:300]}" for i in items]
        return "\n".join(parts)[:6000]

    def record_task(self, project_id: str, task: dict[str, Any]) -> None:
        text = f"{task.get('kind')}: {task.get('request', '')[:400]} -> {task.get('status')}"
        self.remember("project", project_id, "task_history", task.get("id", ""), text)

    def summary(self, project_id: str, user_id: str, conversation_id: str) -> dict[str, int]:
        return {
            "project": len(self.recall("project", project_id, limit=200)),
            "user": len(self.recall("user", user_id, limit=200)) if user_id else 0,
            "session": len(self.recall("session", conversation_id, limit=200)) if conversation_id else 0,
        }


memory_manager = MemoryManager()

__all__ = ["MemoryManager", "memory_manager", "MemoryItem", "SCOPES", "KINDS"]
