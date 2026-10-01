"""AI Image/Design tool.

Image *generation/editing* requires a configured provider (``LAIW_IMAGE_PROVIDER_URL``).
Without it the tool honestly returns UNAVAILABLE and never fabricates images.
Design briefs and prompt engineering work whenever an LLM is reachable.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from typing import Any

import requests

from backend.app.core.errors import NetworkError, ToolError
from models.adapters import ChatMessage
from tools.base import BaseTool, Permission, ToolContext, ToolResult, ValidationReport
from tools.registry import register
from configs.settings import settings


@register
class ImageTool(BaseTool):
    name = "image"
    description = "Generate design briefs and image prompts; generate or edit images when an image provider is configured (otherwise UNAVAILABLE)."
    category = "design"
    permissions = [Permission.READ, Permission.WRITE, Permission.FILES, Permission.NETWORK, Permission.MODEL]
    cost_estimate = "model-tokens (+provider cost)"
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["brief", "prompt", "generate", "variant"], "default": "brief"},
            "description": {"type": "string"},
            "style": {"type": "string"},
            "aspect_ratio": {"type": "string", "default": "1:1"},
            "variants": {"type": "integer", "default": 1},
            "base_image_url": {"type": "string", "description": "For editing/variants"},
            "model": {"type": "string"},
        },
        "required": ["description"],
    }
    output_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "brief": {"type": "object"}, "prompts": {"type": "array"}, "images": {"type": "array"}},
    }

    def availability(self, ctx: ToolContext | None = None) -> str:
        if not settings.enable_network_tools:
            return "UNAVAILABLE"
        return "AVAILABLE"

    def unavailable_reason(self, ctx: ToolContext | None = None) -> str:
        return "Network tools are disabled."

    def image_provider_ready(self) -> bool:
        return bool(settings.image_provider_url)

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        description = str(self.require(payload, "description")).strip()
        if not description:
            raise ToolError("description must not be empty")
        action = str(payload.get("action", "brief"))

        if action in ("generate", "variant"):
            if not self.image_provider_ready():
                return ToolResult(
                    status="UNAVAILABLE",
                    summary="Image generation provider is not configured (set LAIW_IMAGE_PROVIDER_URL).",
                    error="No image provider configured",
                    error_class="UNAVAILABLE",
                )
            return self._generate(ctx, payload, description)

        # brief / prompt engineering (LLM-backed, always honest)
        registry = getattr(ctx, "model_registry", None)
        if registry is None:
            from models.registry import registry as global_registry

            registry = global_registry
        prompt = (
            "You are a senior product designer. Return ONLY JSON with keys: "
            '"brief" (object: concept, audience, mood, palette[hex,...], typography, layout, deliverables[..]) '
            'and "prompts" (array of 1-4 detailed image-generation prompts). \n\n'
            f"Request: {description}\nStyle: {payload.get('style', '')}\nAspect ratio: {payload.get('aspect_ratio', '1:1')}"
        )
        completion = registry.complete([ChatMessage("user", prompt)], model=payload.get("model"), max_tokens=1500)
        text = completion.text
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ToolError("Model did not return a usable design brief", detail=text[:300])
        parsed = json.loads(text[start : end + 1])

        artifacts: list[dict[str, Any]] = []
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        artifact = ctx.save_artifact(
            f"design-brief-{stamp}.json",
            json.dumps(parsed, indent=2, ensure_ascii=False),
            "design",
            "application/json",
            "generated",
            {"action": action},
        )
        artifacts.append(artifact)
        return ToolResult(
            status="SUCCESS",
            summary=f"Design brief generated with {len(parsed.get('prompts', []))} prompt(s).",
            data={"action": action, "brief": parsed.get("brief", {}), "prompts": parsed.get("prompts", [])},
            artifacts=artifacts,
        )

    def _generate(self, ctx: ToolContext, payload: dict[str, Any], description: str) -> ToolResult:
        count = max(1, min(4, int(payload.get("variants", 1))))
        images: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        errors: list[str] = []
        for i in range(count):
            body: dict[str, Any] = {"prompt": description, "aspect_ratio": payload.get("aspect_ratio", "1:1"), "n": 1}
            if payload.get("base_image_url"):
                body["init_image_url"] = payload["base_image_url"]
            if payload.get("style"):
                body["style"] = payload["style"]
            try:
                resp = requests.post(
                    settings.image_provider_url,
                    headers={"Authorization": f"Bearer {settings.image_provider_key}", "Content-Type": "application/json"},
                    data=json.dumps(body),
                    timeout=settings.http_timeout_seconds * 4,
                )
            except requests.RequestException as exc:
                raise NetworkError("Image provider unreachable", detail=str(exc)) from exc
            if resp.status_code >= 400:
                errors.append(f"HTTP {resp.status_code}")
                continue
            ctype = resp.headers.get("Content-Type", "image/png")
            if "application/json" in ctype:
                data = resp.json()
                url = data.get("url") or (data.get("data") or [{}])[0].get("url")
                if url:
                    images.append({"variant": i + 1, "url": url})
                    continue
                b64 = (data.get("data") or [{}])[0].get("b64_json")
                if b64:
                    raw = base64.b64decode(b64)
                else:
                    errors.append("provider returned no image payload")
                    continue
            else:
                raw = resp.content
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
            artifact = ctx.save_artifact(f"image-{stamp}-{i + 1}.png", raw, "image", "image/png", "generated", {"prompt": description})
            artifacts.append(artifact)
            images.append({"variant": i + 1, "artifact_id": artifact["id"], "url": f"/api/artifacts/{artifact['id']}/content"})

        if not images:
            return ToolResult(status="UNAVAILABLE", summary="Image provider returned no images.", error="; ".join(errors), error_class="UNAVAILABLE")
        return ToolResult(status="SUCCESS", summary=f"{len(images)} image(s) generated.", data={"action": "generate", "images": images}, artifacts=artifacts)

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        if result.status == "SUCCESS":
            if result.data.get("action") == "generate":
                import os

                checks.append({"name": "images", "ok": bool(result.data.get("images")), "detail": f"{len(result.data.get('images', []))}"})
                for art in result.artifacts:
                    checks.append({"name": f"file:{art['name']}", "ok": os.path.exists(art["storage_path"]), "detail": f"{art.get('size', 0)} bytes"})
            else:
                checks.append({"name": "brief", "ok": bool(result.data.get("brief")), "detail": "design brief"})
                checks.append({"name": "prompts", "ok": bool(result.data.get("prompts")), "detail": f"{len(result.data.get('prompts', []))}"})
        return ValidationReport(valid=all(c["ok"] for c in checks), message="image validation")


__all__ = ["ImageTool"]
