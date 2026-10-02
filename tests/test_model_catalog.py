"""Model Catalog tests.

Covers the *declarative* catalog layer and its integration with runtime discovery:

* catalog metadata completeness and unified vocabulary
  (``id, name, family, provider, modality, capabilities, context_window,
  reasoning, vision, tools, streaming, local, cost_tier, status``);
* status semantics — catalog entries are ``NOT_CONFIGURED`` by default and are
  **never** ``AVAILABLE`` (no false availability);
* registry merge — catalog metadata enriches a discovered model but can never
  override its probed status;
* capability filtering — the router must never send an image/video/vision task to
  a chat-only model;
* no-hardcoding — the catalog carries no credentials, tokens or endpoint URLs.

All provider I/O is replaced by deterministic fakes; no real provider is needed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from models.base import (
    CAP_CHAT,
    CAP_EMBEDDINGS,
    CAP_IMAGE_GENERATION,
    CAP_STREAMING,
    CAP_VIDEO_GENERATION,
    CAP_VISION,
    COST_TIER_FREE,
    COST_TIER_UNKNOWN,
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_IMAGE,
    KIND_VIDEO,
    STATUS_AVAILABLE,
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
    USABLE_STATUSES,
    ChatMessage,
    Completion,
    EmbeddingResult,
    ModelAdapter,
    infer_modality,
)
from models.catalog import (
    CATALOG,
    ModelCatalogEntry,
    catalog_by_kind,
    catalog_entries,
    catalog_ids,
    catalog_providers,
    get_catalog_entry,
    is_local_provider,
)
from models.registry import ModelInfo, ModelRegistry
from models.router import (
    TASK_CHAT,
    TASK_CODE,
    TASK_IMAGE,
    TASK_REQUIREMENTS,
    TASK_VIDEO,
    TASK_VISION,
    ModelRouter,
    _satisfies_required,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The unified metadata vocabulary every catalog entry must expose.
REQUIRED_METADATA_FIELDS = (
    "id",
    "name",
    "family",
    "provider",
    "modality",
    "capabilities",
    "context_window",
    "reasoning",
    "vision",
    "tools",
    "streaming",
    "local",
    "cost_tier",
    "status",
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeAdapter(ModelAdapter):
    """Deterministic adapter whose discovery/probe behaviour is controllable."""

    name = "openai_compatible"
    provider = "openai_compatible"

    def __init__(
        self,
        models: list[str] | None = None,
        *,
        configured: bool = True,
        fail_complete: bool = False,
    ) -> None:
        self._models = models or ["fake-chat-1"]
        self.configured = configured
        self.fail_complete = fail_complete
        self.complete_calls = 0

    def is_configured(self) -> bool:
        return self.configured

    def list_models(self) -> list[str]:
        return list(self._models)

    def complete(self, messages: list[ChatMessage], model: str, **opts) -> Completion:
        self.complete_calls += 1
        if self.fail_complete:
            from backend.app.core.errors import ModelUnavailableError

            raise ModelUnavailableError("Model provider refused the request (billing/quota notice)")
        return Completion(text="pong", model=model, provider=self.provider, tokens_in=1, tokens_out=1)

    def stream(self, messages: list[ChatMessage], model: str, **opts):
        yield "pong"

    def embed(self, texts: list[str], model: str, **opts) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[0.1] for _ in texts], model=model, provider=self.provider, dimensions=1)


def make_registry(*adapters: tuple[str, ModelAdapter]) -> ModelRegistry:
    reg = ModelRegistry(build_adapters=False)
    for name, adapter in adapters:
        reg.register_adapter(name, adapter)
    return reg


class _StubModel:
    """Minimal model object for router-gate unit checks."""

    def __init__(self, model_id: str, capabilities: list[str], *, kind: str = KIND_CHAT, status: str = STATUS_AVAILABLE) -> None:
        self.id = model_id
        self.capabilities = capabilities
        self.type = kind
        self.status = status
        self.provider = "stub"
        self.local = False
        self.context_length = 4096


# --------------------------------------------------------------------------- #
# 1. Catalog metadata completeness
# --------------------------------------------------------------------------- #
def test_catalog_is_non_empty_and_typed():
    assert len(CATALOG) >= 40, "catalog should cover a modern, multi-modal set"
    assert all(isinstance(e, ModelCatalogEntry) for e in CATALOG)


def test_every_entry_exposes_the_unified_metadata_vocabulary():
    for entry in CATALOG:
        data = entry.to_dict()
        for field in REQUIRED_METADATA_FIELDS:
            assert field in data, f"{entry.id} missing '{field}'"
        assert entry.id and entry.name and entry.family and entry.provider
        assert isinstance(data["modality"], list) and data["modality"]
        assert isinstance(data["capabilities"], list) and data["capabilities"]
        assert isinstance(entry.context_window, int) and entry.context_window >= 0
        assert all(isinstance(v, bool) for v in (entry.reasoning, entry.vision, entry.tools, entry.streaming, entry.local))


def test_catalog_ids_are_unique():
    ids = catalog_ids()
    assert len(ids) == len(set(ids)), "catalog model ids must be unique"


def test_capability_flags_match_capability_list():
    """Boolean flags and the capability list must not contradict each other."""
    for entry in CATALOG:
        caps = set(entry.capabilities)
        if entry.kind == KIND_CHAT:
            assert entry.streaming is True
            assert (CAP_STREAMING in caps) is True
            assert (CAP_VISION in caps) == entry.vision
            assert entry.tools is False or CAP_CHAT in caps
        if entry.kind == KIND_IMAGE:
            assert entry.capabilities == (CAP_IMAGE_GENERATION,)
            assert entry.streaming is False and entry.vision is False
        if entry.kind == KIND_VIDEO:
            assert entry.capabilities == (CAP_VIDEO_GENERATION,)
        if entry.kind == KIND_EMBEDDING:
            assert entry.capabilities == (CAP_EMBEDDINGS,)


def test_vision_entries_use_image_input_modality():
    for entry in CATALOG:
        if entry.vision:
            assert "image" in entry.modality, f"{entry.id} declares vision without image modality"
            assert CAP_VISION in entry.capabilities


def test_catalog_covers_required_modern_families():
    ids = set(catalog_ids())
    required = {
        "qwen3:4b",
        "qwen3-coder:30b",
        "qwen3-vl:8b",
        "deepseek-r1:8b",
        "gpt-oss:20b",
        "glm-4.5-air",
        "devstral-small:24b",
        "mistral-small3.2:24b",
        "gemma3:4b",
        "flux.1-dev",
        "qwen-image",
        "wan2.2-t2v",
        "hunyuanvideo",
    }
    missing = required - ids
    assert not missing, f"catalog missing required modern models: {sorted(missing)}"


def test_catalog_kinds_cover_chat_embedding_image_video():
    for kind in (KIND_CHAT, KIND_EMBEDDING, KIND_IMAGE, KIND_VIDEO):
        assert catalog_by_kind(kind), f"catalog has no '{kind}' entries"


def test_qwen3_4b_is_preserved():
    entry = get_catalog_entry("qwen3:4b")
    assert entry is not None
    assert entry.family == "Qwen3"
    assert entry.reasoning is True
    assert entry.context_window == 131072
    assert entry.local is True


# --------------------------------------------------------------------------- #
# 2. Status semantics — no false availability
# --------------------------------------------------------------------------- #
def test_catalog_defaults_to_not_configured():
    assert all(e.status == STATUS_NOT_CONFIGURED for e in CATALOG)


def test_catalog_never_claims_available():
    assert not any(e.status == STATUS_AVAILABLE for e in CATALOG)


def test_not_configured_is_not_a_usable_status():
    assert STATUS_NOT_CONFIGURED not in USABLE_STATUSES
    assert USABLE_STATUSES == (STATUS_AVAILABLE,)


def test_catalog_entries_only_use_known_statuses():
    from models.base import ALL_STATUSES

    for entry in CATALOG:
        assert entry.status in ALL_STATUSES


def test_local_provider_classification():
    from models.catalog import LOCAL_PROVIDERS

    assert is_local_provider("ollama") is True
    assert is_local_provider("localai") is True
    assert is_local_provider("openai") is False
    assert is_local_provider("") is False
    # Every local-runtime entry must be flagged local; cloud vendors must not be.
    for entry in CATALOG:
        if entry.provider in LOCAL_PROVIDERS:
            assert entry.local is True
        else:
            assert entry.local is False


def test_cost_tiers_are_from_the_vocabulary():
    from models.base import ALL_COST_TIERS

    for entry in CATALOG:
        assert entry.cost_tier in ALL_COST_TIERS
    # qwen3:4b is a local model → free tier.
    assert get_catalog_entry("qwen3:4b").cost_tier == COST_TIER_FREE
    # Unknown tier is a valid fallback value.
    assert COST_TIER_UNKNOWN in ALL_COST_TIERS


# --------------------------------------------------------------------------- #
# 3. Registry ⇄ catalog merge
# --------------------------------------------------------------------------- #
def test_catalog_is_separate_from_runtime_discovery():
    """An empty runtime still yields the full declared catalog (NOT_CONFIGURED)."""
    reg = make_registry()
    assert reg.refresh(force=True) == {}, "no adapters → no discovered models"
    catalog = reg.catalog()
    assert len(catalog) == len(CATALOG)
    assert all(m.status == STATUS_NOT_CONFIGURED for m in catalog)
    assert all(m.config_source == "catalog" for m in catalog)


def test_catalog_view_marks_undiscovered_models_not_configured():
    reg = make_registry(("openai_compatible", FakeAdapter(["gpt-5.4-mini"], fail_complete=False)))
    reg.refresh(force=True)
    catalog = {m.id: m for m in reg.catalog()}

    # Discovered + probed → AVAILABLE.
    assert catalog["gpt-5.4-mini"].status == STATUS_AVAILABLE
    # Known but not discovered → NOT_CONFIGURED (never AVAILABLE).
    assert catalog["flux.1-dev"].status == STATUS_NOT_CONFIGURED
    assert catalog["qwen3:4b"].status == STATUS_NOT_CONFIGURED


def test_registry_merges_catalog_metadata_into_discovered_model():
    reg = make_registry(("openai_compatible", FakeAdapter(["qwen3:4b"], fail_complete=False)))
    reg.refresh(force=True)
    info = reg.get("qwen3:4b")
    assert info.status == STATUS_AVAILABLE
    assert info.catalog is True
    assert info.family == "Qwen3"  # enriched from catalog
    assert info.cost_tier == COST_TIER_FREE
    assert info.reasoning is True
    assert "chat" in info.capabilities
    assert info.modality  # modality vocabulary populated


def test_catalog_metadata_never_overrides_probed_status():
    """A catalog-known model that fails its probe stays UNAVAILABLE."""
    reg = make_registry(("openai_compatible", FakeAdapter(["qwen3:4b"], fail_complete=True)))
    reg.refresh(force=True)
    assert reg.get("qwen3:4b").status == STATUS_UNAVAILABLE
    # And the catalog view reflects the *real* (unavailable) status.
    view = reg.get_catalog_entry("qwen3:4b")
    assert view.status == STATUS_UNAVAILABLE
    assert view.family == "Qwen3"  # metadata still merged


def test_discovered_unknown_model_has_no_catalog_flag():
    reg = make_registry(("openai_compatible", FakeAdapter(["totally-unknown-model"], fail_complete=False)))
    reg.refresh(force=True)
    info = reg.get("totally-unknown-model")
    assert info.catalog is False
    assert info.family == ""
    assert info.cost_tier == COST_TIER_UNKNOWN


def test_model_info_to_dict_includes_new_and_legacy_fields():
    reg = make_registry(("openai_compatible", FakeAdapter(["qwen3:4b"], fail_complete=False)))
    reg.refresh(force=True)
    data = reg.get("qwen3:4b").to_dict()
    for field in REQUIRED_METADATA_FIELDS + ("health", "last_checked", "error", "config_source", "catalog"):
        assert field in data, field


def test_get_catalog_entry_returns_none_for_unknown():
    reg = make_registry()
    assert reg.get_catalog_entry("no-such-model") is None


# --------------------------------------------------------------------------- #
# 4. Capability filtering — the router gate
# --------------------------------------------------------------------------- #
def test_requirement_gate_blocks_chat_only_model_for_vision():
    chat_only = _StubModel("chat-only", [CAP_CHAT, CAP_STREAMING])
    assert _satisfies_required(chat_only, TASK_REQUIREMENTS[TASK_VISION]) is False
    vision_model = _StubModel("sees", [CAP_CHAT, CAP_STREAMING, CAP_VISION])
    assert _satisfies_required(vision_model, TASK_REQUIREMENTS[TASK_VISION]) is True


def test_vision_image_video_requirements_are_hard_gated():
    assert CAP_VISION in TASK_REQUIREMENTS[TASK_VISION].required
    assert CAP_IMAGE_GENERATION in TASK_REQUIREMENTS[TASK_IMAGE].required
    assert CAP_VIDEO_GENERATION in TASK_REQUIREMENTS[TASK_VIDEO].required
    # Chat/code/tools/reasoning keep no hard gate (backwards compatible).
    for task in (TASK_CHAT, TASK_CODE):
        assert TASK_REQUIREMENTS[task].required == ()


def test_router_never_selects_chat_only_for_vision():
    reg = make_registry(("openai_compatible", FakeAdapter(["plain-chat-model"], fail_complete=False)))
    reg.refresh(force=True)
    decision = ModelRouter(reg).select(TASK_VISION)
    assert decision.model is None
    assert decision.available is False


def test_router_selects_vision_model_when_present():
    reg = make_registry(("openai_compatible", FakeAdapter(["qwen3-vl-8b"], fail_complete=False)))
    reg.refresh(force=True)
    decision = ModelRouter(reg).select(TASK_VISION)
    assert decision.model == "qwen3-vl-8b"


def test_router_never_selects_chat_only_for_image_or_video():
    reg = make_registry(("openai_compatible", FakeAdapter(["plain-chat-model"], fail_complete=False)))
    reg.refresh(force=True)
    router = ModelRouter(reg)
    assert router.select(TASK_IMAGE).model is None
    assert router.select(TASK_VIDEO).model is None


def test_router_selects_dedicated_image_and_video_models():
    reg = make_registry(("openai_compatible", FakeAdapter(["dall-e-3", "wan2.2-t2v"], fail_complete=False)))
    reg.refresh(force=True)
    router = ModelRouter(reg)
    assert router.select(TASK_IMAGE).model == "dall-e-3"
    assert router.select(TASK_VIDEO).model == "wan2.2-t2v"


def test_router_candidates_respects_capability_gate():
    reg = make_registry(("openai_compatible", FakeAdapter(["plain-chat-model"], fail_complete=False)))
    reg.refresh(force=True)
    assert ModelRouter(reg).candidates(TASK_VISION) == []


# --------------------------------------------------------------------------- #
# 5. Modality vocabulary
# --------------------------------------------------------------------------- #
def test_infer_modality_shapes():
    assert infer_modality(KIND_CHAT) == ["text"]
    assert infer_modality(KIND_CHAT, vision=True) == ["text", "image"]
    assert infer_modality(KIND_IMAGE) == ["text", "image"]
    assert infer_modality(KIND_VIDEO) == ["text", "video"]
    assert infer_modality(KIND_EMBEDDING) == ["text", "embedding"]


# --------------------------------------------------------------------------- #
# 6. No hardcoding — no secrets, credentials or endpoints in the catalog
# --------------------------------------------------------------------------- #
def test_catalog_source_contains_no_secrets_or_credentials():
    source = (REPO_ROOT / "models" / "catalog.py").read_text(encoding="utf-8")
    forbidden = ("sk-", "ghp_", "gsk_", "Bearer ", "api_key", "API_KEY", "password", "token=", "secret")
    for marker in forbidden:
        assert marker not in source, f"catalog must not hardcode '{marker}'"


def test_catalog_source_contains_no_endpoint_urls():
    source = (REPO_ROOT / "models" / "catalog.py").read_text(encoding="utf-8")
    assert "http://" not in source
    assert "https://" not in source


def test_catalog_performs_no_network_io():
    """The catalog module must not import networking or perform I/O."""
    source = (REPO_ROOT / "models" / "catalog.py").read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "urlopen" not in source
    assert "socket" not in source


def test_catalog_providers_are_bare_labels():
    """Provider labels are short identifiers, never connection strings."""
    for provider in catalog_providers():
        assert re.fullmatch(r"[a-z0-9_.-]+", provider), provider
        assert "@" not in provider and "/" not in provider and ":" not in provider


# --------------------------------------------------------------------------- #
# 7. Catalog helpers
# --------------------------------------------------------------------------- #
def test_catalog_entries_helper_returns_tuple_copy():
    entries = catalog_entries()
    assert isinstance(entries, tuple)
    assert len(entries) == len(CATALOG)


def test_catalog_lookup_returns_none_for_unknown():
    assert get_catalog_entry("does-not-exist") is None


@pytest.mark.parametrize(
    "model_id,expected_kind",
    [
        ("qwen3:4b", KIND_CHAT),
        ("text-embedding-3-large", KIND_EMBEDDING),
        ("flux.1-dev", KIND_IMAGE),
        ("hunyuanvideo", KIND_VIDEO),
    ],
)
def test_catalog_kind_assignment(model_id, expected_kind):
    assert get_catalog_entry(model_id).kind == expected_kind


def test_catalog_kind_is_consistent_with_runtime_inference():
    """Runtime ``infer_kind`` must agree with each catalog entry's declared kind.

    Guards against drift: if the catalog declares a model as an image/video
    model, runtime discovery of the same id must classify it the same way.
    """
    from models.base import infer_kind

    for entry in CATALOG:
        assert infer_kind(entry.id) == entry.kind, f"{entry.id}: catalog={entry.kind} inferred={infer_kind(entry.id)}"
