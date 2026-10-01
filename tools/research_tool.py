"""Deep Research tool: multi-query evidence gathering + structured cited report."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from backend.app.core.errors import ToolError
from models.adapters import ChatMessage
from tools.base import BaseTool, Permission, ToolContext, ToolResult, ValidationReport
from tools.registry import register
from tools.search_backends import fetch_page_text, search_web

REPORT_SECTIONS = ["Introduction", "Key Findings", "Evidence", "Comparison", "Limitations", "Conclusion", "Sources"]


def _plan_queries(question: str, model_registry: Any, model: str | None) -> list[str]:
    """Derive focused sub-queries. Falls back to deterministic decomposition."""
    fallback = [
        question,
        f"{question} latest research",
        f"{question} comparison alternatives",
        f"{question} limitations challenges",
    ]
    try:
        prompt = (
            "Break the research question into 3-5 focused web search sub-queries. "
            'Return ONLY a JSON array of strings, no markdown.\n\nQuestion: ' + question
        )
        completion = model_registry.complete([ChatMessage("user", prompt)], model=model, max_tokens=400)
        text = completion.text.strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1:
            queries = json.loads(text[start : end + 1])
            queries = [str(q).strip() for q in queries if str(q).strip()]
            if queries:
                return queries[:5]
    except Exception:  # noqa: BLE001 - fallback is intentional and honest
        pass
    return fallback


@register
class ResearchTool(BaseTool):
    name = "research"
    description = "Run deep research: plan queries, search, collect/deduplicate sources, extract evidence, cross-check, and synthesise a cited report."
    category = "research"
    permissions = [Permission.READ, Permission.NETWORK, Permission.WEB, Permission.MODEL]
    cost_estimate = "high (network+model-tokens)"
    input_schema = {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "max_sources": {"type": "integer", "default": 12},
            "model": {"type": "string"},
            "produce_report": {"type": "boolean", "default": True},
        },
        "required": ["question"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "queries": {"type": "array"},
            "sources": {"type": "array"},
            "sections": {"type": "object"},
            "markdown": {"type": "string"},
            "artifacts": {"type": "array"},
        },
    }

    def availability(self, ctx: ToolContext | None = None) -> str:
        from configs.settings import settings

        return "AVAILABLE" if settings.enable_network_tools else "UNAVAILABLE"

    def unavailable_reason(self, ctx: ToolContext | None = None) -> str:
        return "Network tools are disabled; deep research requires web access."

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        question = self.require(payload, "question").strip()
        if not question:
            raise ToolError("Question must not be empty")
        max_sources = int(payload.get("max_sources", 12))
        model = payload.get("model")

        registry = getattr(ctx, "model_registry", None)
        if registry is None:
            from models.registry import registry as global_registry

            registry = global_registry

        queries = _plan_queries(question, registry, model)

        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        evidence: list[dict[str, Any]] = []
        errors: list[str] = []

        for q in queries:
            found, backend_errors = search_web(q, limit=6)
            errors.extend(backend_errors)
            for item in found:
                key = item.url.rstrip("/")
                if key in seen or not key.startswith("http"):
                    continue
                seen.add(key)
                sources.append(item.to_dict())
                if len(sources) >= max_sources:
                    break
            if len(sources) >= max_sources:
                break

        for src in sources[:8]:
            try:
                text = fetch_page_text(src["url"], max_chars=5000)
            except Exception:  # noqa: BLE001
                continue
            if text:
                evidence.append({"url": src["url"], "title": src["title"], "text": text[:3500]})

        report = {
            "Introduction": "",
            "Key Findings": [],
            "Evidence": [],
            "Comparison": "",
            "Limitations": "",
            "Conclusion": "",
            "Sources": [{"index": s["rank"], "title": s["title"], "url": s["url"]} for s in sources],
        }

        if sources:
            bundle = json.dumps({"question": question, "sources": sources, "evidence": evidence}, ensure_ascii=False)[:20000]
            prompt = (
                "You are a rigorous research analyst. Using ONLY the supplied sources and evidence, produce a JSON object with keys: "
                '"Introduction" (string), "Key Findings" (array of strings), "Evidence" (array of {claim, url} using supplied URLs only), '
                '"Comparison" (string), "Limitations" (string), "Conclusion" (string). '
                "Never invent URLs or facts. If data is missing, say so in Limitations. Return ONLY JSON.\n\n" + bundle
            )
            try:
                completion = registry.complete([ChatMessage("user", prompt)], model=model, max_tokens=3000)
                text = completion.text.strip()
                start, end = text.find("{"), text.rfind("}")
                if start != -1 and end != -1:
                    parsed = json.loads(text[start : end + 1])
                    for key in ("Introduction", "Key Findings", "Evidence", "Comparison", "Limitations", "Conclusion"):
                        if key in parsed and parsed[key]:
                            report[key] = parsed[key]
            except Exception as exc:  # noqa: BLE001
                errors.append(f"synthesis: {type(exc).__name__}")

        markdown = _render_markdown(question, report, sources, evidence)
        artifacts: list[dict[str, Any]] = []
        if payload.get("produce_report", True):
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
            artifact = ctx.save_artifact(
                name=f"research-{stamp}.md",
                payload=markdown,
                type_="research",
                mime_type="text/markdown",
                category="research",
                meta={"question": question, "sources": len(sources), "queries": queries},
            )
            artifacts.append(artifact)

        data = {
            "question": question,
            "queries": queries,
            "sources": sources,
            "evidence": evidence,
            "sections": report,
            "markdown": markdown,
            "backend_errors": errors,
        }
        return ToolResult(status="SUCCESS", summary=f"Research report generated with {len(sources)} sources.", data=data, artifacts=artifacts)

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        if result.status == "SUCCESS":
            md = result.data.get("markdown", "")
            for section in ("Introduction", "Key Findings", "Sources"):
                checks.append({"name": f"section:{section}", "ok": section.lower() in md.lower(), "detail": section})
            checks.append({"name": "artifacts", "ok": len(result.artifacts) >= 1, "detail": f"{len(result.artifacts)} artifact(s)"})
            for art in result.artifacts:
                import os

                checks.append({"name": "artifact_exists", "ok": os.path.exists(art.get("storage_path", "")), "detail": art.get("name", "")})
        return ValidationReport(valid=all(c["ok"] for c in checks), checks=checks, message="research validation")


def _render_markdown(question: str, report: dict[str, Any], sources: list[dict], evidence: list[dict]) -> str:
    lines = [f"# Research Report: {question}", "", f"_Generated {dt.datetime.now(dt.timezone.utc).isoformat()}_", ""]
    lines += ["## Introduction", report.get("Introduction") or f"This report investigates: {question}", ""]
    lines.append("## Key Findings")
    findings = report.get("Key Findings") or []
    if findings:
        lines += [f"- {f}" for f in findings]
    else:
        lines.append("_No findings were synthesised (insufficient sources or model unavailable)._")
    lines.append("")

    lines.append("## Evidence")
    ev = report.get("Evidence") or []
    if ev:
        for item in ev:
            if isinstance(item, dict):
                lines.append(f"- {item.get('claim', '')} — [{item.get('url', '')}]({item.get('url', '')})")
            else:
                lines.append(f"- {item}")
    elif evidence:
        for item in evidence[:6]:
            lines.append(f"- Excerpt from [{item['title']}]({item['url']}): {item['text'][:240].strip()}…")
    else:
        lines.append("_No evidence excerpts could be extracted._")
    lines.append("")

    lines += ["## Comparison", report.get("Comparison") or "_Not applicable._", ""]
    lines += ["## Limitations", report.get("Limitations") or "_Limitations were not assessed._", ""]
    lines += ["## Conclusion", report.get("Conclusion") or "_No conclusion could be drawn from the available sources._", ""]
    lines.append("## Sources")
    for s in sources:
        lines.append(f"{s['rank']}. [{s['title']}]({s['url']}) — {s.get('source', '')}")
    if not sources:
        lines.append("_No sources were collected._")
    return "\n".join(lines)


__all__ = ["ResearchTool", "REPORT_SECTIONS"]
