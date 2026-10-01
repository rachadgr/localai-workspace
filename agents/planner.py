"""Planner: turns a natural-language request into an ordered, validated plan.

No tool selection happens here — the Router owns that. The Planner is
responsible for intent, context assembly and step decomposition.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from backend.app.core.observability import get_logger
from models.adapters import ChatMessage

logger = get_logger("planner")

# Deterministic, high-confidence intent signals (used before falling back to an LLM).
INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("slides", ["slide", "slides", "deck", "powerpoint", "pptx", "presentation", "pres", "عرض تقديمي", "شرائح"]),
    ("sheets", ["spreadsheet", "sheet", "xlsx", "excel", "csv", "table of data", "pivot", "جدول بيانات", "اكسل"]),
    ("docs", ["document", "docx", "pdf", "report as a", "write a report", "white paper", "مستند", "تقرير"]),
    ("research", ["deep research", "research", "investigate", "literature", "state of the art", "بحث", "تحقيق"]),
    ("website", ["website", "landing page", "web page", "html site", "portfolio site", "موقع", "صفحة ويب"]),
    ("developer", ["code", "function", "script", "bug", "debug", "unit test", "refactor", "api endpoint", "برمجة", "كود"]),
    ("design", ["image", "logo", "illustration", "design brief", "poster", "thumb", "mockup", "صورة", "تصميم"]),
    ("search", ["search", "look up", "find information", "latest news", "google", "ابحث", "بحث عن"]),
]

TOOL_BY_INTENT = {
    "slides": "slides",
    "sheets": "sheets",
    "docs": "docs",
    "research": "research",
    "website": "website",
    "developer": "developer",
    "design": "image",
    "search": "search",
    "chat": "chat",
}


@dataclass
class PlanStep:
    index: int
    name: str
    tool: str
    description: str
    inputs: dict[str, Any] = field(default_factory=dict)
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "tool": self.tool,
            "description": self.description,
            "inputs": self.inputs,
            "optional": self.optional,
        }


@dataclass
class Plan:
    intent: str
    title: str
    steps: list[PlanStep]
    context: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "title": self.title,
            "steps": [s.to_dict() for s in self.steps],
            "context": self.context,
            "notes": self.notes,
            "source": self.source,
        }

    @property
    def tools(self) -> list[str]:
        seen: list[str] = []
        for step in self.steps:
            if step.tool not in seen:
                seen.append(step.tool)
        return seen


class Planner:
    def __init__(self, tool_registry: Any, model_registry: Any, memory: Any = None) -> None:
        self.tools = tool_registry
        self.models = model_registry
        self.memory = memory

    # ------------------------------------------------------------ intent
    def detect_intent(self, request: str) -> str:
        text = request.lower()
        scores: dict[str, int] = {}
        for intent, keywords in INTENT_KEYWORDS:
            score = 0
            for kw in keywords:
                if kw in text:
                    score += len(kw.split()) * 2
            if score:
                scores[intent] = score
        # "research" supersedes "search" when both apply.
        if "research" in scores and "search" in scores:
            scores.pop("search")
        if not scores:
            return "chat"
        return max(scores.items(), key=lambda kv: kv[1])[0]

    # ------------------------------------------------------------ planning
    def plan(self, request: str, context: dict[str, Any] | None = None) -> Plan:
        context = context or {}
        intent = self.detect_intent(request)
        title = _derive_title(request)

        try:
            llm_plan = self._llm_plan(request, intent, context)
        except Exception as exc:  # noqa: BLE001 - degrade to deterministic plan
            logger.debug("LLM planning unavailable (%s); using deterministic plan", exc)
            llm_plan = None

        if llm_plan and llm_plan.steps:
            steps = []
            for i, raw in enumerate(llm_plan.steps):
                tool = raw.get("tool", "")
                if not self.tools.has(tool):
                    continue
                steps.append(
                    PlanStep(
                        index=i,
                        name=str(raw.get("name", raw.get("description", tool))),
                        tool=tool,
                        description=str(raw.get("description", "")),
                        inputs=raw.get("inputs", {}) if isinstance(raw.get("inputs"), dict) else {},
                        optional=bool(raw.get("optional", False)),
                    )
                )
            if steps:
                steps = _renumber(steps)
                return Plan(intent=llm_plan.intent, title=title, steps=steps, context=context, notes=llm_plan.notes, source="llm")

        steps = self._deterministic_plan(intent, request, context)
        return Plan(intent=intent, title=title, steps=steps, context=context, notes="Deterministic plan (LLM planning unavailable or unnecessary).", source="deterministic")

    def _deterministic_plan(self, intent: str, request: str, context: dict[str, Any]) -> list[PlanStep]:
        steps: list[PlanStep] = []
        if intent == "research":
            steps.append(
                PlanStep(
                    index=0,
                    name="Deep research & cited report",
                    tool="research",
                    description="Plan queries, gather/deduplicate sources, extract evidence and synthesise a cited report.",
                    inputs={"question": request, "max_sources": 12},
                )
            )
            if context.get("also_make_slides"):
                steps.append(
                    PlanStep(
                        index=1,
                        name="Executive deck from research",
                        tool="slides",
                        description="Turn the research report into a presentation.",
                        inputs={"title": _derive_title(request), "prompt": request, "target_slides": 10},
                    )
                )
            elif _mentions(request, ["deck", "slide", "presentation", "pptx"]):
                steps.append(
                    PlanStep(
                        index=1,
                        name="Executive deck from research",
                        tool="slides",
                        description="Turn the research report into a presentation.",
                        inputs={"title": _derive_title(request), "prompt": request, "target_slides": 10},
                    )
                )
        elif intent == "slides":
            steps.append(
                PlanStep(
                    index=0,
                    name="Generate presentation",
                    tool="slides",
                    description="Generate an 8–12 slide deck with speaker notes.",
                    inputs={"title": _derive_title(request), "prompt": request, "target_slides": _target_slides(request)},
                )
            )
        elif intent == "sheets":
            steps.append(
                PlanStep(
                    index=0,
                    name="Build workbook",
                    tool="sheets",
                    description="Create a CSV/XLSX workbook with statistics and charts.",
                    inputs={"title": _derive_title(request), "generate_sample": _wants_sample(request), "rows": context.get("rows") or [], "columns": context.get("columns") or []},
                )
            )
        elif intent == "docs":
            fmt = "docx" if _mentions(request, ["docx", "word"]) else ("pdf" if _mentions(request, ["pdf"]) else "md")
            steps.append(
                PlanStep(
                    index=0,
                    name="Write document",
                    tool="docs",
                    description=f"Generate a professional document ({fmt}).",
                    inputs={"title": _derive_title(request), "prompt": request, "format": fmt},
                )
            )
        elif intent == "website":
            steps.append(
                PlanStep(
                    index=0,
                    name="Build website",
                    tool="website",
                    description="Design and implement a responsive, accessible static site.",
                    inputs={"prompt": request, "site_name": _slug(_derive_title(request))},
                )
            )
        elif intent == "developer":
            steps.append(
                PlanStep(
                    index=0,
                    name="Implement and test code",
                    tool="developer",
                    description="Implement, run real tests, fix failures and validate.",
                    inputs={"task": request, "language": context.get("language", "python")},
                )
            )
        elif intent == "design":
            steps.append(
                PlanStep(
                    index=0,
                    name="Design brief & prompts",
                    tool="image",
                    description="Produce a design brief and image prompts (or generate images if a provider is configured).",
                    inputs={"description": request, "action": "brief"},
                )
            )
        elif intent == "search":
            steps.append(
                PlanStep(
                    index=0,
                    name="Web search with citations",
                    tool="search",
                    description="Search, deduplicate sources, extract evidence and summarise with citations.",
                    inputs={"query": request, "limit": 8},
                )
            )
            if _mentions(request, ["report", "document", "summary doc"]):
                steps.append(
                    PlanStep(
                        index=1,
                        name="Export findings to document",
                        tool="docs",
                        description="Save the search findings as a document.",
                        inputs={"title": _derive_title(request), "prompt": request, "format": "md"},
                        optional=True,
                    )
                )
        else:
            steps.append(
                PlanStep(
                    index=0,
                    name="Answer question",
                    tool="chat",
                    description="Answer the user's request directly.",
                    inputs={"message": request},
                )
            )
        return _renumber(steps)

    # -------------------------------------------------------------- LLM plan
    def _llm_plan(self, request: str, intent: str, context: dict[str, Any]) -> Plan | None:
        if not self.models:
            return None
        self.models.refresh()
        if not self.models.chat_models():
            return None

        tool_docs = []
        for tool in self.tools.all():
            tool_docs.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "category": tool.category,
                    "inputs": list((tool.input_schema.get("properties") or {}).keys()),
                    "availability": tool.availability(),
                }
            )
        prompt = (
            "You are the planner of an AI workspace. Decompose the user request into the FEWEST steps that fully satisfy it, "
            "choosing tools ONLY from the registry below. Return ONLY JSON: "
            '{"intent": string, "steps": [{"name": string, "tool": string, "description": string, "inputs": object, "optional": bool}], "notes": string}. '
            "Rules: prefer a single tool when enough; chain 'research'->'slides' or 'research'->'docs' only when the user asks for both. "
            "Never invent tools. Inputs must match the tool's declared input keys. If a needed tool is UNAVAILABLE, still plan it but note it in 'notes'.\n\n"
            f"Tool registry:\n{json.dumps(tool_docs, ensure_ascii=False)}\n\n"
            f"Request: {request}\nDetected intent hint: {intent}"
        )
        completion = self.models.complete([ChatMessage("user", prompt)], model=self.models.default_chat_model(), max_tokens=1200)
        text = completion.text
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        raw_steps = parsed.get("steps") or []
        steps: list[PlanStep] = []
        for i, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                continue
            tool = str(raw.get("tool", "")).strip()
            if not tool:
                continue
            steps.append(
                PlanStep(
                    index=i,
                    name=str(raw.get("name") or raw.get("description") or tool),
                    tool=tool,
                    description=str(raw.get("description", "")),
                    inputs=raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {},
                    optional=bool(raw.get("optional", False)),
                )
            )
        if not steps:
            return None
        return Plan(intent=str(parsed.get("intent", intent)), title=_derive_title(request), steps=steps, context=context, notes=str(parsed.get("notes", "")), source="llm")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _renumber(steps: list[PlanStep]) -> list[PlanStep]:
    for i, step in enumerate(steps):
        step.index = i
    return steps


def _mentions(text: str, needles: list[str]) -> bool:
    lower = text.lower()
    return any(n in lower for n in needles)


def _wants_sample(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in ("sample data", "example data", "demo data", "fake data", "بيانات تجريبية", "بيانات عشوائية"))


def _target_slides(text: str) -> int:
    match = re.search(r"(\d+)\s*(slides|slide|شرائح)", text.lower())
    if match:
        return max(8, min(12, int(match.group(1))))
    return 10


def _derive_title(request: str) -> str:
    first = re.split(r"[\n\.\?\!]", request.strip())[0].strip()
    if len(first) > 90:
        first = first[:87].rstrip() + "..."
    return first or "Untitled"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or "site"


__all__ = ["Planner", "Plan", "PlanStep", "TOOL_BY_INTENT", "INTENT_KEYWORDS"]
