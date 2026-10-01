"""Generation registrations — image, video and image-to-video.

This module is the image/video counterpart of the chat activation layer
(:mod:`models.local`): it records **declarative registrations** for the open-weight
generation models the workspace wants to support, wired to a *runtime* from
:mod:`models.runtimes`, and reports an honest state for each.

Scope & honesty rules (identical spirit to the catalog / registry / activation):

* **Registrations, not adapters.** A registration declares *what a model is and how
  it would be served*; it never pretends to generate anything. When the runtime that
  would serve it is unsupported in this build, the model is reported
  ``NOT_CONFIGURED`` with a **clear reason** (``runtime_unsupported``) — there is no
  fake adapter and no invented output.
* **Nothing is downloaded.** There is no pull/download path anywhere; the official
  identifier is recorded purely as a *reference* (``official_ref``) for an operator
  who chooses to provision the weights themselves. ``AUTOMATIC_DOWNLOAD`` is
  ``False`` and enforced by tests.
* **A real sink is required.** A model is only ``AVAILABLE`` when its runtime is
  supported **and** a real generation sink exists: either the runtime reconciled a
  descriptor for it (``runtime`` sink) or an operator configured an HTTP endpoint
  (``endpoint`` sink). Otherwise it is ``INSTALLED`` (reachable, no confirmed sink)
  or ``NOT_INSTALLED``.
* **Image / video / i2v are distinct sinks.** An image registration can never
  satisfy a video task, and a text-to-video registration can never satisfy an
  image-to-video task: the surface is a hard property of the registration.
* No network I/O and no cloud API calls happen here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.app.core.observability import get_logger
from models.base import (
    CAP_IMAGE_GENERATION,
    CAP_VIDEO_GENERATION,
    KIND_IMAGE,
    KIND_VIDEO,
    MODALITY_IMAGE,
    MODALITY_TEXT,
    MODALITY_VIDEO,
)
from models.runtimes import (
    RUNTIME_DIFFUSERS,
    SURFACE_IMAGE_GENERATION,
    SURFACE_IMAGE_TO_VIDEO,
    SURFACE_VIDEO_GENERATION,
    runtime_status,
)

logger = get_logger("model_generation")

#: This layer never downloads weights — the constant is asserted by the test suite.
AUTOMATIC_DOWNLOAD = False

# --------------------------------------------------------------------------- #
# Sink vocabulary — how a generation model is (or would be) served
# --------------------------------------------------------------------------- #
#: Served by a local runtime that reconciled a descriptor (e.g. a served diffusers).
SINK_RUNTIME = "runtime"
#: Served by an operator-configured HTTP generation endpoint (never auto-created).
SINK_ENDPOINT = "endpoint"
#: Registered but not reachable on this host — nothing was (or will be) downloaded.
SINK_NONE = "none"

# --------------------------------------------------------------------------- #
# State vocabulary (regulation ✕ reality), mirroring local-model activation
# --------------------------------------------------------------------------- #
#: Reachable **and** a real sink confirmed it — the only state that is usable.
GEN_AVAILABLE = "AVAILABLE"
#: Reachable/discovered, but no generation sink was confirmed.
GEN_INSTALLED = "INSTALLED"
#: Registered but not present on this host; nothing was downloaded.
GEN_NOT_INSTALLED = "NOT_INSTALLED"
#: The runtime that would serve it is unsupported in this build (clear reason).
GEN_NOT_CONFIGURED = "NOT_CONFIGURED"

ALL_GEN_STATES = (GEN_AVAILABLE, GEN_INSTALLED, GEN_NOT_INSTALLED, GEN_NOT_CONFIGURED)

#: Reason codes explaining a non-available registration.
REASON_RUNTIME_UNSUPPORTED = "runtime_unsupported"
REASON_NO_SINK = "no_confirmed_sink"
REASON_NOT_PRESENT = "not_present_on_host"


@dataclass(frozen=True)
class GenerationRegistration:
    """Declarative registration for one image / video / i2v model.

    ``official_ref`` is a **documentation-only** pointer to the model's official
    identifier (a Hugging Face repo id). It is never fetched, resolved or
    downloaded by this module.
    """

    id: str
    family: str
    provider: str
    runtime: str
    kind: str
    surfaces: tuple[str, ...]
    official_ref: str = ""
    notes: str = ""

    @property
    def is_i2v(self) -> bool:
        return SURFACE_IMAGE_TO_VIDEO in self.surfaces

    @property
    def is_t2v(self) -> bool:
        return SURFACE_VIDEO_GENERATION in self.surfaces

    @property
    def modality(self) -> tuple[str, ...]:
        if self.kind == KIND_IMAGE:
            return (MODALITY_TEXT, MODALITY_IMAGE)
        if self.is_i2v:
            # Image-to-video consumes an image + prompt and produces video.
            return (MODALITY_TEXT, MODALITY_IMAGE, MODALITY_VIDEO)
        return (MODALITY_TEXT, MODALITY_VIDEO)

    @property
    def capability(self) -> str:
        return CAP_IMAGE_GENERATION if self.kind == KIND_IMAGE else CAP_VIDEO_GENERATION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["surfaces"] = list(self.surfaces)
        data["modality"] = list(self.modality)
        data["capability"] = self.capability
        data["is_i2v"] = self.is_i2v
        data["is_t2v"] = self.is_t2v
        return data


# --------------------------------------------------------------------------- #
# The registrations (official identifiers only — docs.claude.com official repos)
# --------------------------------------------------------------------------- #
_REGISTRATIONS: tuple[GenerationRegistration, ...] = (
    # ---------------------------------------------------------------- image
    GenerationRegistration(
        id="qwen-image",
        family="Qwen-Image",
        provider="qwen",
        runtime=RUNTIME_DIFFUSERS,
        kind=KIND_IMAGE,
        surfaces=(SURFACE_IMAGE_GENERATION,),
        official_ref="Qwen/Qwen-Image",
        notes="Open-weight text-to-image foundation model (complex text rendering).",
    ),
    GenerationRegistration(
        id="qwen-image-edit",
        family="Qwen-Image",
        provider="qwen",
        runtime=RUNTIME_DIFFUSERS,
        kind=KIND_IMAGE,
        surfaces=(SURFACE_IMAGE_GENERATION,),
        official_ref="Qwen/Qwen-Image-Edit",
        notes="Instruction-based image editing variant.",
    ),
    GenerationRegistration(
        id="flux.1-schnell",
        family="FLUX.1",
        provider="bfl",
        runtime=RUNTIME_DIFFUSERS,
        kind=KIND_IMAGE,
        surfaces=(SURFACE_IMAGE_GENERATION,),
        official_ref="black-forest-labs/FLUX.1-schnell",
        notes="Distilled, few-step open-weight image model.",
    ),
    # ---------------------------------------------------------------- video (t2v)
    GenerationRegistration(
        id="wan2.2-t2v",
        family="Wan",
        provider="alibaba",
        runtime=RUNTIME_DIFFUSERS,
        kind=KIND_VIDEO,
        surfaces=(SURFACE_VIDEO_GENERATION,),
        official_ref="Wan-AI/Wan2.2-T2V-A14B",
        notes="Text-to-video (MoE).",
    ),
    GenerationRegistration(
        id="hunyuanvideo",
        family="HunyuanVideo",
        provider="tencent",
        runtime=RUNTIME_DIFFUSERS,
        kind=KIND_VIDEO,
        surfaces=(SURFACE_VIDEO_GENERATION,),
        official_ref="tencent/HunyuanVideo",
        notes="Text-to-video (13B diffusion transformer).",
    ),
    GenerationRegistration(
        id="cogvideox-5b",
        family="CogVideoX",
        provider="zhipu",
        runtime=RUNTIME_DIFFUSERS,
        kind=KIND_VIDEO,
        surfaces=(SURFACE_VIDEO_GENERATION,),
        official_ref="zai-org/CogVideoX-5b",
        notes="Text-to-video (5B).",
    ),
    # ---------------------------------------------------------------- video (i2v)
    GenerationRegistration(
        id="wan2.2-i2v",
        family="Wan",
        provider="alibaba",
        runtime=RUNTIME_DIFFUSERS,
        kind=KIND_VIDEO,
        surfaces=(SURFACE_VIDEO_GENERATION, SURFACE_IMAGE_TO_VIDEO),
        official_ref="Wan-AI/Wan2.2-I2V-A14B",
        notes="Image-to-video (MoE); also supports text-to-video per the model card.",
    ),
    GenerationRegistration(
        id="hunyuanvideo-i2v",
        family="HunyuanVideo",
        provider="tencent",
        runtime=RUNTIME_DIFFUSERS,
        kind=KIND_VIDEO,
        surfaces=(SURFACE_IMAGE_TO_VIDEO,),
        official_ref="tencent/HunyuanVideo-I2V",
        notes="Image-to-video built on HunyuanVideo.",
    ),
)

GENERATION_REGISTRATIONS: tuple[GenerationRegistration, ...] = _REGISTRATIONS

_BY_ID: dict[str, GenerationRegistration] = {r.id: r for r in GENERATION_REGISTRATIONS}


# --------------------------------------------------------------------------- #
# Outcome
# --------------------------------------------------------------------------- #
@dataclass
class GenerationOutcome:
    """The honest state of one generation registration."""

    id: str
    family: str
    provider: str
    runtime: str
    kind: str
    surfaces: list[str]
    state: str = GEN_NOT_CONFIGURED
    reason: str = REASON_RUNTIME_UNSUPPORTED
    runtime_supported: bool = False
    sink: str = SINK_NONE
    installed: bool = False
    available: bool = False
    capability: str = ""
    modality: list[str] = field(default_factory=list)
    official_ref: str = ""
    endpoints: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Lookups / helpers
# --------------------------------------------------------------------------- #
def generation_registrations() -> tuple[GenerationRegistration, ...]:
    return GENERATION_REGISTRATIONS


def generation_ids() -> list[str]:
    return [r.id for r in GENERATION_REGISTRATIONS]


def get_generation_registration(model_id: str) -> GenerationRegistration | None:
    return _BY_ID.get(model_id)


def is_generation_model(model_id: str) -> bool:
    """True when ``model_id`` is a registered generation (image/video) model."""
    return model_id in _BY_ID


def registrations_for_surface(surface: str) -> list[GenerationRegistration]:
    """Registrations that expose ``surface`` (e.g. an i2v surface)."""
    return [r for r in GENERATION_REGISTRATIONS if surface in r.surfaces]


# --------------------------------------------------------------------------- #
# Pure classification (no I/O — the testable core)
# --------------------------------------------------------------------------- #
def _confirmed_sink(
    reg: GenerationRegistration,
    descriptor: Any,
) -> tuple[str, list[str]]:
    """Determine the *confirmed* sink for ``reg`` from its runtime view.

    A ``runtime`` sink requires the runtime to have reconciled a descriptor. The
    ``endpoint`` sink is only ever accepted when the descriptor explicitly carries a
    non-empty, declared endpoint (an operator configuration) — never inferred from a
    model merely appearing in a list.
    """
    if descriptor is None:
        return SINK_NONE, []
    endpoints = [str(e) for e in (getattr(descriptor, "endpoints", None) or []) if e]
    endpoint = str(getattr(descriptor, "endpoint", "") or "")
    if endpoint and endpoint not in endpoints:
        endpoints.append(endpoint)
    if endpoints:
        return SINK_ENDPOINT, endpoints
    # A descriptor reconciled by a *supported* local runtime is itself a real sink.
    return SINK_RUNTIME, []


def classify_generation(
    *,
    runtime_models: dict[str, Any] | None = None,
    endpoint_models: dict[str, tuple[str, ...]] | None = None,
    scope_ids: set[str] | None = None,
) -> dict[str, GenerationOutcome]:
    """Pure classification of every generation registration (no network, no download).

    Parameters
    ----------
    runtime_models:
        ``{model_id: descriptor}`` for generation models a supported runtime
        actually reconciled (e.g. a served diffusers runtime). Descriptors may carry
        ``endpoint`` / ``endpoints`` for an operator-configured sink.
    endpoint_models:
        ``{model_id: (endpoint, ...)}`` for models an operator wired to a real HTTP
        generation endpoint. Never created implicitly.
    scope_ids:
        Restrict the report to these ids.
    """
    runtime_models = runtime_models or {}
    endpoint_models = endpoint_models or {}
    outcomes: dict[str, GenerationOutcome] = {}

    for reg in GENERATION_REGISTRATIONS:
        if scope_ids is not None and reg.id not in scope_ids:
            continue

        supported, reason = runtime_status(reg.runtime)
        descriptor = runtime_models.get(reg.id)
        explicit_endpoints = tuple(endpoint_models.get(reg.id, ()))
        if descriptor is not None and explicit_endpoints:
            # An explicit operator endpoint takes precedence on the descriptor.
            try:
                descriptor.endpoints = list(explicit_endpoints)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - descriptor may be frozen
                descriptor = _EndpointDescriptor(reg.id, explicit_endpoints, getattr(descriptor, "endpoint", ""))
        elif descriptor is None and explicit_endpoints:
            descriptor = _EndpointDescriptor(reg.id, explicit_endpoints, "")

        sink, endpoints = _confirmed_sink(reg, descriptor)
        installed = descriptor is not None

        if not supported:
            # A runtime with no adapter in this build → NOT_CONFIGURED + a clear reason.
            state, final_reason = GEN_NOT_CONFIGURED, reason
        elif sink in (SINK_RUNTIME, SINK_ENDPOINT):
            state, final_reason = GEN_AVAILABLE, ""
        elif installed:
            state, final_reason = GEN_INSTALLED, REASON_NO_SINK
        else:
            state, final_reason = GEN_NOT_INSTALLED, REASON_NOT_PRESENT

        outcomes[reg.id] = GenerationOutcome(
            id=reg.id,
            family=reg.family,
            provider=reg.provider,
            runtime=reg.runtime,
            kind=reg.kind,
            surfaces=list(reg.surfaces),
            state=state,
            reason=final_reason,
            runtime_supported=supported,
            sink=sink,
            installed=installed,
            available=state == GEN_AVAILABLE,
            capability=reg.capability,
            modality=list(reg.modality),
            official_ref=reg.official_ref,
            endpoints=list(endpoints),
            notes=reg.notes,
        )
    return outcomes


@dataclass
class _EndpointDescriptor:
    """Minimal descriptor for an operator-configured generation endpoint."""

    id: str
    endpoints: list[str]
    endpoint: str = ""


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def generation_summary(
    *,
    runtime_models: dict[str, Any] | None = None,
    endpoint_models: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """Compact, JSON-safe generation report (never contains secrets)."""
    outcomes = classify_generation(runtime_models=runtime_models, endpoint_models=endpoint_models)
    models = [o.to_dict() for o in sorted(outcomes.values(), key=lambda o: o.id)]

    def ids(state: str) -> list[str]:
        return sorted(m["id"] for m in models if m["state"] == state)

    return {
        "scope": "generation",
        "kinds": [KIND_IMAGE, KIND_VIDEO],
        "automatic_download": AUTOMATIC_DOWNLOAD,
        "image": sorted(m["id"] for m in models if m["kind"] == KIND_IMAGE),
        "video": sorted(m["id"] for m in models if m["kind"] == KIND_VIDEO),
        "i2v": sorted(m["id"] for m in models if m["capability"] == CAP_VIDEO_GENERATION and m["state"] and "image_to_video" in m["surfaces"]),
        "available": ids(GEN_AVAILABLE),
        "installed": [m["id"] for m in models if m["installed"]],
        "not_installed": ids(GEN_NOT_INSTALLED),
        "not_configured": ids(GEN_NOT_CONFIGURED),
        "total": len(models),
        "models": models,
        "secrets_exposed": False,
    }


def available_generation_models(
    *,
    runtime_models: dict[str, Any] | None = None,
    endpoint_models: dict[str, tuple[str, ...]] | None = None,
) -> list[str]:
    """Ids of generation models that are genuinely available (real sink, supported runtime)."""
    outcomes = classify_generation(runtime_models=runtime_models, endpoint_models=endpoint_models)
    return sorted(o.id for o in outcomes.values() if o.available)


__all__ = [
    "AUTOMATIC_DOWNLOAD",
    "SINK_RUNTIME",
    "SINK_ENDPOINT",
    "SINK_NONE",
    "GEN_AVAILABLE",
    "GEN_INSTALLED",
    "GEN_NOT_INSTALLED",
    "GEN_NOT_CONFIGURED",
    "ALL_GEN_STATES",
    "REASON_RUNTIME_UNSUPPORTED",
    "REASON_NO_SINK",
    "REASON_NOT_PRESENT",
    "GenerationRegistration",
    "GENERATION_REGISTRATIONS",
    "GenerationOutcome",
    "generation_registrations",
    "generation_ids",
    "get_generation_registration",
    "is_generation_model",
    "registrations_for_surface",
    "classify_generation",
    "generation_summary",
    "available_generation_models",
]
