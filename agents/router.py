"""Router: resolves each plan step to a concrete tool + fully-bound inputs.

Responsibilities:
* Reject tools that are not AVAILABLE and surface an honest reason.
* Bind outputs of previous steps into the inputs of the current step
  (e.g. research → slides uses the research report as context).
* Apply sensible input repair (fill required fields from the raw request).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.core.observability import get_logger
from agents.planner import Plan, PlanStep

logger = get_logger("router")


@dataclass
class Routing:
    tool: str
    available: bool
    inputs: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    fallback_tool: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "available": self.available, "inputs": self.inputs, "reason": self.reason, "fallback_tool": self.fallback_tool}


class Router:
    def __init__(self, tool_registry: Any) -> None:
        self.tools = tool_registry

    def route(self, plan: Plan, step: PlanStep, ctx: Any, previous: dict[str, Any] | None = None) -> Routing:
        previous = previous or {}
        tool_name = step.tool

        if not self.tools.has(tool_name):
            return Routing(tool=tool_name, available=False, reason=f"Tool '{tool_name}' is not registered", fallback_tool="chat")

        availability = self.tools.availability(tool_name, ctx)
        inputs = self._bind_inputs(tool_name, step, plan, previous)

        if availability != "AVAILABLE":
            tool = self.tools.get(tool_name)
            reason = tool.unavailable_reason(ctx) or f"{tool_name} is {availability}"
            fallback = self._fallback_for(tool_name)
            return Routing(tool=tool_name, available=False, inputs=inputs, reason=reason, fallback_tool=fallback)

        return Routing(tool=tool_name, available=True, inputs=inputs, reason="ok")

    # ------------------------------------------------------------ binding
    def _bind_inputs(self, tool_name: str, step: PlanStep, plan: Plan, previous: dict[str, Any]) -> dict[str, Any]:
        inputs = dict(step.inputs or {})
        request = plan.context.get("request", "")
        tool = self.tools.get(tool_name) if self.tools.has(tool_name) else None
        required = (tool.input_schema.get("required") if tool else []) or []

        # Fill missing required fields from the request / previous output.
        for key in required:
            if inputs.get(key) is not None:
                continue
            if key in previous and previous[key]:
                inputs[key] = previous[key]
                continue
            inputs[key] = self._default_for(key, request, plan, previous)

        if tool_name == "slides":
            # Chain: research text becomes the deck source.
            research = previous.get("research") or {}
            if research.get("markdown") and not inputs.get("prompt"):
                inputs["prompt"] = research["markdown"][:12000]
            inputs.setdefault("title", plan.title)
            inputs.setdefault("prompt", request)
            inputs.setdefault("target_slides", 10)

        if tool_name == "docs":
            research = previous.get("research") or {}
            search = previous.get("search") or {}
            if research.get("markdown") and not inputs.get("prompt"):
                inputs["prompt"] = research["markdown"][:12000]
            elif search.get("summary") and not inputs.get("prompt"):
                inputs["prompt"] = search["summary"]
            inputs.setdefault("title", plan.title)
            inputs.setdefault("format", inputs.get("format", "md"))

        if tool_name == "chat":
            inputs.setdefault("message", request)
            if plan.context.get("history"):
                inputs.setdefault("history", plan.context["history"])
            if plan.context.get("memory"):
                inputs.setdefault("context", plan.context["memory"])

        return inputs

    @staticmethod
    def _default_for(key: str, request: str, plan: Plan, previous: dict[str, Any]) -> Any:
        mapping = {
            "message": request,
            "prompt": request,
            "task": request,
            "question": request,
            "query": request,
            "description": request,
            "title": plan.title,
            "site_name": plan.title[:40].lower().replace(" ", "-") or "site",
            "action": "brief" if key == "action" else "list",
        }
        if key in mapping:
            return mapping[key]
        return previous.get(key)

    @staticmethod
    def _fallback_for(tool_name: str) -> str | None:
        fallbacks = {
            "image": "docs",       # design brief can fall back to a written document
            "search": "chat",
            "research": "search",
            "website": "docs",
        }
        return fallbacks.get(tool_name)


__all__ = ["Router", "Routing"]
