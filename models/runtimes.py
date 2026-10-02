"""Runtime matrix — which runtimes this workspace can *actually* serve models with.

Why a separate module?
----------------------
A catalog model id alone does not say *how* it is served. ``qwen3:4b`` is served by
the local Ollama runtime; ``Qwen/Qwen-Image`` is an open-weight diffusion model that
would need a local ``diffusers`` runtime; ``gpt-5`` is served by a hosted HTTP API.
This module is the single, declarative place that records, per runtime:

* its human label and whether models it serves run **locally** (no egress);
* the **adapter** wired in this build (a :class:`models.base.ModelAdapter` subclass
  name) — ``""`` when no adapter exists yet;
* **which modalities/tasks** the runtime can serve;
* whether it is **supported** right now, and — when it is not — a *clear reason*.

Honesty rules (identical spirit to the catalog / registry / local activation):

* This module is **declarative and inert**: no network I/O, no imports of a
  networking library, no weights, no credentials.
* A runtime with no wired adapter is reported ``supported = False`` with a reason
  rather than being faked. Models that *would* be served by it are therefore
  reported ``NOT_CONFIGURED`` downstream (see :mod:`models.generation` and
  :mod:`models.provisioning`) — never ``AVAILABLE``.
* Support is a property of *this build*, not a promise about the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from models.base import (
    CAP_EMBEDDINGS,
    CAP_IMAGE_GENERATION,
    CAP_VIDEO_GENERATION,
    MODALITY_EMBEDDING,
    MODALITY_IMAGE,
    MODALITY_TEXT,
    MODALITY_VIDEO,
)

# --------------------------------------------------------------------------- #
# Runtime identifiers (stable label vocabulary)
# --------------------------------------------------------------------------- #
RUNTIME_OLLAMA = "ollama"
RUNTIME_LOCALAI = "localai"
RUNTIME_DIFFUSERS = "diffusers"
RUNTIME_WAN_I2V = "wan_i2v"
RUNTIME_OPENAI_COMPATIBLE = "openai_compatible"
RUNTIME_ANTHROPIC = "anthropic"

# --------------------------------------------------------------------------- #
# Capability "surface" vocabulary a runtime advertises
# --------------------------------------------------------------------------- #
#: Plain chat / text completion (OpenAI-compatible chat completions).
SURFACE_CHAT = "chat"
#: Image *understanding* (multimodal chat input).
SURFACE_VISION = "vision"
#: Text embeddings.
SURFACE_EMBEDDING = "embedding"
#: Image *generation*.
SURFACE_IMAGE_GENERATION = "image_generation"
#: Video generation (text-to-video).
SURFACE_VIDEO_GENERATION = "video_generation"
#: Image-to-video generation.
SURFACE_IMAGE_TO_VIDEO = "image_to_video"

ALL_SURFACES = (
    SURFACE_CHAT,
    SURFACE_VISION,
    SURFACE_EMBEDDING,
    SURFACE_IMAGE_GENERATION,
    SURFACE_VIDEO_GENERATION,
    SURFACE_IMAGE_TO_VIDEO,
)

#: Modalities a model *run by* the runtime can consume/produce. Kept aligned with
#: :data:`models.base.ALL_MODALITIES` so the two vocabularies never drift.
ALL_RUNTIME_MODALITIES = (
    MODALITY_TEXT,
    MODALITY_IMAGE,
    MODALITY_VIDEO,
    MODALITY_EMBEDDING,
)

#: Reason surfaced for a runtime that has no adapter wired in this build.
UNWIRED_GENERATION_REASON = (
    "Generation runtime adapter is not wired in this build: models that need it are "
    "declarative registrations only, nothing is downloaded and no fake adapter is used."
)

#: Reason surfaced for a generation runtime that *is* wired in this build but whose
#: weights are not present on this host. Distinct from :data:`UNWIRED_GENERATION_REASON`:
#: the adapter exists (lazy, probe-first), it simply has nothing local to load — and it
#: never downloads. Models served by such a runtime are reported ``NOT_CONFIGURED``
#: with a ``weights_missing`` reason until an operator provisions the checkpoint.
WEIGHTS_MISSING_REASON = (
    "Generation runtime is wired but its weights are not present on this host "
    "(NOT_CONFIGURED / WEIGHTS_MISSING): provision the checkpoint locally — nothing is "
    "downloaded automatically and no fake output is produced."
)


# --------------------------------------------------------------------------- #
# Descriptor
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RuntimeDescriptor:
    """A declarative description of one serving runtime (never a credential)."""

    id: str
    label: str
    #: True when the models it serves run locally (no external egress required).
    local: bool
    #: ``ModelAdapter`` subclass wired in this build, or ``""`` when none exists yet.
    adapter: str
    #: Whether this build can actually serve models through the runtime.
    supported: bool
    #: Capability surfaces the runtime can serve (see ``ALL_SURFACES``).
    surfaces: tuple[str, ...] = ()
    #: Modalities it can consume/produce (see ``ALL_RUNTIME_MODALITIES``).
    modalities: tuple[str, ...] = ()
    #: Human-readable reason explaining an unsupported runtime ("" when supported).
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "local": self.local,
            "adapter": self.adapter,
            "supported": self.supported,
            "surfaces": list(self.surfaces),
            "modalities": list(self.modalities),
            "reason": self.reason,
        }


# --------------------------------------------------------------------------- #
# The matrix
# --------------------------------------------------------------------------- #
_RUNTIMES: tuple[RuntimeDescriptor, ...] = (
    RuntimeDescriptor(
        id=RUNTIME_OLLAMA,
        label="Ollama (local)",
        local=True,
        adapter="OllamaAdapter",
        supported=True,
        surfaces=(SURFACE_CHAT, SURFACE_VISION, SURFACE_EMBEDDING),
        modalities=(MODALITY_TEXT, MODALITY_IMAGE, MODALITY_EMBEDDING),
    ),
    RuntimeDescriptor(
        id=RUNTIME_LOCALAI,
        label="LocalAI (local, OpenAI-compatible)",
        local=True,
        adapter="LocalAIAdapter",
        supported=True,
        surfaces=(SURFACE_CHAT, SURFACE_VISION, SURFACE_EMBEDDING, SURFACE_IMAGE_GENERATION),
        modalities=(MODALITY_TEXT, MODALITY_IMAGE, MODALITY_EMBEDDING),
    ),
    RuntimeDescriptor(
        id=RUNTIME_DIFFUSERS,
        label="Diffusers (local, open weights)",
        local=True,
        adapter="",
        supported=False,
        surfaces=(SURFACE_IMAGE_GENERATION, SURFACE_VIDEO_GENERATION, SURFACE_IMAGE_TO_VIDEO),
        modalities=(MODALITY_TEXT, MODALITY_IMAGE, MODALITY_VIDEO),
        reason=UNWIRED_GENERATION_REASON,
    ),
    RuntimeDescriptor(
        id=RUNTIME_WAN_I2V,
        label="Wan 2.2 I2V (local, open weights)",
        local=True,
        #: The adapter wired in this build (``models.generation_runtime.WanI2VAdapter``).
        #: It is lazy: importing/starting the app loads no weights; a real probe runs
        #: only when a generation is explicitly requested, and only from a *local*
        #: checkpoint (no download path exists).
        adapter="WanI2VAdapter",
        supported=True,
        surfaces=(SURFACE_IMAGE_TO_VIDEO,),
        modalities=(MODALITY_TEXT, MODALITY_IMAGE, MODALITY_VIDEO),
    ),
    RuntimeDescriptor(
        id=RUNTIME_OPENAI_COMPATIBLE,
        label="OpenAI-compatible HTTP API",
        local=False,
        adapter="OpenAICompatibleAdapter",
        supported=True,
        surfaces=(SURFACE_CHAT, SURFACE_VISION, SURFACE_EMBEDDING, SURFACE_IMAGE_GENERATION),
        modalities=(MODALITY_TEXT, MODALITY_IMAGE, MODALITY_EMBEDDING),
    ),
    RuntimeDescriptor(
        id=RUNTIME_ANTHROPIC,
        label="Anthropic Messages API",
        local=False,
        adapter="AnthropicAdapter",
        supported=True,
        surfaces=(SURFACE_CHAT, SURFACE_VISION),
        modalities=(MODALITY_TEXT, MODALITY_IMAGE),
    ),
)

RUNTIMES: tuple[RuntimeDescriptor, ...] = _RUNTIMES

_BY_ID: dict[str, RuntimeDescriptor] = {r.id: r for r in RUNTIMES}

#: Runtimes whose models run locally (no external egress required).
LOCAL_RUNTIMES: frozenset[str] = frozenset(r.id for r in RUNTIMES if r.local)

#: Runtime label → the surface constants it satisfies (derived helper).
_SURFACE_TO_CAPABILITY: dict[str, str] = {
    SURFACE_IMAGE_GENERATION: CAP_IMAGE_GENERATION,
    SURFACE_VIDEO_GENERATION: CAP_VIDEO_GENERATION,
    SURFACE_IMAGE_TO_VIDEO: CAP_VIDEO_GENERATION,
    SURFACE_EMBEDDING: CAP_EMBEDDINGS,
}


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def runtime_ids() -> list[str]:
    return [r.id for r in RUNTIMES]


def runtimes() -> tuple[RuntimeDescriptor, ...]:
    return RUNTIMES


def get_runtime(runtime_id: str) -> RuntimeDescriptor | None:
    """Return the descriptor for ``runtime_id`` (``None`` when unknown)."""
    return _BY_ID.get(runtime_id)


def is_local_runtime(runtime_id: str) -> bool:
    """True when models served by ``runtime_id`` run locally."""
    return (runtime_id or "").strip().lower() in LOCAL_RUNTIMES


def runtime_supported(runtime_id: str) -> bool:
    """Whether this build can serve models through ``runtime_id``.

    An *unknown* runtime is never supported — we do not invent adapters.
    """
    descriptor = get_runtime(runtime_id)
    return bool(descriptor and descriptor.supported)


def runtime_reason(runtime_id: str) -> str:
    """Clear reason a runtime is unsupported ("" when supported/known-good)."""
    descriptor = get_runtime(runtime_id)
    if descriptor is None:
        return f"Unknown runtime '{runtime_id}': no adapter is registered for it."
    return descriptor.reason


def runtime_status(runtime_id: str) -> tuple[bool, str]:
    """Convenience ``(supported, reason)`` pair for a runtime id."""
    return runtime_supported(runtime_id), runtime_reason(runtime_id)


def runtimes_for_surface(surface: str) -> list[RuntimeDescriptor]:
    """Runtimes that advertise ``surface`` (supported or not)."""
    return [r for r in RUNTIMES if surface in r.surfaces]


def supported_runtimes_for_surface(surface: str) -> list[RuntimeDescriptor]:
    return [r for r in runtimes_for_surface(surface) if r.supported]


def capability_for_surface(surface: str) -> str:
    """Map a runtime surface to its :mod:`models.base` capability ("" if none)."""
    return _SURFACE_TO_CAPABILITY.get(surface, "")


def runtime_view() -> dict[str, Any]:
    """JSON-safe description of the whole runtime matrix (never contains secrets)."""
    return {
        "runtimes": [r.to_dict() for r in RUNTIMES],
        "surfaces": list(ALL_SURFACES),
        "modalities": list(ALL_RUNTIME_MODALITIES),
        "local": sorted(LOCAL_RUNTIMES),
        "supported": sorted(r.id for r in RUNTIMES if r.supported),
        "unsupported": sorted(r.id for r in RUNTIMES if not r.supported),
        "config_source": "runtime-matrix",
        "secrets_exposed": False,
    }


__all__ = [
    "RUNTIME_OLLAMA",
    "RUNTIME_LOCALAI",
    "RUNTIME_DIFFUSERS",
    "RUNTIME_WAN_I2V",
    "RUNTIME_OPENAI_COMPATIBLE",
    "RUNTIME_ANTHROPIC",
    "SURFACE_CHAT",
    "SURFACE_VISION",
    "SURFACE_EMBEDDING",
    "SURFACE_IMAGE_GENERATION",
    "SURFACE_VIDEO_GENERATION",
    "SURFACE_IMAGE_TO_VIDEO",
    "ALL_SURFACES",
    "ALL_RUNTIME_MODALITIES",
    "UNWIRED_GENERATION_REASON",
    "WEIGHTS_MISSING_REASON",
    "RuntimeDescriptor",
    "RUNTIMES",
    "LOCAL_RUNTIMES",
    "runtime_ids",
    "runtimes",
    "get_runtime",
    "is_local_runtime",
    "runtime_supported",
    "runtime_reason",
    "runtime_status",
    "runtimes_for_surface",
    "supported_runtimes_for_surface",
    "capability_for_surface",
    "runtime_view",
]
