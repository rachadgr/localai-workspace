"""ModelRouter — selects a model by *task requirement*, never by provider name.

The Super Agent asks for a capability (e.g. "coding", "vision", "embedding") and
the router returns the best **available** model, with a deterministic fallback
ordering when several qualify, and an explicit, machine-readable outcome when
none do.

Design rules
------------
* **Availability is authoritative and runtime-only.** A model is a candidate only
  while its probed ``status`` is ``AVAILABLE``. ``NOT_CONFIGURED`` / ``UNAVAILABLE``
  / ``MISCONFIGURED`` / ``DISABLED`` / ``LOADING`` / ``ERROR`` models are never
  selected. Availability is never inferred from catalog membership.
* **Category alone is never proof.** A model's ``kind`` (category) only groups it;
  the task's *capability* and *modality* requirements are **hard constraints**
  every candidate must satisfy. This is what stops a chat-only model from being
  routed an image / vision / video / embedding task — and stops an image generator
  from being routed a text chat.
* **No false availability, no fabricated model.** If no AVAILABLE model satisfies
  the task's hard constraints the router returns ``model=None`` with an explicit
  outcome of :data:`OUTCOME_NO_CAPABLE_MODEL` (never a wrong-but-plausible pick).
* Local preference (``prefer_local``) is applied only *after* the hard gates, as a
  tie-break — it can never promote an otherwise ineligible model.
* Ordering is deterministic: a soft preference score, then ``(provider, id)``.
* The router performs **no network I/O** — it reads whatever the registry already
  probed (honouring the registry's own TTL). It never triggers a probe, never
  downloads weights and never calls a cloud API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.core.observability import get_logger
from models.base import (
    CAP_CHAT,
    CAP_CODE,
    CAP_EMBEDDINGS,
    CAP_IMAGE_GENERATION,
    CAP_LONG_CONTEXT,
    CAP_REASONING,
    CAP_STREAMING,
    CAP_TOOLS,
    CAP_VIDEO_GENERATION,
    CAP_VISION,
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_IMAGE,
    KIND_VIDEO,
    MODALITY_EMBEDDING,
    MODALITY_IMAGE,
    MODALITY_TEXT,
    MODALITY_VIDEO,
    STATUS_AVAILABLE,
)

logger = get_logger("model_router")

# --------------------------------------------------------------------------- #
# Routing outcomes (explicit, machine-readable verdicts)
# --------------------------------------------------------------------------- #
#: A candidate satisfying every hard constraint was found.
OUTCOME_SELECTED = "SELECTED"
#: No AVAILABLE model carried the required capability/modality for the task.
OUTCOME_NO_CAPABLE_MODEL = "NO_CAPABLE_MODEL"
#: The model registry itself could not be queried (no adapter / internal error).
OUTCOME_REGISTRY_UNAVAILABLE = "REGISTRY_UNAVAILABLE"

# --------------------------------------------------------------------------- #
# Task vocabulary → required category + hard capability/modality constraints
# --------------------------------------------------------------------------- #
#: Free-form text chat / any LLM.
TASK_CHAT = "chat"
#: Structured "text" task (alias of ``chat`` with the text modality enforced).
TASK_TEXT = "text"
#: Source-code generation / repair.
TASK_CODING = "coding"
#: Backwards-compatible alias of :data:`TASK_CODING`.
TASK_CODE = "code"
#: Long-form document synthesis (long context preferred).
TASK_DOCUMENT = "document"
#: Image *understanding* — a model that actually accepts image input.
TASK_VISION = "vision"
#: Image *generation* — a model that actually produces images.
TASK_IMAGE = "image"
#: Text embeddings.
TASK_EMBEDDING = "embedding"
#: Video generation (text-to-video).
TASK_VIDEO = "video"
#: Image-to-video generation.
TASK_I2V = "i2v"
#: Deep, multi-step reasoning.
TASK_REASONING = "reasoning"
#: Tool / function calling.
TASK_TOOLS = "tools"


@dataclass(frozen=True)
class TaskRequirement:
    """The hard + soft constraints a task imposes on candidate models.

    * ``kind`` — the model *category* the task belongs to (grouping only; on its
      own it is never a usability claim — the router also enforces ability).
    * ``required`` — capabilities a candidate **must** carry. A hard gate.
    * ``modalities`` — modalities a candidate **must** expose. A hard gate that
      keeps a text-only model out of an image / video / vision / embedding task.
    * ``preferred`` — capabilities that only *rank* qualifying candidates; they
      never admit a model that failed a hard gate.
    * ``context_min`` — soft minimum context length, applied only among models
      that already satisfy every hard gate.
    """

    kind: str
    required: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ()
    preferred: tuple[str, ...] = ()
    context_min: int = 0


TASK_REQUIREMENTS: dict[str, TaskRequirement] = {
    # ---- text / chat family: category + text-modality gate (no extra capability) #
    TASK_CHAT: TaskRequirement(KIND_CHAT, modalities=(MODALITY_TEXT,), preferred=(CAP_STREAMING,)),
    TASK_TEXT: TaskRequirement(KIND_CHAT, modalities=(MODALITY_TEXT,), preferred=(CAP_STREAMING,)),
    # ---- coding: a text model that *prefers* code/tools/reasoning (soft) -------- #
    TASK_CODING: TaskRequirement(KIND_CHAT, modalities=(MODALITY_TEXT,), preferred=(CAP_CODE, CAP_TOOLS, CAP_REASONING)),
    TASK_CODE: TaskRequirement(KIND_CHAT, modalities=(MODALITY_TEXT,), preferred=(CAP_CODE, CAP_TOOLS, CAP_REASONING)),
    # ---- document synthesis: long-context text model (context_min is soft) ------ #
    TASK_DOCUMENT: TaskRequirement(KIND_CHAT, modalities=(MODALITY_TEXT,), preferred=(CAP_LONG_CONTEXT, CAP_REASONING), context_min=32_000),
    # ---- vision analysis: MUST accept image input (hard capability gate) -------- #
    TASK_VISION: TaskRequirement(KIND_CHAT, required=(CAP_VISION,), modalities=(MODALITY_TEXT, MODALITY_IMAGE), preferred=(CAP_VISION,)),
    # ---- tool calling: MUST declare tools (hard capability gate) ---------------- #
    TASK_TOOLS: TaskRequirement(KIND_CHAT, required=(CAP_TOOLS,), modalities=(MODALITY_TEXT,), preferred=(CAP_TOOLS, CAP_REASONING)),
    # ---- deep reasoning: MUST declare reasoning (hard capability gate) ---------- #
    TASK_REASONING: TaskRequirement(KIND_CHAT, required=(CAP_REASONING,), modalities=(MODALITY_TEXT,), preferred=(CAP_REASONING, CAP_LONG_CONTEXT)),
    # ---- image generation: MUST actually generate images (hard gate) ------------ #
    TASK_IMAGE: TaskRequirement(KIND_IMAGE, required=(CAP_IMAGE_GENERATION,), modalities=(MODALITY_IMAGE,), preferred=(CAP_IMAGE_GENERATION,)),
    # ---- embedding: MUST produce embeddings (hard gate) ------------------------ #
    TASK_EMBEDDING: TaskRequirement(KIND_EMBEDDING, required=(CAP_EMBEDDINGS,), modalities=(MODALITY_EMBEDDING,), preferred=(CAP_EMBEDDINGS,)),
    # ---- video generation: MUST actually generate video (hard gate) ------------- #
    TASK_VIDEO: TaskRequirement(KIND_VIDEO, required=(CAP_VIDEO_GENERATION,), modalities=(MODALITY_VIDEO,), preferred=(CAP_VIDEO_GENERATION,)),
    # ---- image-to-video: a video generator that prefers image input ------------- #
    TASK_I2V: TaskRequirement(
        KIND_VIDEO,
        required=(CAP_VIDEO_GENERATION,),
        modalities=(MODALITY_VIDEO,),
        preferred=(CAP_VIDEO_GENERATION, MODALITY_IMAGE),
    ),
}


@dataclass
class RoutingDecision:
    task: str
    model: str | None
    provider: str = ""
    reason: str = ""
    candidates: list[str] = field(default_factory=list)
    #: Explicit verdict — :data:`OUTCOME_SELECTED` / :data:`OUTCOME_NO_CAPABLE_MODEL`
    #: / :data:`OUTCOME_REGISTRY_UNAVAILABLE`.
    outcome: str = OUTCOME_SELECTED
    #: The hard constraints enforced for this task (a debugging aid).
    required: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ()
    #: Sorted ``status:count`` of same-category models (diagnostic aid).
    excluded_status: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.model is not None

    @property
    def selected(self) -> bool:
        return self.outcome == OUTCOME_SELECTED and self.model is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model": self.model,
            "provider": self.provider,
            "available": self.available,
            "outcome": self.outcome,
            "reason": self.reason,
            "candidates": list(self.candidates),
            "required": list(self.required),
            "modalities": list(self.modalities),
            "excluded_status": list(self.excluded_status),
        }


class ModelRouter:
    """Deterministic, availability-aware model selection under hard constraints."""

    def __init__(self, model_registry: Any) -> None:
        self.registry = model_registry

    # ------------------------------------------------------------------ api
    def select(
        self,
        task: str,
        *,
        model_registry: Any = None,
        prefer_local: bool = False,
        exclude: set[str] | None = None,
        force_refresh: bool = False,
    ) -> RoutingDecision:
        registry = model_registry or self.registry
        requirement = requirement_for(task)
        exclude = exclude or set()

        try:
            models = registry.refresh(force=force_refresh)
        except Exception as exc:  # noqa: BLE001
            return self._no_capable(
                task,
                requirement,
                reason=f"registry unavailable: {exc}",
                outcome=OUTCOME_REGISTRY_UNAVAILABLE,
            )

        # 1. Candidate pool: AVAILABLE + correct category + every hard constraint.
        usable = [
            m
            for m in models.values()
            if m.status == STATUS_AVAILABLE
            and m.type == requirement.kind
            and m.id not in exclude
            and satisfies_requirements(m, requirement)
        ]

        if not usable:
            return self._no_capable(
                task,
                requirement,
                reason=self._no_capable_reason(task, requirement, models),
                excluded_status=self._status_histogram(models, requirement),
            )

        # 2. Soft ranking only — never admits a model that failed step 1.
        if requirement.context_min:
            preferred = [m for m in usable if (m.context_length or 0) >= requirement.context_min]
            usable = preferred or usable

        ordered = sorted(usable, key=lambda m: self._score(m, requirement, prefer_local))
        best = ordered[0]
        return RoutingDecision(
            task=task,
            model=best.id,
            provider=best.provider,
            reason=f"selected {best.id} ({best.provider}) for task '{task}'",
            candidates=[m.id for m in ordered],
            outcome=OUTCOME_SELECTED,
            required=requirement.required,
            modalities=requirement.modalities,
        )

    def candidates(self, task: str, *, prefer_local: bool = False, force_refresh: bool = False) -> list[str]:
        registry = self.registry
        requirement = requirement_for(task)
        models = registry.refresh(force=force_refresh)
        usable = [
            m
            for m in models.values()
            if m.status == STATUS_AVAILABLE
            and m.type == requirement.kind
            and satisfies_requirements(m, requirement)
        ]
        ordered = sorted(usable, key=lambda m: self._score(m, requirement, prefer_local))
        return [m.id for m in ordered]

    def plan(self, tasks: list[str], *, prefer_local: bool = False) -> dict[str, RoutingDecision]:
        return {task: self.select(task, prefer_local=prefer_local) for task in tasks}

    def resolve(self, task: str, explicit_model: str = "", *, prefer_local: bool = False) -> str | None:
        """Return an explicit model if it is usable, else route by task.

        An explicit model is honoured **only** when it is AVAILABLE *and* meets the
        task's hard constraints (category + capabilities + modalities); otherwise
        the router falls back to task routing (never a hard failure), returning
        ``None`` when nothing qualifies.
        """
        requirement = requirement_for(task)
        if explicit_model:
            info = self.registry.get(explicit_model)
            if (
                info is not None
                and info.status == STATUS_AVAILABLE
                and info.type == requirement.kind
                and satisfies_requirements(info, requirement)
            ):
                return explicit_model
            # Explicit but unusable / wrong capability → fall back to task routing.
        return self.select(task, prefer_local=prefer_local).model

    # -------------------------------------------------------------- scoring
    @staticmethod
    def _score(model: Any, requirement: TaskRequirement, prefer_local: bool) -> tuple[int, int, str, str]:
        caps = capabilities_of(model)
        mods = modalities_of(model)
        preference_hits = sum(1 for pref in requirement.preferred if pref in caps or pref in mods)
        local_rank = 0 if (prefer_local and model.local) else (1 if prefer_local else 0)
        # Negative preference so higher hits sort first; stable tiebreak by provider/id.
        return (-preference_hits, local_rank, model.provider or "", model.id or "")

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _no_capable(
        task: str,
        requirement: TaskRequirement,
        *,
        reason: str,
        outcome: str = OUTCOME_NO_CAPABLE_MODEL,
        excluded_status: list[str] | None = None,
    ) -> RoutingDecision:
        return RoutingDecision(
            task=task,
            model=None,
            reason=reason,
            outcome=outcome,
            required=requirement.required,
            modalities=requirement.modalities,
            excluded_status=excluded_status or [],
        )

    @staticmethod
    def _no_capable_reason(task: str, requirement: TaskRequirement, models: dict[str, Any]) -> str:
        """A precise, honest reason for a NO_CAPABLE_MODEL verdict.

        Distinguishes "nothing carries the capability" from "the capability exists
        but no *AVAILABLE* model provides it" — the common case when a matching
        model is NOT_CONFIGURED / UNAVAILABLE. Both start with *No AVAILABLE model*
        so callers can rely on the phrase.
        """
        hard = ", ".join((*requirement.required, *requirement.modalities)) or "any"
        kind_models = [m for m in models.values() if m.type == requirement.kind]
        capable_but_not_available = [
            m for m in kind_models if satisfies_requirements(m, requirement) and m.status != STATUS_AVAILABLE
        ]
        if capable_but_not_available:
            statuses = sorted({m.status for m in capable_but_not_available})
            return (
                f"No AVAILABLE model for task '{task}' (requires [{hard}]): "
                f"{len(capable_but_not_available)} capable model(s) are {', '.join(statuses)}"
            )
        return f"No AVAILABLE model for task '{task}': no model provides the required capability/modality [{hard}]"

    @staticmethod
    def _status_histogram(models: dict[str, Any], requirement: TaskRequirement) -> list[str]:
        """Sorted ``status:count`` of same-category models (diagnostic aid)."""
        counts: dict[str, int] = {}
        for m in models.values():
            if m.type != requirement.kind:
                continue
            counts[m.status] = counts.get(m.status, 0) + 1
        return [f"{status}:{counts[status]}" for status in sorted(counts)]


# --------------------------------------------------------------------------- #
# Constraint evaluation (public + testable)
# --------------------------------------------------------------------------- #
def requirement_for(task: str) -> TaskRequirement:
    """Return the requirement for ``task`` (defaults to a plain text-chat gate)."""
    return TASK_REQUIREMENTS.get(task) or TaskRequirement(KIND_CHAT, modalities=(MODALITY_TEXT,), preferred=(CAP_STREAMING,))


def capabilities_of(model: Any) -> set[str]:
    """The model's declared capabilities, normalised to a lowercase set."""
    return {str(c).lower() for c in (getattr(model, "capabilities", None) or [])}


def modalities_of(model: Any) -> set[str]:
    """The model's declared modalities, normalised to a lowercase set.

    Falls back to inferring from the model's kind + vision flag when no explicit
    modality list was surfaced, so discovery-only models stay routable without
    fabrication.
    """
    declared = {str(m).lower() for m in (getattr(model, "modality", None) or []) if m}
    if declared:
        return declared
    kind = getattr(model, "type", KIND_CHAT)
    vision = bool(getattr(model, "vision", False)) or CAP_VISION in capabilities_of(model)
    if kind == KIND_IMAGE:
        return {MODALITY_TEXT, MODALITY_IMAGE}
    if kind == KIND_VIDEO:
        return {MODALITY_TEXT, MODALITY_VIDEO}
    if kind == KIND_EMBEDDING:
        return {MODALITY_TEXT, MODALITY_EMBEDDING}
    return {MODALITY_TEXT, MODALITY_IMAGE} if vision else {MODALITY_TEXT}


def satisfies_requirements(model: Any, requirement: TaskRequirement) -> bool:
    """True when ``model`` carries **every** capability + modality a task requires.

    A task with no hard constraints imposes no extra gate (backwards compatible).
    This is the single gate that stops a chat-only model from being routed an
    image / vision / video / embedding task.
    """
    caps = capabilities_of(model)
    for cap in requirement.required:
        if cap not in caps:
            return False
    if requirement.modalities:
        mods = modalities_of(model)
        for modality in requirement.modalities:
            if modality not in mods:
                return False
    return True


#: Backwards-compatible private alias used by earlier tests/tools.
_satisfies_required = satisfies_requirements


__all__ = [
    "ModelRouter",
    "RoutingDecision",
    "TaskRequirement",
    "TASK_REQUIREMENTS",
    "requirement_for",
    "satisfies_requirements",
    "capabilities_of",
    "modalities_of",
    "OUTCOME_SELECTED",
    "OUTCOME_NO_CAPABLE_MODEL",
    "OUTCOME_REGISTRY_UNAVAILABLE",
    "TASK_CHAT",
    "TASK_TEXT",
    "TASK_CODING",
    "TASK_CODE",
    "TASK_DOCUMENT",
    "TASK_VISION",
    "TASK_IMAGE",
    "TASK_EMBEDDING",
    "TASK_VIDEO",
    "TASK_I2V",
    "TASK_REASONING",
    "TASK_TOOLS",
]
