"""AI Chat tool: model-routed conversation with context and optional tool calling."""

from __future__ import annotations

from typing import Any

from backend.app.core.errors import ModelUnavailableError, ToolError
from models.adapters import ChatMessage
from models.registry import STATUS_AVAILABLE
from tools.base import BaseTool, Permission, ToolContext, ToolResult, ValidationReport
from tools.registry import register


@register
class ChatTool(BaseTool):
    name = "chat"
    description = "Answer a message with a routed LLM, optionally using project context and prior conversation history."
    category = "chat"
    permissions = [Permission.READ, Permission.MODEL]
    cost_estimate = "model-tokens"
    input_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "User message"},
            "history": {"type": "array", "items": {"type": "object", "properties": {"role": {"type": "string"}, "content": {"type": "string"}}}},
            "context": {"type": "string", "description": "Extra project context"},
            "system": {"type": "string", "description": "System instruction override"},
            "model": {"type": "string"},
            "temperature": {"type": "number"},
            "max_tokens": {"type": "integer"},
        },
        "required": ["message"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "model": {"type": "string"},
            "tokens_in": {"type": "integer"},
            "tokens_out": {"type": "integer"},
        },
    }

    def availability(self, ctx: ToolContext | None = None) -> str:
        registry = getattr(ctx, "model_registry", None) if ctx else None
        if registry is None:
            from models.registry import registry as global_registry

            registry = global_registry
        try:
            return "AVAILABLE" if registry.chat_available() else "UNAVAILABLE"
        except Exception:
            return "UNAVAILABLE"

    def unavailable_reason(self, ctx: ToolContext | None = None) -> str:
        return "No chat model is reachable (check LLM base URL / API key)."

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        message = self.require(payload, "message")
        registry = getattr(ctx, "model_registry", None)
        if registry is None:
            from models.registry import registry as global_registry

            registry = global_registry

        model = payload.get("model") or registry.default_chat_model()
        system = payload.get("system") or "You are LocalAI Workspace, a precise, honest assistant. If you are unsure or lack data, say so explicitly instead of inventing facts."

        messages: list[ChatMessage] = [ChatMessage("system", system)]
        if payload.get("context"):
            messages.append(ChatMessage("system", f"Project context:\n{payload['context']}"))
        for item in payload.get("history") or []:
            role = str(item.get("role", "user"))
            content = str(item.get("content", ""))
            if role in ("system", "user", "assistant") and content:
                messages.append(ChatMessage(role, content))
        messages.append(ChatMessage("user", message))

        opts: dict[str, Any] = {}
        if payload.get("temperature") is not None:
            opts["temperature"] = payload["temperature"]
        if payload.get("max_tokens") is not None:
            opts["max_tokens"] = payload["max_tokens"]

        try:
            completion = registry.complete(messages, model=model, **opts)
        except ModelUnavailableError as exc:
            return ToolResult(status="UNAVAILABLE", summary=exc.message, error=exc.message, error_class="ModelUnavailable")

        return ToolResult(
            status="SUCCESS",
            summary=completion.text[:280],
            data={
                "text": completion.text,
                "model": completion.model,
                "provider": completion.provider,
                "tokens_in": completion.tokens_in,
                "tokens_out": completion.tokens_out,
                "finish_reason": completion.finish_reason,
            },
        )

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        if result.status == "SUCCESS":
            text = result.data.get("text", "")
            checks.append({"name": "non_empty", "ok": bool(text.strip()), "detail": f"{len(text)} chars"})
        return ValidationReport(valid=all(c["ok"] for c in checks), checks=checks, message="chat validation")
