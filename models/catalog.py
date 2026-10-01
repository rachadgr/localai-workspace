"""Static **Model Catalog** — declarative metadata for a modern, multi-modal set.

Why a separate catalog?
-----------------------
Runtime *discovery* (``models/adapters.py`` + ``models/registry.py``) only knows
what a provider actually exposes right now. The catalog adds the *declared*
metadata we want to reason about — ``id, name, family, provider, modality,
capabilities, context_window, reasoning, vision, tools, streaming, local,
cost_tier, status`` — **without ever claiming a model is usable**.

Honesty rules (identical spirit to ``models/base.py``):

* Every entry defaults to ``status = NOT_CONFIGURED``. A catalog entry is a
  *description*, never a proof of availability.
* ``AVAILABLE`` is only ever produced by the registry after a **real** minimal
  request succeeds; the catalog never sets it.
* The catalog holds **no credentials** and performs **no network I/O**. It never
  downloads weights and never calls a cloud API.
* ``provider`` is a *label* (``ollama`` for locally-served models, the vendor
  name for cloud models). It is **not** a credential and never implies access.

The registry merges this metadata with the real runtime state, keyed by
``(provider, id)`` — the catalog can enrich a discovered model (family,
reasoning, cost tier…) but can never override its probed ``status``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from models.base import (
    CAP_CHAT,
    CAP_CODE,
    CAP_EMBEDDINGS,
    CAP_IMAGE_GENERATION,
    CAP_JSON_MODE,
    CAP_LONG_CONTEXT,
    CAP_REASONING,
    CAP_STREAMING,
    CAP_TOOLS,
    CAP_VIDEO_GENERATION,
    CAP_VISION,
    COST_TIER_UNKNOWN,
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_IMAGE,
    KIND_VIDEO,
    STATUS_NOT_CONFIGURED,
    infer_modality,
)

# --------------------------------------------------------------------------- #
# Provider classification (labels only — never credentials)
# --------------------------------------------------------------------------- #
#: Providers whose models run locally (no external egress required).
LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama"})


def is_local_provider(provider: str) -> bool:
    """True when ``provider`` is a known local runtime label."""
    return (provider or "").strip().lower() in LOCAL_PROVIDERS


# --------------------------------------------------------------------------- #
# Catalog entry
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModelCatalogEntry:
    """Declarative metadata for one model (no runtime claims)."""

    id: str
    name: str
    family: str
    provider: str
    kind: str = KIND_CHAT
    modality: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    context_window: int = 0
    reasoning: bool = False
    vision: bool = False
    tools: bool = False
    streaming: bool = False
    local: bool = False
    cost_tier: str = COST_TIER_UNKNOWN
    status: str = STATUS_NOT_CONFIGURED
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["modality"] = list(self.modality)
        data["capabilities"] = list(self.capabilities)
        return data


# --------------------------------------------------------------------------- #
# Construction helpers (keep entries compact + internally consistent)
# --------------------------------------------------------------------------- #
def _compose_capabilities(
    kind: str,
    *,
    tools: bool = False,
    vision: bool = False,
    reasoning: bool = False,
    code: bool = False,
    json_mode: bool = True,
    long_context: bool = False,
) -> tuple[str, ...]:
    """Derive the capability list from a model kind + boolean flags.

    Keeps ``capabilities`` and the boolean fields (``reasoning``/``vision``/
    ``tools``/``streaming``) automatically consistent.
    """
    if kind == KIND_IMAGE:
        return (CAP_IMAGE_GENERATION,)
    if kind == KIND_VIDEO:
        return (CAP_VIDEO_GENERATION,)
    if kind == KIND_EMBEDDING:
        return (CAP_EMBEDDINGS,)
    caps: list[str] = [CAP_CHAT, CAP_STREAMING]
    if tools:
        caps.append(CAP_TOOLS)
    if vision:
        caps.append(CAP_VISION)
    if reasoning:
        caps.append(CAP_REASONING)
    if code:
        caps.append(CAP_CODE)
    if json_mode:
        caps.append(CAP_JSON_MODE)
    if long_context:
        caps.append(CAP_LONG_CONTEXT)
    return tuple(caps)


def _entry(
    id: str,
    name: str,
    family: str,
    provider: str,
    *,
    kind: str = KIND_CHAT,
    context_window: int = 0,
    reasoning: bool = False,
    vision: bool = False,
    tools: bool = False,
    code: bool = False,
    json_mode: bool = True,
    long_context: bool = False,
    cost_tier: str = COST_TIER_UNKNOWN,
    status: str = STATUS_NOT_CONFIGURED,
    local: bool | None = None,
    notes: str = "",
) -> ModelCatalogEntry:
    """Build a consistent :class:`ModelCatalogEntry`.

    ``local`` and ``streaming`` are derived from ``provider``/``kind`` unless
    explicitly overridden. ``status`` defaults to ``NOT_CONFIGURED`` — never
    ``AVAILABLE``.
    """
    resolved_local = is_local_provider(provider) if local is None else local
    streaming = kind == KIND_CHAT
    return ModelCatalogEntry(
        id=id,
        name=name,
        family=family,
        provider=provider,
        kind=kind,
        modality=tuple(infer_modality(kind, vision=vision)),
        capabilities=_compose_capabilities(
            kind,
            tools=tools,
            vision=vision,
            reasoning=reasoning,
            code=code,
            json_mode=json_mode,
            long_context=long_context,
        ),
        context_window=context_window,
        reasoning=reasoning,
        vision=vision,
        tools=tools,
        streaming=streaming,
        local=resolved_local,
        cost_tier=cost_tier,
        status=status,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# The catalog (grouped by family for readability)
# --------------------------------------------------------------------------- #
_ENTRIES: list[ModelCatalogEntry] = [
    # ------------------------------------------------------------- Qwen3 (local)
    _entry(
        "qwen3:4b",
        "Qwen3 4B",
        "Qwen3",
        "ollama",
        context_window=131072,
        reasoning=True,
        tools=True,
        cost_tier="free",
        notes="Dense Qwen3 with a switchable thinking mode; the workspace's current default chat model.",
    ),
    _entry(
        "qwen3:8b",
        "Qwen3 8B",
        "Qwen3",
        "ollama",
        context_window=131072,
        reasoning=True,
        tools=True,
        cost_tier="free",
    ),
    _entry(
        "qwen3:14b",
        "Qwen3 14B",
        "Qwen3",
        "ollama",
        context_window=131072,
        reasoning=True,
        tools=True,
        cost_tier="free",
    ),
    _entry(
        "qwen3:30b-a3b",
        "Qwen3 30B-A3B",
        "Qwen3",
        "ollama",
        context_window=131072,
        reasoning=True,
        tools=True,
        cost_tier="free",
        notes="Mixture-of-Experts (30B total / 3B active).",
    ),
    # --------------------------------------------------------- Qwen3-Coder (local)
    _entry(
        "qwen3-coder:30b",
        "Qwen3 Coder 30B",
        "Qwen3-Coder",
        "ollama",
        context_window=262144,
        tools=True,
        code=True,
        cost_tier="free",
    ),
    _entry(
        "qwen3-coder:480b",
        "Qwen3 Coder 480B",
        "Qwen3-Coder",
        "ollama",
        context_window=262144,
        tools=True,
        code=True,
        cost_tier="free",
        notes="Flagship MoE coder; large host required.",
    ),
    # ------------------------------------------------------------ Qwen3-VL (local)
    _entry(
        "qwen3-vl:8b",
        "Qwen3-VL 8B",
        "Qwen3-VL",
        "ollama",
        context_window=262144,
        reasoning=True,
        vision=True,
        tools=True,
        cost_tier="free",
    ),
    _entry(
        "qwen3-vl:32b",
        "Qwen3-VL 32B",
        "Qwen3-VL",
        "ollama",
        context_window=262144,
        reasoning=True,
        vision=True,
        tools=True,
        cost_tier="free",
    ),
    # ------------------------------------------------------------- Qwen2.5 (local)
    _entry(
        "qwen2.5:7b",
        "Qwen2.5 7B",
        "Qwen2.5",
        "ollama",
        context_window=32768,
        tools=True,
        cost_tier="free",
    ),
    _entry(
        "qwen2.5-coder:7b",
        "Qwen2.5 Coder 7B",
        "Qwen2.5-Coder",
        "ollama",
        context_window=32768,
        tools=True,
        code=True,
        cost_tier="free",
    ),
    # ------------------------------------------------------------- DeepSeek (local)
    _entry(
        "deepseek-r1:8b",
        "DeepSeek-R1 8B",
        "DeepSeek-R1",
        "ollama",
        context_window=131072,
        reasoning=True,
        cost_tier="free",
    ),
    _entry(
        "deepseek-r1:14b",
        "DeepSeek-R1 14B",
        "DeepSeek-R1",
        "ollama",
        context_window=131072,
        reasoning=True,
        cost_tier="free",
    ),
    _entry(
        "deepseek-r1:32b",
        "DeepSeek-R1 32B",
        "DeepSeek-R1",
        "ollama",
        context_window=131072,
        reasoning=True,
        cost_tier="free",
    ),
    _entry(
        "deepseek-v3:671b",
        "DeepSeek-V3 671B",
        "DeepSeek-V3",
        "ollama",
        context_window=131072,
        tools=True,
        cost_tier="free",
        notes="MoE (671B total / 37B active); large host required.",
    ),
    _entry(
        "deepseek-coder-v2:16b",
        "DeepSeek-Coder-V2 16B",
        "DeepSeek-Coder-V2",
        "ollama",
        context_window=163840,
        code=True,
        cost_tier="free",
    ),
    # ------------------------------------------------------------- GPT-OSS (local)
    _entry(
        "gpt-oss:20b",
        "GPT-OSS 20B",
        "GPT-OSS",
        "ollama",
        context_window=131072,
        reasoning=True,
        tools=True,
        cost_tier="free",
        notes="OpenAI open-weight release (Apache-2.0); configurable reasoning effort.",
    ),
    _entry(
        "gpt-oss:120b",
        "GPT-OSS 120B",
        "GPT-OSS",
        "ollama",
        context_window=131072,
        reasoning=True,
        tools=True,
        cost_tier="free",
    ),
    # ---------------------------------------------------------------- GLM (local)
    _entry(
        "glm-4.5-air",
        "GLM-4.5 Air",
        "GLM-4.5",
        "ollama",
        context_window=131072,
        reasoning=True,
        tools=True,
        cost_tier="free",
    ),
    _entry(
        "glm-4.5v",
        "GLM-4.5V",
        "GLM-4.5V",
        "ollama",
        context_window=131072,
        reasoning=True,
        vision=True,
        tools=True,
        cost_tier="free",
    ),
    # ----------------------------------------------------------- Devstral (local)
    _entry(
        "devstral-small:24b",
        "Devstral Small 24B",
        "Devstral",
        "ollama",
        context_window=131072,
        tools=True,
        code=True,
        cost_tier="free",
        notes="Mistral agentic coding model for tool use.",
    ),
    # ------------------------------------------------------------ Mistral (local)
    _entry(
        "mistral-small3.2:24b",
        "Mistral Small 3.2 24B",
        "Mistral-Small",
        "ollama",
        context_window=131072,
        vision=True,
        tools=True,
        cost_tier="free",
    ),
    _entry(
        "magistral:24b",
        "Magistral Small 24B",
        "Magistral",
        "ollama",
        context_window=40960,
        reasoning=True,
        cost_tier="free",
        notes="Mistral reasoning model (traceable chain-of-thought).",
    ),
    _entry(
        "codestral:22b",
        "Codestral 22B",
        "Codestral",
        "ollama",
        context_window=262144,
        code=True,
        cost_tier="free",
    ),
    # -------------------------------------------------------------- Gemma (local)
    _entry(
        "gemma3:4b",
        "Gemma 3 4B",
        "Gemma-3",
        "ollama",
        context_window=131072,
        vision=True,
        cost_tier="free",
    ),
    _entry(
        "gemma3:12b",
        "Gemma 3 12B",
        "Gemma-3",
        "ollama",
        context_window=131072,
        vision=True,
        cost_tier="free",
    ),
    _entry(
        "gemma3:27b",
        "Gemma 3 27B",
        "Gemma-3",
        "ollama",
        context_window=131072,
        vision=True,
        cost_tier="free",
    ),
    _entry(
        "codegemma:7b",
        "CodeGemma 7B",
        "CodeGemma",
        "ollama",
        context_window=8192,
        code=True,
        cost_tier="free",
    ),
    _entry(
        "embeddinggemma:300m",
        "EmbeddingGemma 300M",
        "EmbeddingGemma",
        "ollama",
        kind=KIND_EMBEDDING,
        context_window=2048,
        cost_tier="free",
    ),
    # -------------------------------------------------------------- Llama (local)
    _entry(
        "llama3.2-vision:11b",
        "Llama 3.2 Vision 11B",
        "Llama-3.2-Vision",
        "ollama",
        context_window=131072,
        vision=True,
        cost_tier="free",
    ),
    _entry(
        "llama3.3:70b",
        "Llama 3.3 70B",
        "Llama-3.3",
        "ollama",
        context_window=131072,
        tools=True,
        cost_tier="free",
    ),
    # ---------------------------------------------------------------- Phi (local)
    _entry(
        "phi4:14b",
        "Phi-4 14B",
        "Phi-4",
        "ollama",
        context_window=16384,
        reasoning=True,
        cost_tier="free",
    ),
    _entry(
        "phi4-mini:3.8b",
        "Phi-4 Mini 3.8B",
        "Phi-4",
        "ollama",
        context_window=131072,
        reasoning=True,
        tools=True,
        cost_tier="free",
    ),
    # ---------------------------------------------------- local embedders (Ollama)
    _entry(
        "nomic-embed-text",
        "Nomic Embed Text",
        "Nomic-Embed",
        "ollama",
        kind=KIND_EMBEDDING,
        context_window=8192,
        cost_tier="free",
    ),
    _entry(
        "mxbai-embed-large",
        "MixedBread Embed Large",
        "MXBAI-Embed",
        "ollama",
        kind=KIND_EMBEDDING,
        context_window=512,
        cost_tier="free",
    ),
    _entry(
        "bge-m3",
        "BGE-M3",
        "BGE",
        "ollama",
        kind=KIND_EMBEDDING,
        context_window=8192,
        cost_tier="free",
    ),
    # ------------------------------------------------------------------ OpenAI (cloud)
    _entry(
        "gpt-5",
        "GPT-5",
        "GPT-5",
        "openai",
        context_window=400000,
        reasoning=True,
        vision=True,
        tools=True,
        code=True,
        long_context=True,
        cost_tier="high",
    ),
    _entry(
        "gpt-5-mini",
        "GPT-5 Mini",
        "GPT-5",
        "openai",
        context_window=400000,
        reasoning=True,
        vision=True,
        tools=True,
        long_context=True,
        cost_tier="medium",
    ),
    _entry(
        "gpt-5.4-mini",
        "GPT-5.4 Mini",
        "GPT-5",
        "openai",
        context_window=400000,
        reasoning=True,
        vision=True,
        tools=True,
        long_context=True,
        cost_tier="medium",
        notes="Referenced as the workspace's configured default chat model.",
    ),
    _entry(
        "gpt-4o",
        "GPT-4o",
        "GPT-4o",
        "openai",
        context_window=128000,
        vision=True,
        tools=True,
        code=True,
        cost_tier="high",
    ),
    _entry(
        "gpt-4o-mini",
        "GPT-4o Mini",
        "GPT-4o",
        "openai",
        context_window=128000,
        vision=True,
        tools=True,
        cost_tier="low",
    ),
    _entry(
        "o3",
        "o3",
        "o-series",
        "openai",
        context_window=200000,
        reasoning=True,
        vision=True,
        tools=True,
        long_context=True,
        cost_tier="high",
    ),
    _entry(
        "o4-mini",
        "o4-mini",
        "o-series",
        "openai",
        context_window=200000,
        reasoning=True,
        vision=True,
        tools=True,
        cost_tier="medium",
    ),
    _entry(
        "text-embedding-3-large",
        "Text Embedding 3 Large",
        "text-embedding-3",
        "openai",
        kind=KIND_EMBEDDING,
        context_window=8191,
        cost_tier="low",
    ),
    _entry(
        "text-embedding-3-small",
        "Text Embedding 3 Small",
        "text-embedding-3",
        "openai",
        kind=KIND_EMBEDDING,
        context_window=8191,
        cost_tier="low",
    ),
    _entry(
        "dall-e-3",
        "DALL·E 3",
        "DALL·E",
        "openai",
        kind=KIND_IMAGE,
        cost_tier="high",
    ),
    _entry(
        "gpt-image-1",
        "GPT Image 1",
        "GPT-Image",
        "openai",
        kind=KIND_IMAGE,
        cost_tier="high",
    ),
    # --------------------------------------------------------------- Anthropic (cloud)
    _entry(
        "claude-sonnet-4-5",
        "Claude Sonnet 4.5",
        "Claude-4",
        "anthropic",
        context_window=200000,
        reasoning=True,
        vision=True,
        tools=True,
        code=True,
        long_context=True,
        cost_tier="high",
    ),
    _entry(
        "claude-opus-4-1",
        "Claude Opus 4.1",
        "Claude-4",
        "anthropic",
        context_window=200000,
        reasoning=True,
        vision=True,
        tools=True,
        code=True,
        long_context=True,
        cost_tier="high",
    ),
    _entry(
        "claude-3-5-haiku-latest",
        "Claude 3.5 Haiku",
        "Claude-3.5",
        "anthropic",
        context_window=200000,
        vision=True,
        tools=True,
        cost_tier="low",
    ),
    # ------------------------------------------------------------------ Google (cloud)
    _entry(
        "gemini-2.5-pro",
        "Gemini 2.5 Pro",
        "Gemini-2.5",
        "google",
        context_window=1048576,
        reasoning=True,
        vision=True,
        tools=True,
        code=True,
        long_context=True,
        cost_tier="high",
    ),
    _entry(
        "gemini-2.5-flash",
        "Gemini 2.5 Flash",
        "Gemini-2.5",
        "google",
        context_window=1048576,
        reasoning=True,
        vision=True,
        tools=True,
        long_context=True,
        cost_tier="medium",
    ),
    _entry(
        "gemini-2.0-flash",
        "Gemini 2.0 Flash",
        "Gemini-2.0",
        "google",
        context_window=1048576,
        vision=True,
        tools=True,
        long_context=True,
        cost_tier="low",
    ),
    # -------------------------------------------------------------------- Z.ai (cloud)
    _entry(
        "glm-4.6",
        "GLM-4.6",
        "GLM-4.6",
        "zai",
        context_window=200000,
        reasoning=True,
        tools=True,
        code=True,
        long_context=True,
        cost_tier="medium",
    ),
    _entry(
        "glm-4.5",
        "GLM-4.5",
        "GLM-4.5",
        "zai",
        context_window=131072,
        reasoning=True,
        tools=True,
        code=True,
        cost_tier="medium",
    ),
    # ------------------------------------------------------------------ Mistral (cloud)
    _entry(
        "mistral-large-2411",
        "Mistral Large 24.11",
        "Mistral-Large",
        "mistral",
        context_window=131072,
        tools=True,
        code=True,
        cost_tier="medium",
    ),
    _entry(
        "pixtral-large-2411",
        "Pixtral Large 24.11",
        "Pixtral",
        "mistral",
        context_window=131072,
        vision=True,
        tools=True,
        cost_tier="medium",
    ),
    _entry(
        "devstral-medium",
        "Devstral Medium",
        "Devstral",
        "mistral",
        context_window=131072,
        tools=True,
        code=True,
        cost_tier="medium",
    ),
    # --------------------------------------------------------------------- xAI (cloud)
    _entry(
        "grok-4",
        "Grok 4",
        "Grok-4",
        "xai",
        context_window=256000,
        reasoning=True,
        vision=True,
        tools=True,
        long_context=True,
        cost_tier="high",
    ),
    _entry(
        "grok-3",
        "Grok 3",
        "Grok-3",
        "xai",
        context_window=131072,
        vision=True,
        tools=True,
        cost_tier="high",
    ),
    # ------------------------------------------------------------------ DeepSeek (cloud)
    _entry(
        "deepseek-chat",
        "DeepSeek Chat",
        "DeepSeek-V3",
        "deepseek",
        context_window=131072,
        tools=True,
        code=True,
        long_context=True,
        cost_tier="low",
    ),
    _entry(
        "deepseek-reasoner",
        "DeepSeek Reasoner",
        "DeepSeek-R1",
        "deepseek",
        context_window=131072,
        reasoning=True,
        long_context=True,
        cost_tier="low",
    ),
    # ------------------------------------------------------- image generation (cloud)
    _entry(
        "flux.1-dev",
        "FLUX.1 Dev",
        "FLUX.1",
        "bfl",
        kind=KIND_IMAGE,
        cost_tier="medium",
    ),
    _entry(
        "flux.1-schnell",
        "FLUX.1 Schnell",
        "FLUX.1",
        "bfl",
        kind=KIND_IMAGE,
        cost_tier="low",
        notes="Distilled, few-step variant.",
    ),
    _entry(
        "flux.1-pro",
        "FLUX.1 Pro",
        "FLUX.1",
        "bfl",
        kind=KIND_IMAGE,
        cost_tier="high",
    ),
    _entry(
        "qwen-image",
        "Qwen-Image",
        "Qwen-Image",
        "qwen",
        kind=KIND_IMAGE,
        cost_tier="medium",
    ),
    _entry(
        "qwen-image-edit",
        "Qwen-Image-Edit",
        "Qwen-Image",
        "qwen",
        kind=KIND_IMAGE,
        cost_tier="medium",
        notes="Instruction-based image editing.",
    ),
    _entry(
        "stable-diffusion-3.5-large",
        "Stable Diffusion 3.5 Large",
        "Stable-Diffusion-3.5",
        "stability",
        kind=KIND_IMAGE,
        cost_tier="medium",
    ),
    # ------------------------------------------------------- video generation (cloud)
    _entry(
        "wan2.2-t2v",
        "Wan 2.2 T2V",
        "Wan",
        "alibaba",
        kind=KIND_VIDEO,
        cost_tier="medium",
        notes="Text-to-video.",
    ),
    _entry(
        "wan2.2-i2v",
        "Wan 2.2 I2V",
        "Wan",
        "alibaba",
        kind=KIND_VIDEO,
        cost_tier="medium",
        notes="Image-to-video.",
    ),
    _entry(
        "hunyuanvideo",
        "HunyuanVideo",
        "HunyuanVideo",
        "tencent",
        kind=KIND_VIDEO,
        cost_tier="medium",
        notes="Text-to-video.",
    ),
    _entry(
        "hunyuanvideo-i2v",
        "HunyuanVideo I2V",
        "HunyuanVideo",
        "tencent",
        kind=KIND_VIDEO,
        cost_tier="medium",
        notes="Image-to-video.",
    ),
    _entry(
        "cogvideox-5b",
        "CogVideoX 5B",
        "CogVideoX",
        "zhipu",
        kind=KIND_VIDEO,
        cost_tier="low",
    ),
]

#: Ordered tuple of every catalog entry (declaration order is stable).
CATALOG: tuple[ModelCatalogEntry, ...] = tuple(_ENTRIES)

#: Index by model id (ids are unique across the catalog).
_BY_ID: dict[str, ModelCatalogEntry] = {entry.id: entry for entry in CATALOG}


def catalog_entries() -> tuple[ModelCatalogEntry, ...]:
    """Return every catalog entry (immutable tuple)."""
    return CATALOG


def catalog_ids() -> list[str]:
    """Return all catalog model ids (declaration order)."""
    return [entry.id for entry in CATALOG]


def get_catalog_entry(model_id: str) -> ModelCatalogEntry | None:
    """Look up a catalog entry by exact model id."""
    return _BY_ID.get(model_id)


def catalog_providers() -> list[str]:
    """Return the distinct provider labels referenced by the catalog."""
    seen: list[str] = []
    for entry in CATALOG:
        if entry.provider not in seen:
            seen.append(entry.provider)
    return seen


def catalog_by_kind(kind: str) -> list[ModelCatalogEntry]:
    """Return catalog entries of a given kind (chat/embedding/image/video)."""
    return [entry for entry in CATALOG if entry.kind == kind]


__all__ = [
    "ModelCatalogEntry",
    "CATALOG",
    "LOCAL_PROVIDERS",
    "is_local_provider",
    "catalog_entries",
    "catalog_ids",
    "get_catalog_entry",
    "catalog_providers",
    "catalog_by_kind",
]
