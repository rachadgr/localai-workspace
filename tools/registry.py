"""Central ToolRegistry.

A single place that owns every tool. Tools self-register via ``@register`` and
the registry persists discovery metadata to the ``tools`` table so the API can
expose schemas without importing Python internals.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Iterable

from backend.app.core.errors import ToolError
from backend.app.core.observability import get_logger
from tools.base import BaseTool, ToolContext, ToolResult, ValidationReport, unavailable_result

logger = get_logger("tool_registry")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._lock = threading.RLock()
        self._loaded = False

    # ---------------------------------------------------------- registration
    def register(self, tool: BaseTool) -> BaseTool:
        with self._lock:
            if tool.name in self._tools:
                raise ToolError(f"Duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool
        return tool

    def load_builtin_tools(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
        from tools import (  # noqa: F401  (import side effects register tools)
            chat_tool,
            developer_tool,
            docs_tool,
            files_tool,
            image_tool,
            research_tool,
            search_tool,
            sheets_tool,
            slides_tool,
            website_tool,
        )

        self.persist()

    # ------------------------------------------------------------- lookup
    def get(self, name: str) -> BaseTool:
        self.load_builtin_tools()
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool '{name}'", detail=f"available={sorted(self._tools)}")
        return tool

    def has(self, name: str) -> bool:
        self.load_builtin_tools()
        return name in self._tools

    def all(self) -> list[BaseTool]:
        self.load_builtin_tools()
        return sorted(self._tools.values(), key=lambda t: (t.category, t.name))

    def names(self) -> list[str]:
        return [t.name for t in self.all()]

    def describe_all(self, ctx: ToolContext | None = None) -> list[dict[str, Any]]:
        out = []
        for tool in self.all():
            info = tool.describe()
            info["availability"] = self.availability(tool.name, ctx)
            if info["availability"] != "AVAILABLE":
                info["unavailable_reason"] = tool.unavailable_reason(ctx)
            out.append(info)
        return out

    def availability(self, name: str, ctx: ToolContext | None = None) -> str:
        try:
            return self.get(name).availability(ctx)
        except ToolError:
            return "UNAVAILABLE"

    # ------------------------------------------------------------ execution
    def execute(self, name: str, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        status = tool.availability(ctx)
        if status != "AVAILABLE":
            return unavailable_result(tool, ctx)
        try:
            result = tool.execute(ctx, payload or {})
        except Exception as exc:  # noqa: BLE001 - normalised below
            from backend.app.core.errors import classify

            app_err = classify(exc)
            logger.warning("tool %s failed: %s", name, app_err.message)
            return ToolResult(
                status="FAILED",
                summary=app_err.message,
                error=app_err.detail or app_err.message,
                error_class=app_err.error_class.value,
            )
        if result is None:
            return ToolResult(status="FAILED", summary=f"{name} returned no result", error="none", error_class="InternalError")
        return result

    def validate(self, name: str, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        return self.get(name).validate(ctx, result)

    # ---------------------------------------------------------- persistence
    def persist(self) -> None:
        try:
            from database.models import ToolRecord, session_scope

            with session_scope() as db:
                for tool in self.all():
                    row = db.get(ToolRecord, tool.name)
                    if row is None:
                        row = ToolRecord(name=tool.name)
                        db.add(row)
                    row.description = tool.description
                    row.category = tool.category
                    row.permissions = list(tool.permissions)
                    row.input_schema = tool.input_schema
                    row.output_schema = tool.output_schema
                    row.cost_estimate = tool.cost_estimate
                    row.availability = tool.availability()
        except Exception as exc:  # pragma: no cover
            logger.debug("tool persist skipped: %s", exc)

    # -------------------------------------------------------------- catalog
    def catalog(self) -> dict[str, list[str]]:
        catalog: dict[str, list[str]] = {}
        for tool in self.all():
            catalog.setdefault(tool.category, []).append(tool.name)
        return catalog


registry = ToolRegistry()


def register(tool_cls: type[BaseTool]) -> type[BaseTool]:
    """Class decorator registering a tool instance."""
    registry.register(tool_cls())
    return tool_cls


def execute_tool(name: str, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
    return registry.execute(name, ctx, payload)


def get_tool(name: str) -> BaseTool:
    return registry.get(name)


def tool_names() -> Iterable[str]:
    return registry.names()


__all__ = ["ToolRegistry", "registry", "register", "execute_tool", "get_tool", "tool_names", "ToolContext", "ToolResult"]
