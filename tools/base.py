"""Base tool abstractions.

Every tool exposes:
* name, description, category
* input_schema / output_schema (JSON Schema)
* permissions (READ/WRITE/EXECUTE/NETWORK/WEB/FILES/CODE/MODEL)
* availability()  -> AVAILABLE | UNAVAILABLE | MISCONFIGURED | DISABLED
* cost_estimate
* execute(ctx, payload) -> ToolResult
* validate(ctx, result) -> ValidationReport
"""

from __future__ import annotations

import datetime as dt
import hashlib
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from backend.app.core.errors import ToolError, UNAVAILABLE
from database.models import Artifact, FileRecord, new_id

AVAILABLE = "AVAILABLE"


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
class Permission:
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    NETWORK = "NETWORK"
    WEB = "WEB"
    FILES = "FILES"
    CODE = "CODE"
    MODEL = "MODEL"

    ALL = [READ, WRITE, EXECUTE, NETWORK, WEB, FILES, CODE, MODEL]


# --------------------------------------------------------------------------- #
# Context / results
# --------------------------------------------------------------------------- #
@dataclass
class ToolContext:
    project_id: str
    user_id: str = ""
    task_id: str = ""
    conversation_id: str = ""
    settings: Any = None
    model_registry: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def workspace(self) -> Path:
        base = Path(self.settings.projects_dir) / self.project_id
        base.mkdir(parents=True, exist_ok=True)
        return base

    def category_dir(self, category: str) -> Path:
        target = self.workspace / category
        target.mkdir(parents=True, exist_ok=True)
        return target

    # ------------------------------------------------------------- artifacts
    def save_artifact(
        self,
        name: str,
        payload: bytes | str,
        type_: str = "document",
        mime_type: str = "",
        category: str = "generated",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        target_dir = self.category_dir(category)
        safe_name = _unique_name(target_dir, name)
        path = target_dir / safe_name
        path.write_bytes(data)
        mime = mime_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        checksum = hashlib.sha256(data).hexdigest()

        artifact_id = new_id("art_")
        record = Artifact(
            id=artifact_id,
            project_id=self.project_id,
            task_id=self.task_id or None,
            name=safe_name,
            type=type_,
            mime_type=mime,
            size=len(data),
            status="READY",
            storage_path=str(path),
            meta_json=meta or {},
        )
        file_id = new_id("fil_")
        file_record = FileRecord(
            id=file_id,
            project_id=self.project_id,
            name=safe_name,
            category=category,
            path=str(path),
            mime_type=mime,
            size=len(data),
            checksum=checksum,
        )
        try:
            from database.models import session_scope

            with session_scope() as db:
                db.add(record)
                db.add(file_record)
        except Exception:
            pass

        return {
            "id": artifact_id,
            "file_id": file_id,
            "name": safe_name,
            "type": type_,
            "mime_type": mime,
            "size": len(data),
            "project_id": self.project_id,
            "task_id": self.task_id,
            "storage_path": str(path),
            "category": category,
            "status": "READY",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "checksum": checksum,
        }


@dataclass
class ToolResult:
    status: str = "SUCCESS"  # SUCCESS | UNAVAILABLE | FAILED
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    error_class: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "SUCCESS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "data": self.data,
            "artifacts": self.artifacts,
            "error": self.error,
            "error_class": self.error_class,
        }


@dataclass
class ValidationReport:
    valid: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "checks": self.checks, "message": self.message}


def _unique_name(directory: Path, name: str) -> str:
    from backend.app.core.security import sanitize_filename

    name = sanitize_filename(name)
    candidate = directory / name
    if not candidate.exists():
        return name
    stem, suffix = candidate.stem, candidate.suffix
    i = 1
    while True:
        alt = directory / f"{stem}_{i}{suffix}"
        if not alt.exists():
            return alt.name
        i += 1


# --------------------------------------------------------------------------- #
# Base tool
# --------------------------------------------------------------------------- #
class BaseTool:
    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    category: ClassVar[str] = "general"
    permissions: ClassVar[list[str]] = [Permission.READ]
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    output_schema: ClassVar[dict[str, Any]] = {"type": "object"}
    cost_estimate: ClassVar[str] = "cheap"

    def availability(self, ctx: ToolContext | None = None) -> str:
        return AVAILABLE

    def unavailable_reason(self, ctx: ToolContext | None = None) -> str:
        return ""

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:  # pragma: no cover
        raise NotImplementedError

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        return ValidationReport(valid=result.status != "FAILED", checks=checks, message="default validation")

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "permissions": self.permissions,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "cost_estimate": self.cost_estimate,
        }

    # helpers ---------------------------------------------------------------
    @staticmethod
    def require(payload: dict[str, Any], key: str, default: Any = None) -> Any:
        value = payload.get(key, default)
        if value is None:
            raise ToolError(f"Missing required field '{key}'")
        return value


def unavailable_result(tool: BaseTool, ctx: ToolContext | None = None) -> ToolResult:
    reason = tool.unavailable_reason(ctx) or f"{tool.name} is UNAVAILABLE"
    return ToolResult(status=UNAVAILABLE, summary=reason, error=reason, error_class="UNAVAILABLE")


__all__ = [
    "BaseTool",
    "ToolContext",
    "ToolResult",
    "ValidationReport",
    "Permission",
    "AVAILABLE",
    "UNAVAILABLE",
    "unavailable_result",
]
