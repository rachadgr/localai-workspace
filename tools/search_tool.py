"""AI Search tool: web search, source collection, dedup, evidence, summary, citations."""

from __future__ import annotations

import json
from typing import Any

from backend.app.core.errors import ToolError
from models.adapters import ChatMessage
from tools.base import BaseTool, Permission, ToolContext, ToolResult, ValidationReport
from tools.registry import register
from tools.search_backends import fetch_page_text, search_web


@register
class SearchTool(BaseTool):
    name = "search"
    description = "Search the web, collect and deduplicate sources, extract evidence snippets, and produce a cited summary."
    category = "search"
    permissions = [Permission.READ, Permission.NETWORK, Permission.WEB, Permission.MODEL]
    cost_estimate = "network+model-tokens"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 8},
            "fetch_pages": {"type": "boolean", "default": True, "description": "Fetch and extract evidence from top pages"},
            "summarize": {"type": "boolean", "default": True},
            "model": {"type": "string"},
        },
        "required": ["query"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "sources": {"type": "array"},
            "evidence": {"type": "array"},
            "summary": {"type": "string"},
            "citations": {"type": "array"},
        },
    }

    def availability(self, ctx: ToolContext | None = None) -> str:
        from configs.settings import settings

        return "AVAILABLE" if settings.enable_network_tools else "UNAVAILABLE"

    def unavailable_reason(self, ctx: ToolContext | None = None) -> str:
        return "Network tools are disabled (LAIW_ENABLE_NETWORK_TOOLS=false)."

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        query = self.require(payload, "query").strip()
        if not query:
            raise ToolError("Query must not be empty")
        limit = int(payload.get("limit", 8))
        fetch_pages = bool(payload.get("fetch_pages", True))
        summarize = bool(payload.get("summarize", True))

        results, backend_errors = search_web(query, limit=limit)
        sources = [r.to_dict() for r in results]

        evidence: list[dict[str, Any]] = []
        if fetch_pages and results:
            for item in results[: min(5, len(results))]:
                try:
                    text = fetch_page_text(item.url, max_chars=6000)
                except Exception:  # noqa: BLE001
                    continue
                if text:
                    evidence.append({"url": item.url, "title": item.title, "text": text[:4000]})

        summary = ""
        if summarize and results:
            registry = getattr(ctx, "model_registry", None)
            if registry is None:
                from models.registry import registry as global_registry

                registry = global_registry
            bundle = json.dumps({"query": query, "sources": sources[:8], "evidence": evidence[:5]}, ensure_ascii=False)[:14000]
            prompt = (
                "Summarise the search findings for the query below using ONLY the supplied sources. "
                "Cite sources inline as [n] matching their position in the sources list. "
                "If the sources are insufficient, state that explicitly. Do not invent facts or URLs.\n\n"
                f"Query: {query}\n\nData (JSON):\n{bundle}"
            )
            try:
                completion = registry.complete([ChatMessage("user", prompt)], model=payload.get("model"))
                summary = completion.text
            except Exception as exc:  # noqa: BLE001
                summary = ""
                backend_errors.append(f"summary: {type(exc).__name__}")

        citations = [{"index": s["rank"], "title": s["title"], "url": s["url"]} for s in sources]

        if not sources:
            backend_errors = [e for e in backend_errors if not e.endswith(": unavailable")]
            all_backends_failed = bool(backend_errors) and all(":" in e for e in backend_errors)
            if all_backends_failed:
                return ToolResult(
                    status="UNAVAILABLE",
                    summary="All search backends are unreachable from this environment; no results could be retrieved.",
                    error="; ".join(backend_errors),
                    error_class="NetworkError",
                    data={"query": query, "sources": [], "evidence": [], "summary": "", "citations": [], "backend_errors": backend_errors},
                )
            return ToolResult(
                status="SUCCESS",
                summary=f"No sources found for '{query}'.",
                data={"query": query, "sources": [], "evidence": [], "summary": "", "citations": [], "backend_errors": backend_errors},
            )

        return ToolResult(
            status="SUCCESS",
            summary=f"{len(sources)} sources collected for '{query}'.",
            data={
                "query": query,
                "sources": sources,
                "evidence": evidence,
                "summary": summary,
                "citations": citations,
                "backend_errors": backend_errors,
            },
        )

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        if result.status == "SUCCESS":
            sources = result.data.get("sources", [])
            checks.append({"name": "sources_unique", "ok": len({s["url"] for s in sources}) == len(sources), "detail": f"{len(sources)} sources"})
            checks.append({"name": "citations_match", "ok": len(result.data.get("citations", [])) == len(sources), "detail": "citations derived from sources"})
            for s in sources:
                if not str(s.get("url", "")).startswith("http"):
                    checks.append({"name": "url_valid", "ok": False, "detail": f"invalid url {s.get('url')}"})
                    break
        return ValidationReport(valid=all(c["ok"] for c in checks), checks=checks, message="search validation")


__all__ = ["SearchTool"]
