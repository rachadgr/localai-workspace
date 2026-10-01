"""Generation Router — hard capability/modality gating for generation runtimes.

The Chat Router (:mod:`models.router`) selects *chat/vision/image/video* models for
the agent. The **Generation Router** is its additive counterpart for the generation
*runtimes* wired in this build: it validates that a generation request is genuinely
servable by the runtime it targets, enforcing the runtime's **hard** capability and
modality requirements.

Why a dedicated router?

* A generation runtime declares a *capability* (``video_generation``) and a set of
  *modalities* (e.g. ``image`` + ``video`` for an image-to-video model). These are
  hard gates, not hints. A runtime that cannot consume an image can never run I2V;
  an image generator can never satisfy a video task.
* This is what stops any chat / vision / image model from ever being asked to
  execute an image-to-video generation: only a runtime advertising the exact
  capability + modalities is admitted.

Honesty rules: the router performs **no** network I/O and loads **no** weights. It
only inspects the declarative runtime/adapter metadata, so it is safe to call on
startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.core.observability import get_logger
from models.base import (
    CAP_IMAGE_GENERATION,
    CAP_VIDEO_GENERATION,
    KIND_IMAGE,
    KIND_VIDEO,
    MODALITY_IMAGE,
    MODALITY_VIDEO,
)
from models.runtimes import SURFACE_IMAGE_TO_VIDEO, get_runtime, runtime_status

logger = get_logger("generation_router")

# --------------------------------------------------------------------------- #
# Task vocabulary
# --------------------------------------------------------------------------- #
#: Image-to-video generation (a video generator that consumes an image).
TASK_I2V = "i2v"
#: Text-to-video generation.
TASK_T2V = "t2v"
#: Image generation.
TASK_IMAGE = "image"

ALL_GENERATION_TASKS = (TASK_I2V, TASK_T2V, TASK_IMAGE)

# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #
#: The request can be served by a wired generation runtime.
OUTCOME_SELECTED = "SELECTED"
#: No wired runtime satisfies the task's hard capability/modality constraints.
OUTCOME_NO_CAPABLE_RUNTIME = "NO_CAPABLE_RUNTIME"
#: The request is malformed (unknown task / missing modality).
OUTCOME_INVALID_REQUEST = "INVALID_REQUEST"


@dataclass(frozen=True)
class GenerationRequirement:
    """The hard constraints a generation task imposes on a runtime.

    * ``required`` — capabilities the runtime **must** advertise (a hard gate).
    * ``modalities`` — modalities the runtime **must** expose (a hard gate).
    * ``kind`` — the model category the task belongs to (grouping only).
    """

    task: str
    required: tuple[str, ...]
    modalities: tuple[str, ...]
    kind: str = KIND_VIDEO


#: The single source of truth for generation task gating. Kept aligned with the
#: router vocabulary of :mod:`models.router` (``video`` / ``i2v`` / ``image``).
GENERATION_REQUIREMENTS: dict[str, GenerationRequirement] = {
    TASK_I2V: GenerationRequirement(
        task=TASK_I2V,
        required=(CAP_VIDEO_GENERATION,),
        # Image *input* + video *output*: the two modalities that define I2V.
        modalities=(MODALITY_IMAGE, MODALITY_VIDEO),
        kind=KIND_VIDEO,
    ),
    TASK_T2V: GenerationRequirement(
        task=TASK_T2V,
        required=(CAP_VIDEO_GENERATION,),
        modalities=(MODALITY_VIDEO,),
        kind=KIND_VIDEO,
    ),
    TASK_IMAGE: GenerationRequirement(
        task=TASK_IMAGE,
        required=(CAP_IMAGE_GENERATION,),
        modalities=(MODALITY_IMAGE,),
        kind=KIND_IMAGE,
    ),
}


@dataclass
class GenerationRoutingDecision:
    """The outcome of a generation-routing check (explicit + machine-readable)."""

    task: str
    runtime: str | None = None
    adapter: str = ""
    model: str = ""
    outcome: str = OUTCOME_NO_CAPABLE_RUNTIME
    reason: str = ""
    required: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ()
    supported: bool = False

    @property
    def selected(self) -> bool:
        return self.outcome == OUTCOME_SELECTED and bool(self.runtime)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "runtime": self.runtime,
            "adapter": self.adapter,
            "model": self.model,
            "outcome": self.outcome,
            "reason": self.reason,
            "required": list(self.required),
            "modalities": list(self.modalities),
            "supported": self.supported,
        }


def requirement_for_generation(task: str) -> GenerationRequirement:
    """Return the hard requirement for a generation task (defaults to I2V's gate)."""
    return GENERATION_REQUIREMENTS.get(task) or GENERATION_REQUIREMENTS[TASK_I2V]


def runtime_satisfies(adapter: Any, requirement: GenerationRequirement) -> tuple[bool, list[str], list[str]]:
    """Check a wired runtime/adapter against ``requirement`` (pure, no I/O).

    Returns ``(ok, capabilities, modalities)`` where the capability/modality lists
    are the adapter's *declared* surface (normalised lowercase).
    """
    caps = {str(c).lower() for c in (getattr(adapter, "declared_capabilities", None) or [getattr(adapter, "capability", "")]) if c}
    mods = {str(m).lower() for m in (getattr(adapter, "declared_modalities", None) or getattr(adapter, "required_modalities", ()) or ()) if m}
    ok = all(c in caps for c in requirement.required) and all(m in mods for m in requirement.modalities)
    return ok, sorted(caps), sorted(mods)


class GenerationRouter:
    """Selects a **wired generation runtime** under hard capability/modality gates.

    The router only ever considers the generation runtimes registered in the runtime
    matrix (via the local generation manager). A runtime must be ``supported`` *and*
    expose the exact capabilities/modalities the task demands — a chat, vision or
    image model can never be selected for an image-to-video request.
    """

    def __init__(self, manager: Any = None) -> None:
        self._manager = manager

    def _manager_or_default(self) -> Any:
        if self._manager is not None:
            return self._manager
        from models.generation_runtime import get_local_generation_manager

        return get_local_generation_manager()

    # ------------------------------------------------------------------ api
    def select(self, task: str, *, model_id: str = "") -> GenerationRoutingDecision:
        requirement = requirement_for_generation(task)
        if task not in GENERATION_REQUIREMENTS:
            return GenerationRoutingDecision(
                task=task,
                outcome=OUTCOME_INVALID_REQUEST,
                reason=f"Unknown generation task '{task}'",
                required=requirement.required,
                modalities=requirement.modalities,
            )

        try:
            manager = self._manager_or_default()
            adapters = dict(getattr(manager, "adapters", {}) or {})
        except Exception as exc:  # noqa: BLE001 - never crash a caller
            return GenerationRoutingDecision(
                task=task,
                outcome=OUTCOME_NO_CAPABLE_RUNTIME,
                reason=f"generation runtime unavailable: {exc}",
                required=requirement.required,
                modalities=requirement.modalities,
            )

        if not adapters:
            return GenerationRoutingDecision(
                task=task,
                outcome=OUTCOME_NO_CAPABLE_RUNTIME,
                reason="No generation runtime is wired in this build",
                required=requirement.required,
                modalities=requirement.modalities,
            )

        for runtime_id, adapter in adapters.items():
            model = getattr(adapter, "model_id", "") or ""
            if model_id and model != model_id:
                continue
            supported, _reason = runtime_status(runtime_id)
            descriptor = get_runtime(runtime_id)
            surface_ok = bool(descriptor and _surface_for_task(task) in descriptor.surfaces)
            ok, caps, mods = runtime_satisfies(adapter, requirement)
            if supported and surface_ok and ok:
                return GenerationRoutingDecision(
                    task=task,
                    runtime=runtime_id,
                    adapter=getattr(adapter, "name", ""),
                    model=model,
                    outcome=OUTCOME_SELECTED,
                    reason=f"runtime '{runtime_id}' satisfies [{', '.join((*requirement.required, *requirement.modalities))}]",
                    required=requirement.required,
                    modalities=requirement.modalities,
                    supported=True,
                )

        return GenerationRoutingDecision(
            task=task,
            outcome=OUTCOME_NO_CAPABLE_RUNTIME,
            reason=(
                "No wired runtime exposes the required capability/modality "
                f"[{', '.join((*requirement.required, *requirement.modalities))}]"
            ),
            required=requirement.required,
            modalities=requirement.modalities,
        )

    def can_serve(self, task: str, *, model_id: str = "") -> bool:
        return self.select(task, model_id=model_id).selected


def _surface_for_task(task: str) -> str:
    if task == TASK_I2V:
        return SURFACE_IMAGE_TO_VIDEO
    from models.runtimes import SURFACE_IMAGE_GENERATION, SURFACE_VIDEO_GENERATION

    if task == TASK_IMAGE:
        return SURFACE_IMAGE_GENERATION
    return SURFACE_VIDEO_GENERATION


__all__ = [
    "TASK_I2V",
    "TASK_T2V",
    "TASK_IMAGE",
    "ALL_GENERATION_TASKS",
    "OUTCOME_SELECTED",
    "OUTCOME_NO_CAPABLE_RUNTIME",
    "OUTCOME_INVALID_REQUEST",
    "GenerationRequirement",
    "GENERATION_REQUIREMENTS",
    "GenerationRoutingDecision",
    "GenerationRouter",
    "requirement_for_generation",
    "runtime_satisfies",
]
