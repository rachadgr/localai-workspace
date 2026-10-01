"""Local Model **Activation** tests.

Locks in the additive layer that sits **on top of** the declarative Model Catalog and
Task Routing and answers the operational question: *of the models declared for the
local runtime, which are actually installed here, and which of those are genuinely
usable right now?*

Covered here:

* **discovery** — a model the local runtime really serves becomes ``ACTIVE`` /
  ``AVAILABLE`` after a *real* probe;
* **not installed** — a declared-but-absent local model is ``NOT_INSTALLED`` and
  stays ``NOT_CONFIGURED`` (never available);
* **probe failure** — an installed model whose probe fails is ``INSTALLED`` /
  ``UNAVAILABLE``, never ``AVAILABLE``;
* **metadata merge** — the registry adopts the *catalog* capability vocabulary
  (e.g. ``reasoning`` for ``qwen3:4b``, ``vision`` for ``gemma3:4b``) instead of the
  coarse id heuristic, so an installed model routes correctly;
* **runtime-status precedence** — catalog metadata never overrides the probed
  status;
* **capability validation** — the merged capabilities equal the catalog's exactly;
* **no weights downloaded** — the layer has no download path, performs no extra
  provider round-trip beyond the registry's cached discovery/probes, and the module
  imports no networking library;
* **the qwen3:4b guarantee** — when Ollama serves it, it is ``AVAILABLE`` and is
  routed for ``chat`` / ``text`` / ``coding`` / ``reasoning`` / ``tools``, while
  ``vision`` / ``image`` / ``video`` / ``i2v`` / ``embedding`` stay
  ``NO_CAPABLE_MODEL`` (no local model provides them).

All provider I/O is replaced by deterministic fakes — **no network is used**.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.errors import ModelUnavailableError
from models.base import (
    CAP_CODE,
    CAP_EMBEDDINGS,
    CAP_IMAGE_GENERATION,
    CAP_REASONING,
    CAP_VIDEO_GENERATION,
    CAP_VISION,
    ChatMessage,
    Completion,
    EmbeddingResult,
    ModelAdapter,
    ModelDescriptor,
    STATUS_AVAILABLE,
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
)
from models.catalog import CATALOG, catalog_entries, get_catalog_entry
from models.local import (
    ACTIVATION_ACTIVE,
    ACTIVATION_DISABLED,
    ACTIVATION_INSTALLED,
    ACTIVATION_NOT_INSTALLED,
    ALL_ACTIVATIONS,
    available_local_models,
    classify_local_activation,
    installed_local_ids,
    is_local_catalog_entry,
)
from models.registry import ModelRegistry
from models.router import (
    OUTCOME_NO_CAPABLE_MODEL,
    OUTCOME_SELECTED,
    TASK_CHAT,
    TASK_CODE,
    TASK_CODING,
    TASK_EMBEDDING,
    TASK_I2V,
    TASK_IMAGE,
    TASK_REASONING,
    TASK_TEXT,
    TASK_TOOLS,
    TASK_VIDEO,
    TASK_VISION,
    ModelRouter,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The tasks a plain local chat model (qwen3:4b) must be routed for.
QWEN3_TASKS = (TASK_CHAT, TASK_TEXT, TASK_CODING, TASK_CODE, TASK_REASONING, TASK_TOOLS)

#: The tasks no locally-installed chat model can serve (no capable local model).
NON_CHAT_TASKS = (TASK_VISION, TASK_IMAGE, TASK_VIDEO, TASK_I2V, TASK_EMBEDDING)


# --------------------------------------------------------------------------- #
# Fakes — deterministic, offline, no sockets
# --------------------------------------------------------------------------- #
class FakeOllama(ModelAdapter):
    """A controllable local Ollama runtime.

    ``installed`` is what the runtime actually *has* (discovery). ``fail_models``
    lists models whose real probe should fail. Every call is counted so tests can
    prove activation adds no unexpected traffic.
    """

    name = "ollama"
    provider = "ollama"
    is_local = True

    def __init__(self, installed: list[str], *, fail_models: set[str] | None = None) -> None:
        self._installed = list(installed)
        self.fail_models = set(fail_models or ())
        self.complete_calls: list[str] = []
        self.embed_calls: list[str] = []
        self.list_calls = 0

    def is_configured(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        self.list_calls += 1
        return list(self._installed)

    def discover(self) -> list[ModelDescriptor]:
        from models.base import infer_capabilities, infer_context, infer_kind

        return [
            ModelDescriptor(
                id=model_id,
                provider=self.provider,
                kind=infer_kind(model_id),
                capabilities=infer_capabilities(model_id).to_list(),
                context_length=infer_context(model_id),
                local=True,
            )
            for model_id in self._installed
        ]

    def complete(self, messages: list[ChatMessage], model: str, **opts) -> Completion:
        self.complete_calls.append(model)
        if model in self.fail_models:
            raise ModelUnavailableError("local model failed a real request")
        return Completion(text="pong", model=model, provider=self.provider, tokens_in=1, tokens_out=1)

    def stream(self, messages: list[ChatMessage], model: str, **opts):
        yield "pong"

    def embed(self, texts: list[str], model: str, **opts) -> EmbeddingResult:
        self.embed_calls.append(model)
        return EmbeddingResult(vectors=[[0.1] for _ in texts], model=model, provider=self.provider, dimensions=1)


def make_local_registry(adapter: ModelAdapter) -> ModelRegistry:
    reg = ModelRegistry(build_adapters=False)
    reg.register_adapter("ollama", adapter)
    return reg


# --------------------------------------------------------------------------- #
# 1. Discovery — a model the local runtime really serves becomes ACTIVE/AVAILABLE
# --------------------------------------------------------------------------- #
def test_installed_local_model_is_discovered_and_activated():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    reg.refresh(force=True)

    # Discovery: the model is present in the runtime view and probed AVAILABLE.
    info = reg.get("qwen3:4b")
    assert info is not None and info.status == STATUS_AVAILABLE

    outcomes = reg.local_activation().run()
    outcome = outcomes["qwen3:4b"]
    assert outcome.installed is True
    assert outcome.activation == ACTIVATION_ACTIVE
    assert outcome.runtime_status == STATUS_AVAILABLE
    assert outcome.probed is True and outcome.probe_ok is True
    assert outcome.available is True


def test_installed_model_appears_in_available_local_models():
    reg = make_local_registry(FakeOllama(["qwen3:4b", "deepseek-r1:8b"]))
    reg.refresh(force=True)
    assert available_local_models(reg) == ["deepseek-r1:8b", "qwen3:4b"]


def test_installed_ids_come_only_from_local_providers():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    runtime = reg.refresh(force=True)
    assert installed_local_ids(runtime) == {"qwen3:4b"}
    # An empty runtime has nothing installed.
    assert installed_local_ids({}) == set()


# --------------------------------------------------------------------------- #
# 2. Not installed — declared locally but absent → NOT_CONFIGURED, never available
# --------------------------------------------------------------------------- #
def test_declared_but_absent_local_model_is_not_installed():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))  # only qwen3:4b is present
    outcomes = reg.local_activation().run()

    other = outcomes["gemma3:4b"]
    assert other.installed is False
    assert other.activation == ACTIVATION_NOT_INSTALLED
    assert other.runtime_status == STATUS_NOT_CONFIGURED
    assert other.available is False
    assert other.probed is False  # nothing was probed → nothing was downloaded


def test_every_uninstalled_local_entry_stays_not_configured():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    outcomes = reg.local_activation().run()
    installed_ids = {"qwen3:4b"}
    for entry in CATALOG:
        if not is_local_catalog_entry(entry.id) or entry.id in installed_ids:
            continue
        outcome = outcomes[entry.id]
        assert outcome.activation == ACTIVATION_NOT_INSTALLED, entry.id
        assert outcome.runtime_status == STATUS_NOT_CONFIGURED, entry.id


def test_cloud_and_non_local_models_are_out_of_scope():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    outcomes = reg.local_activation().run()
    # Cloud ids are never part of the local activation report.
    assert "gpt-5" not in outcomes
    assert "claude-sonnet-4-5" not in outcomes
    # Every reported id is a local catalog entry.
    for model_id in outcomes:
        assert is_local_catalog_entry(model_id), model_id


def test_empty_runtime_reports_all_local_entries_not_installed():
    reg = make_local_registry(FakeOllama([]))
    summary = reg.local_activation().summary()
    assert summary["installed"] == []
    assert summary["available"] == []
    assert summary["active"] == []
    expected_local = sorted(e.id for e in catalog_entries() if e.local)
    assert summary["not_installed"] == expected_local


# --------------------------------------------------------------------------- #
# 3. Probe failure — installed but failing → INSTALLED / UNAVAILABLE, never AVAILABLE
# --------------------------------------------------------------------------- #
def test_installed_model_whose_probe_fails_is_not_available():
    reg = make_local_registry(FakeOllama(["qwen3:4b"], fail_models={"qwen3:4b"}))
    outcomes = reg.local_activation().run(force=True)
    outcome = outcomes["qwen3:4b"]
    assert outcome.installed is True
    assert outcome.activation == ACTIVATION_INSTALLED
    assert outcome.activation != ACTIVATION_ACTIVE
    assert outcome.runtime_status == STATUS_UNAVAILABLE
    assert outcome.available is False
    assert outcome.probed is True and outcome.probe_ok is False
    # The failure is surfaced honestly, and does not leak into the router.
    assert outcome.probe_error


def test_failed_probe_model_is_not_routed():
    reg = make_local_registry(FakeOllama(["qwen3:4b"], fail_models={"qwen3:4b"}))
    reg.refresh(force=True)
    decision = ModelRouter(reg).select(TASK_CHAT)
    assert decision.model is None
    assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


def test_probe_failure_is_reported_in_summary():
    reg = make_local_registry(FakeOllama(["qwen3:4b"], fail_models={"qwen3:4b"}))
    summary = reg.local_activation().summary(force=True)
    assert summary["installed"] == ["qwen3:4b"]
    assert summary["available"] == []
    assert summary["installed_but_not_usable"] == ["qwen3:4b"]


def test_probe_disabled_never_claims_available(monkeypatch):
    """With probing off, an installed model is LOADING → INSTALLED, not ACTIVE."""
    from configs.settings import settings as cfg

    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    monkeypatch.setattr(cfg, "model_probe_enabled", False, raising=False)
    reg.refresh(force=True)
    outcome = reg.local_activation().run(force=True)["qwen3:4b"]
    assert outcome.activation == ACTIVATION_INSTALLED
    assert outcome.available is False
    assert outcome.runtime_status != STATUS_AVAILABLE


# --------------------------------------------------------------------------- #
# 4. Metadata merge — the catalog vocabulary reaches the discovered model
# --------------------------------------------------------------------------- #
def test_qwen3_4b_adopts_catalog_reasoning_capability():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    info = reg.get("qwen3:4b")
    entry = get_catalog_entry("qwen3:4b")
    # The whole declared capability vocabulary is adopted, not just a subset.
    assert list(info.capabilities) == list(entry.capabilities)
    assert CAP_REASONING in info.capabilities
    assert info.reasoning is True
    assert info.catalog is True
    assert info.family == "Qwen3"


def test_vision_model_adopts_catalog_vision_and_modality():
    """gemma3:4b declares vision in the catalog but the id heuristic misses it."""
    reg = make_local_registry(FakeOllama(["gemma3:4b"]))
    info = reg.get("gemma3:4b")
    entry = get_catalog_entry("gemma3:4b")
    assert CAP_VISION in info.capabilities
    assert info.vision is True
    assert list(info.modality) == list(entry.modality)
    assert "image" in info.modality


def test_metadata_merge_uses_catalog_exactly_for_every_installed_model():
    installed = ["qwen3:4b", "qwen3-vl:8b", "deepseek-r1:8b", "gemma3:4b", "qwen3-coder:30b"]
    reg = make_local_registry(FakeOllama(installed))
    reg.refresh(force=True)
    for model_id in installed:
        info = reg.get(model_id)
        entry = get_catalog_entry(model_id)
        assert list(info.capabilities) == list(entry.capabilities), model_id
        assert list(info.modality) == list(entry.modality), model_id
        assert info.reasoning == entry.reasoning
        assert info.vision == entry.vision
        assert info.tools == entry.tools
        assert info.cost_tier == entry.cost_tier


def test_discovered_model_absent_from_catalog_keeps_heuristic_metadata():
    reg = make_local_registry(FakeOllama(["some-unknown-local-model"]))
    info = reg.get("some-unknown-local-model")
    assert info.catalog is False
    assert info.family == ""
    # No fabricated capabilities — the runtime heuristic is untouched.
    assert "chat" in info.capabilities


# --------------------------------------------------------------------------- #
# 5. Runtime-status precedence — catalog never overrides the probe
# --------------------------------------------------------------------------- #
def test_catalog_metadata_never_overrides_a_failed_probe():
    reg = make_local_registry(FakeOllama(["qwen3:4b"], fail_models={"qwen3:4b"}))
    reg.refresh(force=True)
    info = reg.get("qwen3:4b")
    # Metadata merged…
    assert CAP_REASONING in info.capabilities
    # …but the probed (unavailable) status wins.
    assert info.status == STATUS_UNAVAILABLE
    catalog_view = reg.get_catalog_entry("qwen3:4b")
    assert catalog_view.status == STATUS_UNAVAILABLE


def test_available_status_only_follows_a_real_probe():
    """Listing alone is not availability: the registry must have probed it."""
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    info = reg.get("qwen3:4b")
    assert info.status == STATUS_AVAILABLE
    assert info.health.get("ok") is True  # a real probe actually ran


def test_activation_runtime_status_matches_registry_status():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    reg.refresh(force=True)
    outcome = reg.local_activation().run()["qwen3:4b"]
    assert outcome.runtime_status == reg.get("qwen3:4b").status


# --------------------------------------------------------------------------- #
# 6. Capability validation — merged caps drive the router gates correctly
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("task", QWEN3_TASKS)
def test_qwen3_4b_is_routed_for_text_capability_tasks(task):
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    reg.refresh(force=True)
    decision = ModelRouter(reg).select(task)
    assert decision.model == "qwen3:4b", task
    assert decision.outcome == OUTCOME_SELECTED


@pytest.mark.parametrize("task", NON_CHAT_TASKS)
def test_qwen3_4b_is_never_routed_for_non_chat_tasks(task):
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    reg.refresh(force=True)
    decision = ModelRouter(reg).select(task)
    assert decision.model is None, task
    assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


def test_capability_gate_still_blocks_a_vision_task_for_a_text_only_local_model():
    """The merged text-only capabilities must NOT claim vision."""
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    info = reg.get("qwen3:4b")
    assert CAP_VISION not in info.capabilities
    assert CAP_IMAGE_GENERATION not in info.capabilities
    assert CAP_VIDEO_GENERATION not in info.capabilities
    assert CAP_EMBEDDINGS not in info.capabilities


def test_local_vision_model_when_installed_is_routed_for_vision():
    """A locally-installed vision model (qwen3-vl:8b) IS routed for vision."""
    reg = make_local_registry(FakeOllama(["qwen3-vl:8b"]))
    reg.refresh(force=True)
    decision = ModelRouter(reg).select(TASK_VISION)
    assert decision.model == "qwen3-vl:8b"
    assert decision.outcome == OUTCOME_SELECTED


def test_local_embedder_when_installed_is_routed_for_embedding():
    reg = make_local_registry(FakeOllama(["nomic-embed-text"]))
    reg.refresh(force=True)
    decision = ModelRouter(reg).select(TASK_EMBEDDING)
    assert decision.model == "nomic-embed-text"
    assert decision.outcome == OUTCOME_SELECTED


def test_no_local_model_provides_image_or_video_generation():
    """Nothing local declares image/video generation → those tasks stay empty."""
    reg = make_local_registry(FakeOllama(["qwen3:4b", "gemma3:4b", "qwen3-vl:8b"]))
    reg.refresh(force=True)
    router = ModelRouter(reg)
    for task in (TASK_IMAGE, TASK_VIDEO, TASK_I2V):
        decision = router.select(task)
        assert decision.model is None, task
        assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


def test_coding_prefers_the_code_capable_local_model_when_installed():
    reg = make_local_registry(FakeOllama(["qwen3:4b", "qwen3-coder:30b"]))
    reg.refresh(force=True)
    decision = ModelRouter(reg).select(TASK_CODING)
    assert decision.model == "qwen3-coder:30b"  # code capability wins the soft rank
    assert CAP_CODE in reg.get(decision.model).capabilities


# --------------------------------------------------------------------------- #
# 7. No weights downloaded / no extra network I/O
# --------------------------------------------------------------------------- #
def test_activation_has_no_download_path():
    """The module must contain no pull/download *code path* (docstrings may name it)."""
    source = (REPO_ROOT / "models" / "local.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    for marker in ("/api/pull", "def pull", "requests.post", "requests.get", "urlopen(", ".download("):
        assert marker not in code, f"local activation must not contain '{marker}'"


def test_activation_module_imports_no_networking_library():
    source = (REPO_ROOT / "models" / "local.py").read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "import socket" not in source
    assert "from urllib" not in source


def test_activation_performs_no_extra_probe_beyond_the_registry():
    """Activation reuses the registry cache; it never re-probes on the fast path."""
    adapter = FakeOllama(["qwen3:4b"])
    reg = make_local_registry(adapter)
    reg.refresh(force=True)
    after_discovery = list(adapter.complete_calls)

    # Classify (pure) → zero I/O.
    classify_local_activation(reg.refresh(force=False))
    assert adapter.complete_calls == after_discovery

    # A non-forced activation run reads the cached verdict → still zero new probes.
    reg.local_activation().run(force=False)
    assert adapter.complete_calls == after_discovery


def test_activation_probes_each_installed_model_exactly_once():
    adapter = FakeOllama(["qwen3:4b", "gemma3:4b"])
    reg = make_local_registry(adapter)
    reg.refresh(force=True)
    # Exactly one real probe per installed model during discovery.
    assert sorted(adapter.complete_calls) == ["gemma3:4b", "qwen3:4b"]


def test_installed_but_absent_from_catalog_is_not_probed_by_activation():
    """A runtime model the catalog does not declare is outside activation scope."""
    adapter = FakeOllama(["qwen3:4b", "mystery-local-model"])
    reg = make_local_registry(adapter)
    reg.refresh(force=True)
    outcomes = reg.local_activation().run()
    # The activation report only covers catalog-declared local ids.
    assert "mystery-local-model" not in outcomes
    assert outcomes["qwen3:4b"].activation == ACTIVATION_ACTIVE


# --------------------------------------------------------------------------- #
# 8. Enabled / disabled / out-of-scope semantics + summary shape
# --------------------------------------------------------------------------- #
def test_activation_can_be_disabled(monkeypatch):
    import models.local as local_module

    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    monkeypatch.setattr(local_module.settings, "local_activation_enabled", False, raising=False)
    outcome = reg.local_activation().run()["qwen3:4b"]
    assert outcome.activation == ACTIVATION_DISABLED
    assert outcome.available is False
    # The registry status is still reported truthfully.
    assert outcome.runtime_status == reg.get("qwen3:4b").status


def test_activation_vocabulary_is_complete():
    assert set(ALL_ACTIVATIONS) == {
        ACTIVATION_ACTIVE,
        ACTIVATION_INSTALLED,
        ACTIVATION_NOT_INSTALLED,
        ACTIVATION_DISABLED,
        "OUT_OF_SCOPE",
    }


def test_summary_shape_is_json_safe_and_secret_free():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    summary = reg.local_activation().summary()
    for key in ("enabled", "scope", "installed", "active", "available", "not_installed", "total", "models", "secrets_exposed"):
        assert key in summary, key
    assert summary["scope"] == "local"
    assert summary["secrets_exposed"] is False
    blob = str(summary)
    for marker in ("sk-", "gsk-", "ghp_", "Bearer ", "api_key", "password"):
        assert marker not in blob, f"leaked {marker}"
    assert isinstance(summary["models"], list) and summary["models"]


def test_probe_all_false_limits_scope_but_keeps_install_view(monkeypatch):
    """The fast path only probes the preferred model, yet still reports installs."""
    import models.local as local_module

    adapter = FakeOllama(["qwen3:4b", "gemma3:4b"])
    reg = make_local_registry(adapter)
    monkeypatch.setattr(local_module.settings, "local_activation_probe_all", False, raising=False)
    monkeypatch.setattr(local_module.settings, "local_activation_preferred_model", "qwen3:4b", raising=False)

    reg.refresh(force=True)
    before = list(adapter.complete_calls)
    outcomes = reg.local_activation().run(force=True)  # force re-probes only the scope
    new_probes = adapter.complete_calls[len(before):]
    assert new_probes == ["qwen3:4b"], new_probes
    # Both installed models are still discovered/reported.
    assert outcomes["qwen3:4b"].installed is True
    assert outcomes["gemma3:4b"].installed is True


def test_is_local_catalog_entry_helper():
    assert is_local_catalog_entry("qwen3:4b") is True
    assert is_local_catalog_entry("gpt-5") is False
    assert is_local_catalog_entry("does-not-exist") is False


# --------------------------------------------------------------------------- #
# 9. API surface — additive, read-only, secret-free
# --------------------------------------------------------------------------- #
def test_local_activation_endpoint_requires_auth():
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as fresh:
        assert fresh.get("/api/models/local/activation").status_code == 401


def test_local_activation_endpoint_shape(auth_client):
    r = auth_client.get("/api/models/local/activation")
    assert r.status_code == 200
    body = r.json()
    assert body["secrets_exposed"] is False
    assert body["scope"] == "local"
    for key in ("enabled", "installed", "active", "available", "not_installed", "total", "models"):
        assert key in body, key
    for model in body["models"]:
        assert model["activation"] in ALL_ACTIVATIONS
        assert "id" in model and "runtime_status" in model


def test_local_activation_endpoint_never_leaks_secrets(auth_client):
    body = auth_client.get("/api/models/local/activation").json()
    blob = str(body)
    for marker in ("sk-", "gsk-", "ghp-", "ghp_", "Bearer ", "api_key", "password", "token="):
        assert marker not in blob, f"leaked {marker}"


def test_local_activation_endpoint_is_backward_compatible(auth_client):
    """Adding the endpoint must not disturb the existing models surface."""
    assert auth_client.get("/api/models").status_code == 200
    assert auth_client.get("/api/models/catalog").status_code == 200
    assert auth_client.get("/api/models/router").status_code == 200
    assert auth_client.get("/api/models/providers").status_code == 200


# --------------------------------------------------------------------------- #
# 10. Configuration surface
# --------------------------------------------------------------------------- #
def test_env_example_documents_local_activation_vars():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "LAIW_LOCAL_ACTIVATION_ENABLED" in text
    assert "LAIW_LOCAL_ACTIVATION_PROBE_ALL" in text
    assert "LAIW_LOCAL_ACTIVATION_PREFERRED_MODEL" in text


def test_settings_expose_local_activation_defaults():
    from configs.settings import settings

    assert settings.local_activation_enabled is True
    assert settings.local_activation_probe_all is True
    assert settings.local_activation_preferred_model == "qwen3:4b"


def test_local_activation_needs_no_api_key_or_cloud_provider():
    """Activation works with only a local adapter registered — no keys anywhere."""
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    summary = reg.local_activation().summary()
    assert summary["available"] == ["qwen3:4b"]
    # Only the local provider exists; no cloud adapter was required.
    assert list(reg.adapters().keys()) == ["ollama"]
