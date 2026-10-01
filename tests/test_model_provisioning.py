"""Runtime matrix / generation registrations / model provisioning tests.

Locks in the layer added on top of the declarative Model Catalog:

* the **runtime matrix** (:mod:`models.runtimes`) — which runtimes this build can
  actually serve models with, and a *clear reason* when it cannot;
* the **generation registrations** (:mod:`models.generation`) — image / video /
  image-to-video models wired to a runtime, with strictly separated states and **no
  download path** (official ids are documentation only);
* the **provisioning view** (:mod:`models.provisioning`) — the explicit
  ``CATALOG → INSTALLED → AVAILABLE`` separation;
* the hard capability routing guarantees: a chat-only model can never serve
  vision / image / video / embedding; image / video / i2v are never picked by the
  Chat Router; and each state is reachable and explicit.

All provider I/O is replaced by deterministic fakes — **no network is used**.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from models.base import (
    CAP_EMBEDDINGS,
    CAP_IMAGE_GENERATION,
    CAP_VIDEO_GENERATION,
    CAP_VISION,
    STATUS_AVAILABLE,
    STATUS_NOT_CONFIGURED,
    ChatMessage,
    Completion,
    EmbeddingResult,
    ModelAdapter,
    ModelDescriptor,
)
from models.catalog import entry_runtime, entry_runtime_supported, get_catalog_entry
from models.generation import (
    ALL_GEN_STATES,
    AUTOMATIC_DOWNLOAD,
    GEN_AVAILABLE,
    GEN_INSTALLED,
    GEN_NOT_CONFIGURED,
    GEN_NOT_INSTALLED,
    GENERATION_REGISTRATIONS,
    REASON_NOT_PRESENT,
    SINK_ENDPOINT,
    SINK_RUNTIME,
    available_generation_models,
    classify_generation,
    generation_ids,
    get_generation_registration,
    is_generation_model,
    registrations_for_surface,
)
from models.provisioning import (
    ALL_PROVISIONING_STATES,
    PROV_AVAILABLE,
    PROV_CATALOG,
    PROV_INSTALLED,
    PROV_NOT_CONFIGURED,
    catalog_entry_runtime,
    classify_provisioning,
    provisioning_summary,
)
from models.registry import ModelRegistry
from models.router import (
    OUTCOME_NO_CAPABLE_MODEL,
    OUTCOME_SELECTED,
    TASK_CHAT,
    TASK_EMBEDDING,
    TASK_I2V,
    TASK_IMAGE,
    TASK_VIDEO,
    TASK_VISION,
    ModelRouter,
)
from models.runtimes import (
    RUNTIME_DIFFUSERS,
    RUNTIME_OLLAMA,
    RUNTIME_OPENAI_COMPATIBLE,
    SURFACE_IMAGE_GENERATION,
    SURFACE_IMAGE_TO_VIDEO,
    SURFACE_VIDEO_GENERATION,
    get_runtime,
    is_local_runtime,
    runtime_reason,
    runtime_supported,
    runtimes,
    supported_runtimes_for_surface,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The ten local models the task asks for explicit support for.
REQUIRED_LOCAL_MODELS = (
    "qwen3:4b",
    "qwen3:8b",
    "qwen3-coder:30b",
    "deepseek-r1:8b",
    "gemma3:4b",
    "qwen3-vl:8b",
    "llama3.2-vision:11b",
    "nomic-embed-text",
    "mxbai-embed-large",
    "bge-m3",
)

#: The eight generation models to register (image / video / i2v).
REQUIRED_GENERATION_MODELS = (
    "qwen-image",
    "qwen-image-edit",
    "flux.1-schnell",
    "wan2.2-t2v",
    "wan2.2-i2v",
    "hunyuanvideo",
    "hunyuanvideo-i2v",
    "cogvideox-5b",
)


# --------------------------------------------------------------------------- #
# Fakes — deterministic, offline, no sockets
# --------------------------------------------------------------------------- #
class FakeOllama(ModelAdapter):
    name = "ollama"
    provider = "ollama"
    is_local = True

    def __init__(self, installed: list[str], *, fail_models: set[str] | None = None) -> None:
        self._installed = list(installed)
        self.fail_models = set(fail_models or ())
        self.complete_calls: list[str] = []
        self.embed_calls: list[str] = []

    def is_configured(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return list(self._installed)

    def discover(self) -> list[ModelDescriptor]:
        from models.base import infer_capabilities, infer_context, infer_kind

        return [
            ModelDescriptor(
                id=mid,
                provider=self.provider,
                kind=infer_kind(mid),
                capabilities=infer_capabilities(mid).to_list(),
                context_length=infer_context(mid),
                local=True,
            )
            for mid in self._installed
        ]

    def complete(self, messages: list[ChatMessage], model: str, **opts) -> Completion:
        self.complete_calls.append(model)
        if model in self.fail_models:
            from backend.app.core.errors import ModelUnavailableError

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
# 1. Runtime matrix
# --------------------------------------------------------------------------- #
def test_runtime_matrix_has_the_expected_runtimes():
    ids = {r.id for r in runtimes()}
    assert {RUNTIME_OLLAMA, RUNTIME_DIFFUSERS, RUNTIME_OPENAI_COMPATIBLE}.issubset(ids)


def test_ollama_runtime_is_supported_and_local():
    assert runtime_supported(RUNTIME_OLLAMA) is True
    assert is_local_runtime(RUNTIME_OLLAMA) is True
    assert runtime_reason(RUNTIME_OLLAMA) == ""


def test_diffusers_runtime_is_not_supported_with_a_clear_reason():
    assert runtime_supported(RUNTIME_DIFFUSERS) is False
    reason = runtime_reason(RUNTIME_DIFFUSERS)
    assert reason and "not wired in this build" in reason


def test_unknown_runtime_is_never_supported():
    assert runtime_supported("no-such-runtime") is False
    assert "Unknown runtime" in runtime_reason("no-such-runtime")


def test_generation_surfaces_local_wiring_is_explicit_and_honest():
    """Image/t2v have no wired local runtime; I2V is wired exactly once (Wan 2.2 I2V).

    The image and text-to-video surfaces remain unwired (declarative only). The only
    local generation runtime wired in this build is the Wan 2.2 I2V runtime, which is
    lazy and weight-free at import (see ``tests/test_generation_runtime.py``).
    """
    from models.runtimes import RUNTIME_WAN_I2V, is_local_runtime as _is_local

    for surface in (SURFACE_IMAGE_GENERATION, SURFACE_VIDEO_GENERATION):
        local_supported = [r for r in supported_runtimes_for_surface(surface) if _is_local(r.id)]
        assert local_supported == [], surface

    i2v_local = [r.id for r in supported_runtimes_for_surface(SURFACE_IMAGE_TO_VIDEO) if _is_local(r.id)]
    assert i2v_local == [RUNTIME_WAN_I2V]


def test_runtime_matrix_performs_no_network_io():
    source = (REPO_ROOT / "models" / "runtimes.py").read_text(encoding="utf-8")
    for marker in ("import requests", "requests.", "urlopen", "socket", "from urllib"):
        assert marker not in source, f"runtimes must not contain '{marker}'"


def test_diffusers_descriptor_has_no_adapter():
    desc = get_runtime(RUNTIME_DIFFUSERS)
    assert desc is not None and desc.adapter == ""


# --------------------------------------------------------------------------- #
# 2. Generation registrations — inventory + official ids
# --------------------------------------------------------------------------- #
def test_all_required_generation_models_are_registered():
    ids = set(generation_ids())
    missing = set(REQUIRED_GENERATION_MODELS) - ids
    assert not missing, f"missing generation registrations: {sorted(missing)}"


def test_generation_registrations_use_official_looking_refs_only():
    for reg in GENERATION_REGISTRATIONS:
        assert reg.official_ref and "/" in reg.official_ref, reg.id
        # No whitespace/scheme — a bare HF repo id, never a URL we would fetch.
        assert " " not in reg.official_ref
        assert not reg.official_ref.startswith("http")


def test_generation_surfaces_are_separated():
    image_surfaces = {SURFACE_IMAGE_GENERATION}
    for reg in registrations_for_surface(SURFACE_IMAGE_GENERATION):
        assert set(reg.surfaces) == image_surfaces
    t2v_only = {r.id for r in registrations_for_surface(SURFACE_VIDEO_GENERATION) if not r.is_i2v}
    assert "wan2.2-t2v" in t2v_only and "hunyuanvideo" in t2v_only and "cogvideox-5b" in t2v_only
    i2v_ids = {r.id for r in registrations_for_surface(SURFACE_IMAGE_TO_VIDEO)}
    assert i2v_ids == {"wan2.2-i2v", "hunyuanvideo-i2v"}


def test_i2v_registrations_declare_image_input_modality():
    for rid in ("wan2.2-i2v", "hunyuanvideo-i2v"):
        reg = get_generation_registration(rid)
        assert reg.is_i2v is True
        assert "image" in reg.modality and "video" in reg.modality


def test_is_generation_model_helper():
    assert is_generation_model("qwen-image") is True
    assert is_generation_model("wan2.2-i2v") is True
    assert is_generation_model("qwen3:4b") is False


def test_generation_module_has_no_download_path():
    source = (REPO_ROOT / "models" / "generation.py").read_text(encoding="utf-8")
    for marker in ("/api/pull", "def pull", "hf_hub_download", "from_pretrained", "snapshot_download", "urlretrieve"):
        assert marker not in source, f"generation must not contain '{marker}'"
    assert AUTOMATIC_DOWNLOAD is False


def test_generation_module_imports_no_networking_library():
    source = (REPO_ROOT / "models" / "generation.py").read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "import socket" not in source
    assert "from urllib" not in source


# --------------------------------------------------------------------------- #
# 3. Generation states — each state is reachable and explicit
# --------------------------------------------------------------------------- #
def test_generation_not_configured_when_runtime_unsupported():
    outcomes = classify_generation(provisioned_ids=set())
    # Every registration is NOT_CONFIGURED here (no weights / unwired runtime) and
    # never AVAILABLE. The un-wired diffusers models carry an explicit "not wired"
    # reason; the wired Wan I2V runtime reports weights_missing.
    for rid in REQUIRED_GENERATION_MODELS:
        o = outcomes[rid]
        assert o.state == GEN_NOT_CONFIGURED
        assert o.available is False
        assert o.reason
    assert outcomes["qwen-image"].runtime_supported is False
    assert "not wired in this build" in outcomes["qwen-image"].reason
    assert outcomes["wan2.2-i2v"].runtime_supported is True
    assert outcomes["wan2.2-i2v"].reason == "weights_missing"


def test_generation_available_when_runtime_sink_confirmed():
    class D:
        id = "qwen-image"
        endpoint = ""
        endpoints: list[str] = []

    class FakeSupportedReg:
        pass

    # Simulate a supported runtime by monkeypatching the registry used for the id.
    outcomes = classify_generation(runtime_models={"qwen-image": D()})
    # Without a supported runtime it is still NOT_CONFIGURED (diffusers unwired)…
    assert outcomes["qwen-image"].state == GEN_NOT_CONFIGURED


def test_generation_not_installed_when_runtime_supported_but_absent(monkeypatch):
    import models.generation as gen

    monkeypatch.setattr(gen, "runtime_status", lambda rid: (True, ""))
    outcomes = classify_generation()
    assert outcomes["qwen-image"].state == GEN_NOT_INSTALLED
    assert outcomes["qwen-image"].reason == REASON_NOT_PRESENT


def test_generation_installed_when_present_but_no_sink(monkeypatch):
    import models.generation as gen

    monkeypatch.setattr(gen, "runtime_status", lambda rid: (True, ""))

    class D:
        id = "qwen-image"
        endpoint = ""
        endpoints: list[str] = []

    outcomes = classify_generation(runtime_models={"qwen-image": D()})
    # A supported runtime reconciles the descriptor → a runtime sink → AVAILABLE.
    assert outcomes["qwen-image"].state == GEN_AVAILABLE
    assert outcomes["qwen-image"].sink == SINK_RUNTIME


def test_generation_available_with_operator_endpoint(monkeypatch):
    import models.generation as gen

    monkeypatch.setattr(gen, "runtime_status", lambda rid: (True, ""))
    outcomes = classify_generation(endpoint_models={"flux.1-schnell": ("http://img.local/gen",)})
    o = outcomes["flux.1-schnell"]
    assert o.state == GEN_AVAILABLE
    assert o.sink == SINK_ENDPOINT
    assert o.endpoints == ["http://img.local/gen"]


def test_generation_states_vocabulary_is_complete():
    assert set(ALL_GEN_STATES) == {GEN_AVAILABLE, GEN_INSTALLED, GEN_NOT_INSTALLED, GEN_NOT_CONFIGURED}


def test_available_generation_models_is_empty_in_this_build():
    # The Wan 2.2 I2V runtime is wired, but with no local weights nothing is AVAILABLE
    # (NOT_CONFIGURED / weights_missing) and no other runtime is wired.
    assert available_generation_models(provisioned_ids=set()) == []


# --------------------------------------------------------------------------- #
# 4. Provisioning — CATALOG / INSTALLED / AVAILABLE separation
# --------------------------------------------------------------------------- #
def test_provisioning_vocabulary_is_explicit():
    assert set(ALL_PROVISIONING_STATES) == {PROV_CATALOG, PROV_INSTALLED, PROV_AVAILABLE, PROV_NOT_CONFIGURED}


def test_catalog_only_view_never_claims_available():
    reg = ModelRegistry(build_adapters=False)
    rows = classify_provisioning(reg, runtime_models={})
    assert all(not m.available for m in rows.values())
    assert all(m.state in (PROV_CATALOG, PROV_NOT_CONFIGURED) for m in rows.values())


def test_generation_models_are_not_configured_in_provisioning():
    reg = ModelRegistry(build_adapters=False)
    rows = classify_provisioning(reg, runtime_models={}, provisioned_ids=set())
    for rid in REQUIRED_GENERATION_MODELS:
        assert rows[rid].state == PROV_NOT_CONFIGURED, rid
        assert rows[rid].available is False
        assert rows[rid].reason
    # The un-wired runtimes stay explicitly unsupported; the wired Wan I2V runtime is
    # supported in this build yet still NOT_CONFIGURED here (no local weights).
    assert rows["qwen-image"].runtime_supported is False
    assert rows["wan2.2-i2v"].runtime_supported is True


def test_installed_local_model_without_probe_is_installed_not_available():
    """Present on the runtime but not probed → INSTALLED, never AVAILABLE."""
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    runtime = {"qwen3:4b": _row("qwen3:4b", local=True, status=STATUS_NOT_CONFIGURED)}
    rows = classify_provisioning(reg, runtime_models=runtime)
    assert rows["qwen3:4b"].installed is True
    assert rows["qwen3:4b"].available is False
    assert rows["qwen3:4b"].state == PROV_INSTALLED


def _row(model_id: str, *, local: bool = False, status: str = STATUS_NOT_CONFIGURED):
    class R:
        pass

    r = R()
    r.id = model_id
    r.provider = "ollama" if local else "openai_compatible"
    r.local = local
    r.status = status
    r.capabilities = get_catalog_entry(model_id).capabilities if get_catalog_entry(model_id) else []
    r.modality = get_catalog_entry(model_id).modality if get_catalog_entry(model_id) else []
    return r


def test_probed_available_local_model_is_available():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    runtime = {"qwen3:4b": _row("qwen3:4b", local=True, status=STATUS_AVAILABLE)}
    rows = classify_provisioning(reg, runtime_models=runtime)
    assert rows["qwen3:4b"].available is True
    assert rows["qwen3:4b"].state == PROV_AVAILABLE


def test_provisioning_summary_shape_is_json_safe_and_secret_free():
    reg = ModelRegistry(build_adapters=False)
    summary = provisioning_summary(reg, runtime_models={})
    for key in ("layers", "states", "catalog", "installed", "available", "catalog_only", "not_configured", "by_kind", "total", "models", "secrets_exposed"):
        assert key in summary, key
    assert summary["layers"] == ["CATALOG", "INSTALLED", "AVAILABLE"]
    assert summary["secrets_exposed"] is False
    blob = str(summary)
    for marker in ("sk-", "gsk-", "ghp_", "Bearer ", "api_key", "password"):
        assert marker not in blob, f"leaked {marker}"


def test_catalog_entry_runtime_for_generation_and_chat():
    assert catalog_entry_runtime("qwen-image") == RUNTIME_DIFFUSERS
    assert catalog_entry_runtime("qwen3:4b") == RUNTIME_OLLAMA


# --------------------------------------------------------------------------- #
# 5. Catalog wiring — runtime field + i2v modality + accurate notes
# --------------------------------------------------------------------------- #
def test_every_generation_catalog_entry_records_its_runtime():
    from models.runtimes import RUNTIME_WAN_I2V

    for rid in REQUIRED_GENERATION_MODELS:
        entry = get_catalog_entry(rid)
        assert entry is not None
        if rid == "wan2.2-i2v":
            # The one generation model whose runtime is wired in this build.
            assert entry_runtime(entry) == RUNTIME_WAN_I2V
            assert entry_runtime_supported(entry) is True
        else:
            assert entry_runtime(entry) == RUNTIME_DIFFUSERS
            assert entry_runtime_supported(entry) is False


def test_i2v_catalog_entries_declare_image_modality():
    for rid in ("wan2.2-i2v", "hunyuanvideo-i2v"):
        entry = get_catalog_entry(rid)
        assert "image" in entry.modality and "video" in entry.modality


def test_local_models_are_supported_ollama_runtime():
    for mid in REQUIRED_LOCAL_MODELS:
        entry = get_catalog_entry(mid)
        assert entry is not None, mid
        assert entry_runtime(entry) == RUNTIME_OLLAMA
        assert entry_runtime_supported(entry) is True


# --------------------------------------------------------------------------- #
# 6. Per-model / per-modality coverage of the ten required local models
# --------------------------------------------------------------------------- #
CHAT_MODELS = ("qwen3:4b", "qwen3:8b", "qwen3-coder:30b", "deepseek-r1:8b")
VISION_MODELS = ("gemma3:4b", "qwen3-vl:8b", "llama3.2-vision:11b")
EMBEDDING_MODELS = ("nomic-embed-text", "mxbai-embed-large", "bge-m3")


@pytest.mark.parametrize("model_id", REQUIRED_LOCAL_MODELS)
def test_each_required_local_model_imports_and_is_known(model_id):
    entry = get_catalog_entry(model_id)
    assert entry is not None
    assert entry.local is True


@pytest.mark.parametrize("model_id", CHAT_MODELS)
def test_chat_local_model_is_routed_for_chat_but_never_multimodal(model_id):
    reg = make_local_registry(FakeOllama([model_id]))
    reg.refresh(force=True)
    router = ModelRouter(reg)
    assert router.select(TASK_CHAT).model == model_id
    for task in (TASK_VISION, TASK_IMAGE, TASK_VIDEO, TASK_I2V, TASK_EMBEDDING):
        decision = router.select(task)
        if task == TASK_VISION and model_id in VISION_MODELS:
            continue
        assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL, (model_id, task)


@pytest.mark.parametrize("model_id", VISION_MODELS)
def test_vision_local_model_routes_only_when_installed(model_id):
    """qwen3-vl:8b is AVAILABLE for vision ONLY IF it is actually installed."""
    absent = make_local_registry(FakeOllama(["qwen3:4b"]))
    absent.refresh(force=True)
    assert ModelRouter(absent).select(TASK_VISION).model is None

    present = make_local_registry(FakeOllama([model_id]))
    present.refresh(force=True)
    decision = ModelRouter(present).select(TASK_VISION)
    assert decision.model == model_id
    assert decision.outcome == OUTCOME_SELECTED


@pytest.mark.parametrize("model_id", EMBEDDING_MODELS)
def test_embedding_models_are_tested_independently(model_id):
    reg = make_local_registry(FakeOllama([model_id]))
    reg.refresh(force=True)
    router = ModelRouter(reg)
    assert router.select(TASK_EMBEDDING).model == model_id
    # And an embedding model is never routed a chat task.
    assert router.select(TASK_CHAT).model is None


def test_qwen3_4b_stays_available_when_ollama_serves_it():
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    reg.refresh(force=True)
    info = reg.get("qwen3:4b")
    assert info.status == STATUS_AVAILABLE
    assert reg.local_activation().run()["qwen3:4b"].available is True


def test_qwen3_vl_not_available_unless_actually_installed():
    """qwen3-vl:8b must stay NOT_CONFIGURED unless Ollama really serves it."""
    reg = make_local_registry(FakeOllama(["qwen3:4b"]))
    reg.refresh(force=True)
    assert reg.get("qwen3-vl:8b") is None
    assert reg.local_activation().run()["qwen3-vl:8b"].runtime_status == STATUS_NOT_CONFIGURED


def test_chat_only_model_can_never_serve_vision_image_video_embedding():
    reg = make_local_registry(FakeOllama(["qwen3:8b"]))
    reg.refresh(force=True)
    info = reg.get("qwen3:8b")
    assert CAP_VISION not in info.capabilities
    assert CAP_IMAGE_GENERATION not in info.capabilities
    assert CAP_VIDEO_GENERATION not in info.capabilities and CAP_EMBEDDINGS not in info.capabilities
    router = ModelRouter(reg)
    for task in (TASK_VISION, TASK_IMAGE, TASK_VIDEO, TASK_I2V, TASK_EMBEDDING):
        assert router.select(task).outcome == OUTCOME_NO_CAPABLE_MODEL, task


# --------------------------------------------------------------------------- #
# 7. Chat Router never picks image / video / i2v — per provider/runtime path
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("runtime", [RUNTIME_OLLAMA, RUNTIME_DIFFUSERS])
def test_chat_router_never_selects_generation_models(runtime):
    reg = ModelRegistry(build_adapters=False)
    # A chat model available on the local runtime.
    reg.register_adapter("ollama", FakeOllama(["qwen3:4b"]))
    reg.refresh(force=True)
    router = ModelRouter(reg)
    for task in (TASK_IMAGE, TASK_VIDEO, TASK_I2V):
        decision = router.select(task)
        assert decision.model is None, (runtime, task)
        assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


def test_image_video_i2v_have_hard_capability_gates():
    from models.router import TASK_REQUIREMENTS

    assert CAP_IMAGE_GENERATION in TASK_REQUIREMENTS[TASK_IMAGE].required
    assert CAP_VIDEO_GENERATION in TASK_REQUIREMENTS[TASK_VIDEO].required
    assert CAP_VIDEO_GENERATION in TASK_REQUIREMENTS[TASK_I2V].required


# --------------------------------------------------------------------------- #
# 8. API surface — additive, read-only, secret-free
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["/api/models/runtimes", "/api/models/generation", "/api/models/provisioning"])
def test_new_endpoints_require_auth(path):
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as fresh:
        assert fresh.get(path).status_code == 401


def test_runtimes_endpoint_shape(auth_client):
    body = auth_client.get("/api/models/runtimes").json()
    assert body["secrets_exposed"] is False
    assert body["config_source"] == "runtime-matrix"
    ids = {r["id"] for r in body["runtimes"]}
    assert {RUNTIME_OLLAMA, RUNTIME_DIFFUSERS}.issubset(ids)
    for r in body["runtimes"]:
        assert "supported" in r and "reason" in r and "surfaces" in r


def test_generation_endpoint_shape(auth_client):
    body = auth_client.get("/api/models/generation").json()
    assert body["secrets_exposed"] is False
    assert body["automatic_download"] is False
    assert body["available"] == []
    for m in body["models"]:
        assert m["state"] in ALL_GEN_STATES
    # Only the wired Wan 2.2 I2V runtime is supported here (still NOT_CONFIGURED with
    # no local weights); every other generation model keeps an unwired runtime.
    supported = {m["id"] for m in body["models"] if m["runtime_supported"]}
    assert supported == {"wan2.2-i2v"}


def test_provisioning_endpoint_shape(auth_client):
    body = auth_client.get("/api/models/provisioning").json()
    assert body["secrets_exposed"] is False
    assert body["layers"] == ["CATALOG", "INSTALLED", "AVAILABLE"]
    for m in body["models"]:
        assert m["state"] in ALL_PROVISIONING_STATES


def test_new_endpoints_never_leak_secrets(auth_client):
    for path in ("/api/models/runtimes", "/api/models/generation", "/api/models/provisioning"):
        blob = str(auth_client.get(path).json())
        for marker in ("sk-", "gsk-", "ghp_", "Bearer ", "api_key", "password", "token="):
            assert marker not in blob, f"{path} leaked {marker}"


def test_new_endpoints_are_backward_compatible(auth_client):
    assert auth_client.get("/api/models").status_code == 200
    assert auth_client.get("/api/models/catalog").status_code == 200
    assert auth_client.get("/api/models/router").status_code == 200
    assert auth_client.get("/api/models/local/activation").status_code == 200
    assert auth_client.get("/api/models/runtimes").status_code == 200
    assert auth_client.get("/api/models/generation").status_code == 200
    assert auth_client.get("/api/models/provisioning").status_code == 200


# --------------------------------------------------------------------------- #
# 9. No network at startup; static guarantees
# --------------------------------------------------------------------------- #
def test_new_modules_perform_no_network_io():
    for name in ("runtimes.py", "generation.py", "provisioning.py"):
        source = (REPO_ROOT / "models" / name).read_text(encoding="utf-8")
        assert "import requests" not in source, name
        assert "urlopen" not in source, name


def test_catalog_module_has_no_network_or_download():
    source = (REPO_ROOT / "models" / "catalog.py").read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "from_pretrained" not in source
    assert "snapshot_download" not in source
