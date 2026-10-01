"""ModelRouter — selects a model by *task requirement*, never by provider name.

The Super Agent asks for a capability (e.g. "code", "vision", "embedding") and
the router returns the best **available** model, with a deterministic fallback
ordering when several are available and a clear reason when none are.

Design rules
------------
* Never select a model that is not ``AVAILABLE`` (UNAVAILABLE / MISCONFIGURED /
  DISABLED / LOADING / ERROR are all excluded).
* Prefer local models when ``prefer_local`` is set (privacy / zero-egress).
* Ordering is deterministic: a task-specific preference score first, then
  ``(provider, id)`` so results are stable across runs.
* Never invent a model: if nothing qualifies, ``select`` returns ``None`` and the
  caller degrades honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.core.observability import get_logger
from models.base import (
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
    STATUS_AVAILABLE,
)

logger = get_logger("model_router")

# --------------------------------------------------------------------------- #
# Task vocabulary → required kind + preferred capabilities
# --------------------------------------------------------------------------- #
TASK_CHAT = "chat"
TASK_CODE = "code"
TASK_DOCUMENT = "document"
TASK_VISION = "vision"
TASK_IMAGE = "image"
TASK_EMBEDDING = "embedding"
TASK_VIDEO = "video"
TASK_REASONING = "reasoning"
TASK_TOOLS = "tools"


@dataclass(frozen=True)
class TaskRequirement:
    kind: str
    preferred: tuple[str, ...] = ()
    context_min: int = 0
    #: Capabilities a candidate **must** carry. This is a hard gate: it stops the
    #: router from ever sending an image/video/vision task to a chat-only model.
    required: tuple[str, ...] = ()


TASK_REQUIREMENTS: dict[str, TaskRequirement] = {
    # chat → any LLM
    TASK_CHAT: TaskRequirement(KIND_CHAT, preferred=(CAP_STREAMING,)),
    # code → coding / tool-use model
    TASK_CODE: TaskRequirement(KIND_CHAT, preferred=(CAP_CODE, CAP_TOOLS, CAP_REASONING)),
    # document synthesis → long-context LLM
    TASK_DOCUMENT: TaskRequirement(KIND_CHAT, preferred=(CAP_LONG_CONTEXT, CAP_REASONING), context_min=32_000),
    # vision analysis → a model that *actually* accepts image input (hard gate)
    TASK_VISION: TaskRequirement(KIND_CHAT, preferred=(CAP_VISION,), required=(CAP_VISION,)),
    # tool calling → tools model
    TASK_TOOLS: TaskRequirement(KIND_CHAT, preferred=(CAP_TOOLS, CAP_REASONING)),
    # deep reasoning → reasoning model
    TASK_REASONING: TaskRequirement(KIND_CHAT, preferred=(CAP_REASONING, CAP_LONG_CONTEXT)),
    # image generation → a model that *actually* generates images (hard gate)
    TASK_IMAGE: TaskRequirement(KIND_IMAGE, preferred=(CAP_IMAGE_GENERATION,), required=(CAP_IMAGE_GENERATION,)),
    # embedding → embedding model
    TASK_EMBEDDING: TaskRequirement(KIND_EMBEDDING, preferred=(CAP_EMBEDDINGS,), required=(CAP_EMBEDDINGS,)),
    # video generation → a model that *actually* generates video (hard gate)
    TASK_VIDEO: TaskRequirement(KIND_VIDEO, preferred=(CAP_VIDEO_GENERATION,), required=(CAP_VIDEO_GENERATION,)),
}


@dataclass
class RoutingDecision:
    task: str
    model: str | None
    provider: str = ""
    reason: str = ""
    candidates: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.model is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model": self.model,
            "provider": self.provider,
            "available": self.available,
            "reason": self.reason,
            "candidates": list(self.candidates),
        }


class ModelRouter:
    """Deterministic, availability-aware model selection."""

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
        requirement = TASK_REQUIREMENTS.get(task)
        if requirement is None:
            requirement = TaskRequirement(KIND_CHAT)
        exclude = exclude or set()

        try:
            models = registry.refresh(force=force_refresh)
        except Exception as exc:  # noqa: BLE001
            return RoutingDecision(task=task, model=None, reason=f"registry unavailable: {exc}")

        usable = [
            m
            for m in models.values()
            if m.status == STATUS_AVAILABLE
            and m.type == requirement.kind
            and m.id not in exclude
            and _satisfies_required(m, requirement)
        ]
        if requirement.context_min:
            usable = [m for m in usable if (m.context_length or 0) >= requirement.context_min] or usable

        if not usable:
            return RoutingDecision(
                task=task,
                model=None,
                reason=f"No AVAILABLE model for task '{task}' (kind={requirement.kind})",
            )

        ordered = sorted(usable, key=lambda m: self._score(m, requirement, prefer_local))
        best = ordered[0]
        return RoutingDecision(
            task=task,
            model=best.id,
            provider=best.provider,
            reason=f"selected {best.id} ({best.provider}) for task '{task}'",
            candidates=[m.id for m in ordered],
        )

    def candidates(self, task: str, *, prefer_local: bool = False, force_refresh: bool = False) -> list[str]:
        registry = self.registry
        requirement = TASK_REQUIREMENTS.get(task, TaskRequirement(KIND_CHAT))
        models = registry.refresh(force=force_refresh)
        usable = [
            m
            for m in models.values()
            if m.status == STATUS_AVAILABLE
            and m.type == requirement.kind
            and _satisfies_required(m, requirement)
        ]
        ordered = sorted(usable, key=lambda m: self._score(m, requirement, prefer_local))
        return [m.id for m in ordered]

    def plan(self, tasks: list[str], *, prefer_local: bool = False) -> dict[str, RoutingDecision]:
        return {task: self.select(task, prefer_local=prefer_local) for task in tasks}

    def resolve(self, task: str, explicit_model: str = "", *, prefer_local: bool = False) -> str | None:
        """Return an explicit model if it is usable, else route by task."""
        if explicit_model:
            info = self.registry.get(explicit_model)
            if info is not None and info.status == STATUS_AVAILABLE:
                return explicit_model
            # Explicit but unusable → fall back to task routing rather than fail.
            decision = self.select(task, prefer_local=prefer_local)
            return decision.model
        decision = self.select(task, prefer_local=prefer_local)
        return decision.model

    # -------------------------------------------------------------- scoring
    @staticmethod
    def _score(model: Any, requirement: TaskRequirement, prefer_local: bool) -> tuple[int, int, str, str]:
        caps = set(model.capabilities or [])
        preference_hits = sum(1 for cap in requirement.preferred if cap in caps)
        local_rank = 0 if (prefer_local and model.local) else (1 if prefer_local else 0)
        # Negative preference so higher hits sort first; stable tiebreak by provider/id.
        return (-preference_hits, local_rank, model.provider or "", model.id or "")


def _satisfies_required(model: Any, requirement: TaskRequirement) -> bool:
    """True when ``model`` carries **every** capability the task requires.

    A task with no ``required`` capabilities imposes no extra gate (backwards
    compatible). This is what stops a chat-only model from being routed an
    image / video / vision task.
    """
    if not requirement.required:
        return True
    caps = set(model.capabilities or [])
    return all(cap in caps for cap in requirement.required)


__all__ = [
    "ModelRouter",
    "RoutingDecision",
    "TaskRequirement",
    "TASK_REQUIREMENTS",
    "TASK_CHAT",
    "TASK_CODE",
    "TASK_DOCUMENT",
    "TASK_VISION",
    "TASK_IMAGE",
    "TASK_EMBEDDING",
    "TASK_VIDEO",
    "TASK_REASONING",
    "TASK_TOOLS",
]
