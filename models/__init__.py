"""Model layer: unified provider contract, adapters, registry and router.

Public surface:

* :class:`models.base.ModelAdapter` — the unified provider interface.
* :mod:`models.adapters` — OpenAI-compatible / Anthropic / Ollama / echo adapters.
* :class:`models.registry.ModelRegistry` — discovery + honest probing + caching.
* :class:`models.router.ModelRouter` — task-based model selection.
"""

from models.base import (  # noqa: F401
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
    COST_TIER_UNKNOWN,
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_IMAGE,
    KIND_SEARCH,
    KIND_VIDEO,
    STATUS_AVAILABLE,
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_LOADING,
    STATUS_MISCONFIGURED,
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
    ChatMessage,
    Completion,
    EmbeddingResult,
    HealthReport,
    ImageResult,
    ModelAdapter,
    ModelCapabilities,
    ModelDescriptor,
    ToolCall,
    VideoResult,
)
from models.catalog import ModelCatalogEntry, catalog_entries, get_catalog_entry  # noqa: F401
from models.registry import ModelInfo, ModelRegistry, registry  # noqa: F401
from models.router import ModelRouter, RoutingDecision  # noqa: F401

__all__ = [
    "ModelAdapter",
    "ModelCapabilities",
    "ModelDescriptor",
    "ModelInfo",
    "ModelCatalogEntry",
    "ModelRegistry",
    "ModelRouter",
    "RoutingDecision",
    "ChatMessage",
    "Completion",
    "EmbeddingResult",
    "ImageResult",
    "VideoResult",
    "ToolCall",
    "HealthReport",
    "registry",
    "catalog_entries",
    "get_catalog_entry",
    "STATUS_AVAILABLE",
    "STATUS_UNAVAILABLE",
    "STATUS_MISCONFIGURED",
    "STATUS_DISABLED",
    "STATUS_LOADING",
    "STATUS_ERROR",
    "STATUS_NOT_CONFIGURED",
    "COST_TIER_UNKNOWN",
]
