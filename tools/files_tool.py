"""Files tool: project-scoped file operations with path-traversal protection."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from backend.app.core.errors import ToolError
from backend.app.core.security import safe_join, sanitize_filename
from tools.base import BaseTool, Permission, ToolContext, ToolResult, ValidationReport
from tools.registry import register

CATEGORIES = ["uploads", "generated", "research", "documents", "spreadsheets", "presentations", "code", "website"]
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".html", ".css", ".js", ".ts", ".py", ".yaml", ".yml", ".log", ".xml"}


@register
class FilesTool(BaseTool):
    name = "files"
    description = "List, read, write, move and delete project-scoped files, and ingest uploaded content into the project workspace."
    category = "files"
    permissions = [Permission.READ, Permission.WRITE, Permission.FILES]
    cost_estimate = "cheap"
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read", "write", "delete", "stat"], "default": "list"},
            "path": {"type": "string", "description": "Path relative to the project workspace"},
            "content": {"type": "string"},
            "category": {"type": "string", "enum": CATEGORIES, "default": "generated"},
        },
        "required": ["action"],
    }
    output_schema = {"type": "object", "properties": {"files": {"type": "array"}, "content": {"type": "string"}}}

    def availability(self, ctx: ToolContext | None = None) -> str:
        return "AVAILABLE"

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        action = str(payload.get("action", "list")).lower()
        workspace = ctx.workspace

        if action == "list":
            category = payload.get("category")
            roots = [workspace / category] if category else [workspace / c for c in CATEGORIES] + [workspace]
            files: list[dict[str, Any]] = []
            for root in roots:
                if not root.exists():
                    continue
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        rel = path.relative_to(workspace).as_posix()
                        if any(f["path"] == rel for f in files):
                            continue
                        files.append({"path": rel, "size": path.stat().st_size, "category": rel.split("/")[0]})
            return ToolResult(status="SUCCESS", summary=f"{len(files)} file(s) in project workspace.", data={"files": files, "workspace": str(workspace)})

        rel = payload.get("path")
        if not rel:
            raise ToolError(f"'path' is required for action '{action}'")
        target = safe_join(workspace, rel)

        if action == "read":
            if not target.exists() or not target.is_file():
                raise ToolError(f"File not found: {rel}")
            if target.suffix.lower() in TEXT_SUFFIXES or target.stat().st_size < 1_000_000:
                try:
                    content = target.read_text(encoding="utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    content = ""
                return ToolResult(status="SUCCESS", summary=f"Read {rel} ({len(content)} chars).", data={"content": content[:200_000], "path": rel})
            raise ToolError(f"Binary file cannot be read as text: {rel}")

        if action == "stat":
            if not target.exists():
                raise ToolError(f"File not found: {rel}")
            return ToolResult(status="SUCCESS", summary=f"{rel}: {target.stat().st_size} bytes", data={"path": rel, "size": target.stat().st_size})

        if action == "write":
            content = payload.get("content", "")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            artifact = ctx.save_artifact(Path(rel).name, content, "file", "text/plain", rel.split("/")[0] if "/" in rel else "generated", {"path": rel})
            return ToolResult(status="SUCCESS", summary=f"Wrote {rel} ({len(content)} chars).", data={"path": rel}, artifacts=[artifact])

        if action == "delete":
            if not target.exists():
                raise ToolError(f"File not found: {rel}")
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return ToolResult(status="SUCCESS", summary=f"Deleted {rel}.", data={"path": rel})

        raise ToolError(f"Unsupported action '{action}'")

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        if result.status == "SUCCESS" and "path" in result.data:
            checks.append({"name": "within_workspace", "ok": str(ctx.workspace) in str(safe_join(ctx.workspace, result.data["path"])), "detail": result.data["path"]})
        return ValidationReport(valid=all(c["ok"] for c in checks), message="files validation")


def ingest_upload(ctx: ToolContext, filename: str, data: bytes, category: str = "uploads") -> dict[str, Any]:
    """Persist an uploaded file into the project workspace and return artifact+file info."""
    safe_name = sanitize_filename(filename, fallback="upload.bin")
    return ctx.save_artifact(
        name=safe_name,
        payload=data,
        type_="upload",
        mime_type="application/octet-stream",
        category=category if category in CATEGORIES else "uploads",
        meta={"checksum": hashlib.sha256(data).hexdigest()},
    )


__all__ = ["FilesTool", "ingest_upload", "CATEGORIES"]
