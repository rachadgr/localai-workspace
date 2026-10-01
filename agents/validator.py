"""Validator: verifies that a tool's output actually satisfies the step.

Validation is layered:
1. The tool's own ``validate()`` (artifact existence, format integrity, citations…).
2. Cross-cutting checks performed here: declared artifacts must exist on disk,
   SUCCESS results must carry a non-empty summary, and research/website/sheets
   outputs must expose their expected structures.
"""

from __future__ import annotations

import os
from typing import Any

from backend.app.core.observability import get_logger
from tools.base import ToolContext, ToolResult, ValidationReport

logger = get_logger("validator")


class Validator:
    def __init__(self, tool_registry: Any) -> None:
        self.tools = tool_registry

    def validate_step(self, tool_name: str, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks: list[dict[str, Any]] = []

        checks.append({"name": "tool_status_not_failed", "ok": result.status != "FAILED", "detail": result.status})

        if result.status == "UNAVAILABLE":
            # UNAVAILABLE is an honest outcome, not a failure.
            return ValidationReport(valid=True, checks=checks, message=f"{tool_name} unavailable: {result.summary}")

        if result.status == "SUCCESS":
            checks.append({"name": "summary_present", "ok": bool(result.summary.strip()), "detail": result.summary[:120]})
            for art in result.artifacts:
                path = art.get("storage_path", "")
                exists = bool(path) and os.path.exists(path) and os.path.getsize(path) > 0
                checks.append(
                    {
                        "name": f"artifact_exists:{art.get('name', '?')}",
                        "ok": exists,
                        "detail": f"{art.get('size', 0)} bytes" if exists else "missing or empty",
                    }
                )

        # Tool-specific validation.
        try:
            report = self.tools.validate(tool_name, ctx, result)
            checks.extend(report.checks)
        except Exception as exc:  # noqa: BLE001
            logger.debug("tool validate() raised for %s: %s", tool_name, exc)
            checks.append({"name": "tool_validate_ran", "ok": False, "detail": f"{type(exc).__name__}: {exc}"})

        valid = all(c.get("ok", False) for c in checks)
        message = f"{tool_name} validation {'passed' if valid else 'failed'} ({sum(1 for c in checks if c.get('ok'))}/{len(checks)} checks)"
        return ValidationReport(valid=valid, checks=checks, message=message)

    def verify_artifacts(self, artifacts: list[dict[str, Any]]) -> ValidationReport:
        checks = []
        for art in artifacts:
            path = art.get("storage_path", "")
            checks.append({"name": f"exists:{art.get('name', '?')}", "ok": bool(path) and os.path.exists(path), "detail": path})
        return ValidationReport(valid=all(c["ok"] for c in checks) if checks else True, checks=checks, message="artifact existence")


__all__ = ["Validator"]
