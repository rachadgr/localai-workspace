"""Model Catalog **API + UI** integration tests.

The declarative catalog and its registry merge are already unit-tested in
``test_model_catalog.py``. This module covers the *integration* added on top:

* ``GET /api/models/catalog`` — the additive endpoint that merges declared
  metadata with the **real** runtime status;
* the honesty guarantees at the API boundary — ``AVAILABLE`` only when the runtime
  confirmed it, ``NOT_CONFIGURED`` for declared-but-uninstalled models, and no
  secret ever leaves the endpoint;
* backward compatibility of ``/api/models`` (unchanged shape);
* the static ``/models.html`` page wiring (catalog section, filters, statuses).

All provider I/O is replaced by deterministic fakes; no real provider is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.routers.models import _catalog_categories, _catalog_entry_view
from models.base import (
    STATUS_AVAILABLE,
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
    ChatMessage,
    Completion,
    EmbeddingResult,
    ModelAdapter,
)
from models.catalog import CATALOG
from models.registry import ModelRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Fields every catalog row returned by the API must expose.
REQUIRED_ROW_FIELDS = (
    "id",
    "name",
    "family",
    "provider",
    "kind",
    "modality",
    "capabilities",
    "category",
    "context_window",
    "reasoning",
    "vision",
    "tools",
    "streaming",
    "local",
    "cost_tier",
    "status",
    "available",
    "runtime",
    "catalog",
    "config_source",
    "last_checked",
    "error",
    "notes",
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeAdapter(ModelAdapter):
    name = "openai_compatible"
    provider = "openai_compatible"

    def __init__(self, models: list[str] | None = None, *, configured: bool = True, fail_complete: bool = False) -> None:
        self._models = models or ["fake-chat-1"]
        self.configured = configured
        self.fail_complete = fail_complete

    def is_configured(self) -> bool:
        return self.configured

    def list_models(self) -> list[str]:
        return list(self._models)

    def complete(self, messages: list[ChatMessage], model: str, **opts) -> Completion:
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


# --------------------------------------------------------------------------- #
# 1. API surface — /api/models/catalog
# --------------------------------------------------------------------------- #
def test_catalog_endpoint_requires_auth():
    # Use a dedicated client so the shared session client's Authorization header
    # (set by the auth_client fixture) does not leak into this check.
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as fresh:
        assert fresh.get("/api/models/catalog").status_code == 401


def test_catalog_endpoint_shape(auth_client):
    r = auth_client.get("/api/models/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body["secrets_exposed"] is False
    for key in ("total", "available", "providers", "categories", "statuses", "counts", "models", "config_source"):
        assert key in body, key
    assert body["config_source"] == "catalog+runtime"
    assert body["total"] == len(body["models"])
    assert isinstance(body["models"], list) and body["models"]


def test_catalog_endpoint_rows_expose_unified_fields(auth_client):
    rows = auth_client.get("/api/models/catalog").json()["models"]
    for row in rows:
        for field in REQUIRED_ROW_FIELDS:
            assert field in row, f"{row.get('id')} missing '{field}'"
        assert isinstance(row["modality"], list) and row["modality"]
        assert isinstance(row["capabilities"], list) and row["capabilities"]
        assert isinstance(row["category"], list) and row["category"]
        assert isinstance(row["local"], bool)
        assert isinstance(row["reasoning"], bool) and isinstance(row["vision"], bool)
        assert isinstance(row["tools"], bool) and isinstance(row["streaming"], bool)


def test_catalog_endpoint_statuses_are_from_the_vocabulary(auth_client):
    body = auth_client.get("/api/models/catalog").json()
    allowed = set(body["statuses"])
    assert allowed == {"AVAILABLE", "NOT_CONFIGURED", "MISCONFIGURED", "UNAVAILABLE", "DISABLED", "LOADING", "ERROR"}
    for row in body["models"]:
        assert row["status"] in allowed


def test_catalog_available_flag_matches_status_and_count(auth_client):
    body = auth_client.get("/api/models/catalog").json()
    available_rows = [m for m in body["models"] if m["status"] == STATUS_AVAILABLE]
    # available flag is derived from the (runtime) status, never from catalog metadata.
    for row in body["models"]:
        assert row["available"] == (row["status"] == STATUS_AVAILABLE)
    assert body["available"] == len(available_rows)
    assert body["counts"][STATUS_AVAILABLE] == len(available_rows)


def test_catalog_endpoint_never_leaks_secrets(auth_client):
    body = auth_client.get("/api/models/catalog").json()
    blob = str(body)
    for marker in ("sk-", "gsk-", "ghp_", "Bearer ", "api_key", "password"):
        assert marker not in blob, f"leaked {marker}"


def test_catalog_filter_vocabulary_is_present(auth_client):
    body = auth_client.get("/api/models/catalog").json()
    assert set(body["categories"]) == {"chat", "reasoning", "coding", "vision", "image", "video", "embedding"}
    # categories used by rows must be a subset of the advertised vocabulary.
    advertised = set(body["categories"])
    for row in body["models"]:
        assert set(row["category"]) <= advertised


def test_catalog_providers_are_bare_labels(auth_client):
    body = auth_client.get("/api/models/catalog").json()
    assert body["providers"]
    for provider in body["providers"]:
        assert "@" not in provider and "/" not in provider and ":" not in provider


def test_catalog_endpoint_is_backward_compatible_with_models(auth_client):
    """Adding /api/models/catalog must not change /api/models' shape or routing."""
    legacy = auth_client.get("/api/models")
    assert legacy.status_code == 200
    legacy_body = legacy.json()
    for key in ("providers", "models", "chat_usable", "models_total", "status"):
        assert key in legacy_body, key

    # Static sub-paths are not swallowed by the /models/{model_id:path} route.
    assert auth_client.get("/api/models/providers").status_code == 200
    assert auth_client.get("/api/models/router").status_code == 200
    assert auth_client.get("/api/models/catalog").status_code == 200


def test_catalog_covers_the_declared_catalog(auth_client):
    rows = auth_client.get("/api/models/catalog").json()["models"]
    ids = {row["id"] for row in rows}
    assert ids == set(catalog_id_list()), "catalog API must expose every declared model"


def catalog_id_list() -> list[str]:
    return [entry.id for entry in CATALOG]


# --------------------------------------------------------------------------- #
# 2. Merge semantics — runtime status always wins over catalog metadata
# --------------------------------------------------------------------------- #
def test_catalog_view_status_is_available_only_when_runtime_confirms():
    reg = make_registry(("openai_compatible", FakeAdapter(["qwen3:4b"], fail_complete=False)))
    reg.refresh(force=True)
    view = _catalog_entry_view(reg.get_catalog_entry("qwen3:4b"))
    assert view["status"] == STATUS_AVAILABLE
    assert view["available"] is True
    assert view["runtime"] is True
    assert view["catalog"] is True
    # Declared metadata is merged in…
    assert view["family"] == "Qwen3"
    assert view["reasoning"] is True
    assert "reasoning" in view["category"]
    # …but ``local`` reflects the *runtime* provider (a non-local fake here), not
    # the catalog's ollama variant — locality is a runtime property.
    assert view["local"] is False


def test_catalog_placeholder_reports_declared_local_for_ollama():
    """An undiscovered catalog entry keeps its declared provider/locality."""
    reg = make_registry()
    reg.refresh(force=True)
    view = _catalog_entry_view(reg.get_catalog_entry("qwen3:4b"))
    assert view["status"] == STATUS_NOT_CONFIGURED
    assert view["provider"] == "ollama"
    assert view["local"] is True


def test_catalog_view_never_overrides_probed_status():
    """A catalog-known model that fails its probe stays UNAVAILABLE in the view."""
    reg = make_registry(("openai_compatible", FakeAdapter(["qwen3:4b"], fail_complete=True)))
    reg.refresh(force=True)
    view = _catalog_entry_view(reg.get_catalog_entry("qwen3:4b"))
    assert view["status"] == STATUS_UNAVAILABLE
    assert view["available"] is False
    # Metadata still merged, but never claims usability.
    assert view["family"] == "Qwen3"


def test_catalog_view_marks_undiscovered_models_not_configured():
    reg = make_registry()  # no adapters → nothing discovered
    reg.refresh(force=True)
    view = _catalog_entry_view(reg.get_catalog_entry("flux.1-dev"))
    assert view["status"] == STATUS_NOT_CONFIGURED
    assert view["available"] is False
    assert view["runtime"] is False
    assert view["catalog"] is True
    # An image model is categorised as image even when NOT_CONFIGURED.
    assert "image" in view["category"]


def test_not_configured_is_never_available_across_the_whole_catalog():
    reg = make_registry()
    reg.refresh(force=True)
    for entry in CATALOG:
        view = _catalog_entry_view(reg.get_catalog_entry(entry.id))
        assert view["status"] == STATUS_NOT_CONFIGURED
        assert view["available"] is False


# --------------------------------------------------------------------------- #
# 3. Category derivation (declared metadata → coarse UI labels)
# --------------------------------------------------------------------------- #
class _StubInfo:
    def __init__(self, **kw) -> None:
        self.id = kw.get("id", "m")
        self.name = kw.get("name", "m")
        self.provider = kw.get("provider", "p")
        self.type = kw.get("kind", "chat")
        self.capabilities = kw.get("capabilities", ["chat"])
        self.modality = kw.get("modality", ["text"])
        self.context_length = kw.get("context_length", 0)
        self.reasoning = kw.get("reasoning", False)
        self.vision = kw.get("vision", False)
        self.tools = kw.get("tools", False)
        self.streaming = kw.get("streaming", True)
        self.local = kw.get("local", False)
        self.cost_tier = kw.get("cost_tier", "unknown")
        self.status = kw.get("status", STATUS_NOT_CONFIGURED)
        self.catalog = True
        self.config_source = "catalog"
        self.endpoint = ""
        self.last_checked = 0.0
        self.error = ""
        self.notes = ""


def test_category_derivation_for_reasoning_coding_vision_chat():
    info = _StubInfo(capabilities=["chat", "streaming", "reasoning", "code", "vision"], reasoning=True, vision=True)
    cats = _catalog_categories(info)
    assert cats == ["chat", "reasoning", "coding", "vision"]


def test_category_derivation_for_image_video_embedding():
    assert _catalog_categories(_StubInfo(kind="image")) == ["image"]
    assert _catalog_categories(_StubInfo(kind="video")) == ["video"]
    assert _catalog_categories(_StubInfo(kind="embedding")) == ["embedding"]


def test_category_is_descriptive_not_a_status_claim():
    """A NOT_CONFIGURED reasoning model is still categorised as reasoning."""
    info = _StubInfo(capabilities=["chat", "reasoning"], reasoning=True, status=STATUS_NOT_CONFIGURED)
    cats = _catalog_categories(info)
    assert "reasoning" in cats
    assert _catalog_entry_view(info)["available"] is False


# --------------------------------------------------------------------------- #
# 4. Static frontend wiring (/models.html)
# --------------------------------------------------------------------------- #
def test_models_frontend_served_with_catalog_section(client):
    r = client.get("/models.html")
    assert r.status_code == 200
    html = r.text
    assert "Model Catalog" in html
    # The page must call the new endpoint…
    assert "/models/catalog" in html
    # …and expose the required filter controls.
    for eid in ("catSearch", "catCategory", "catStatus", "catProvider", "catalogTable"):
        assert f'id="{eid}"' in html, eid


def test_models_frontend_distinguishes_all_four_statuses(client):
    html = client.get("/models.html").text
    # CSS classes / legend for the four required, clearly-distinguished statuses.
    for status in ("AVAILABLE", "NOT_CONFIGURED", "MISCONFIGURED", "UNAVAILABLE"):
        assert f".{status}" in html or f">{status}<" in html, status
    # The page never hardcodes a provider secret.
    assert "OPENAI_API_KEY" not in html


def test_models_frontend_filter_options_cover_modalities(client):
    html = client.get("/models.html").text
    for modality in ("chat", "reasoning", "coding", "vision", "image", "video", "embedding"):
        assert f"<option>{modality}</option>" in html, modality


@pytest.mark.parametrize(
    "status",
    ["AVAILABLE", "NOT_CONFIGURED", "MISCONFIGURED", "UNAVAILABLE", "DISABLED", "LOADING", "ERROR"],
)
def test_catalog_status_filter_has_every_status(client, status):
    html = client.get("/models.html").text
    assert f"<option>{status}</option>" in html, status
