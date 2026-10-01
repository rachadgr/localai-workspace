"""Wan 2.2 I2V generation runtime tests.

Locks in the first *actual* generation runtime wired into the workspace:

* **discovery** — a locally-provisioned checkpoint is found; its absence is the
  honest ``NOT_CONFIGURED`` / ``weights_missing`` (nothing is downloaded);
* **lazy loading** — importing/starting the app loads **no** weights, and a load is
  only ever triggered when a generation is explicitly requested;
* **real probe** — ``AVAILABLE`` is only reached after a genuine pipeline build +
  probe; a missing heavy dependency surfaces as a typed ``UNAVAILABLE``/``ERROR``;
* **capability routing** — a chat / vision / image model can never run I2V: the hard
  ``video_generation`` + ``image``/``video`` gate rejects it;
* **invalid input / artifact result / failure handling** — validated, honest results;
* **no startup weight load** — a static guarantee that the module never imports torch
  or diffusers at module scope.

All tests are deterministic and offline: heavy runtimes are faked monkeypatch-style.
No network is used and no weights are downloaded.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from models.base import (
    CAP_IMAGE_GENERATION,
    CAP_VIDEO_GENERATION,
    MODALITY_IMAGE,
    MODALITY_VIDEO,
    STATUS_AVAILABLE,
    STATUS_ERROR,
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
)
from models.generation import (
    GEN_AVAILABLE,
    GEN_INSTALLED,
    GEN_NOT_CONFIGURED,
    classify_generation,
    get_generation_registration,
)
from models.generation_router import (
    GENERATION_REQUIREMENTS,
    OUTCOME_INVALID_REQUEST,
    OUTCOME_NO_CAPABLE_RUNTIME,
    OUTCOME_SELECTED,
    TASK_IMAGE,
    TASK_I2V,
    TASK_T2V,
    GenerationRouter,
)
from models.generation_runtime import (
    AUTOMATIC_DOWNLOAD,
    LIFECYCLE_AVAILABLE,
    LIFECYCLE_ERROR,
    LIFECYCLE_NOT_CONFIGURED,
    LIFECYCLE_UNAVAILABLE,
    REASON_INVALID_INPUT,
    REASON_LOAD_FAILED,
    REASON_RUNTIME_DEPS_MISSING,
    REASON_WEIGHTS_MISSING,
    WAN_I2V_MODEL_ID,
    GenerationRequest,
    GenerationResult,
    LocalGenerationManager,
    RuntimeUnavailableError,
    WanI2VAdapter,
    WeightsMissingError,
    checkpoint_present,
    detect_wan_i2v_checkpoint,
    get_local_generation_manager,
)
from models.runtimes import (
    RUNTIME_DIFFUSERS,
    RUNTIME_WAN_I2V,
    SURFACE_IMAGE_TO_VIDEO,
    get_runtime,
    runtime_status,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Helpers — real on-disk checkpoints, deterministic fake pipelines
# --------------------------------------------------------------------------- #
def _make_checkpoint(root: Path, name: str = "Wan2.2-I2V-A14B") -> Path:
    """Create a *loadable-looking* diffusers checkpoint dir (model_index.json)."""
    ckpt = root / name
    ckpt.mkdir(parents=True, exist_ok=True)
    (ckpt / "model_index.json").write_text("{}", encoding="utf-8")
    return ckpt


class _FakePipeline:
    """A genuine stand-in for the official Wan pipeline (returns real frames)."""

    def __init__(self, *, empty: bool = False, fail: Exception | None = None) -> None:
        self.components = {} if empty else {"vae": object(), "transformer": object(), "text_encoder": object()}
        self.fail = fail
        self.calls: list[dict] = []
        self.offload_enabled = False

    def enable_model_cpu_offload(self) -> None:
        self.offload_enabled = True

    def to(self, device):  # noqa: ANN001, ANN201
        return self

    def __call__(self, *, image=None, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls.append({"image": image, **kwargs})
        if self.fail is not None:
            raise self.fail

        class _Out:
            frames = [[_FakeFrame()] for _ in range(1)]

        return _Out()


class _FakeFrame:
    def save(self, path):  # noqa: ANN001, ANN201
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nFAKEFRAME")


class _FakePipeClass:
    """Stand-in for ``diffusers.WanImageToVideoPipeline``."""

    built: list[tuple] = []
    pipeline: _FakePipeline | None = None

    @classmethod
    def from_pretrained(cls, path, **kwargs):  # noqa: ANN001, ANN003, ANN201
        cls.built.append((path, kwargs))
        return cls.pipeline if cls.pipeline is not None else _FakePipeline()


def _install_fake_modules(monkeypatch, *, empty_pipe: bool = False, fail: Exception | None = None) -> None:
    """Inject fake ``torch`` + ``diffusers`` so a load can run offline."""
    import types

    # Always install a *fresh* pipeline + reset the build log so tests are isolated.
    _FakePipeClass.built = []
    _FakePipeClass.pipeline = _FakePipeline(empty=empty_pipe, fail=fail)

    fake_diffusers = types.ModuleType("diffusers")
    fake_diffusers.WanImageToVideoPipeline = _FakePipeClass
    utils = types.ModuleType("diffusers.utils")

    def _export_to_video(frames, path, fps):  # noqa: ANN001, ANN201
        Path(path).write_bytes(b"FAKEMP4")

    utils.export_to_video = _export_to_video
    fake_diffusers.utils = utils

    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.float16 = "float16"
    fake_torch.float32 = "float32"

    class _Gen:
        def __init__(self, *a, **k):  # noqa: ANN002, ANN003
            pass

        def manual_seed(self, seed):  # noqa: ANN001, ANN201
            return self

    fake_torch.Generator = _Gen

    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    monkeypatch.setitem(sys.modules, "diffusers.utils", utils)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)


@pytest.fixture()
def checkpoint_dir(tmp_path, monkeypatch):
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setenv("LAIW_GENERATION_CHECKPOINTS_DIR", str(root))

    from configs.settings import settings

    monkeypatch.setattr(settings, "generation_checkpoints_dir", str(root), raising=False)
    monkeypatch.setattr(settings, "generation_wan_i2v_checkpoint", "", raising=False)
    return root


@pytest.fixture(autouse=True)
def _reset_manager():
    """Each test gets a fresh manager (no cross-test weight/lifecycle leakage)."""
    import models.generation_runtime as gr

    original = gr._MANAGER
    gr._MANAGER = None
    yield
    gr._MANAGER = original


def _image(tmp_path: Path) -> str:
    path = tmp_path / "src.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nREALIMAGE")
    return str(path)


# --------------------------------------------------------------------------- #
# 1. Runtime matrix wiring
# --------------------------------------------------------------------------- #
def test_wan_i2v_runtime_is_wired_and_supported():
    assert runtime_status(RUNTIME_WAN_I2V) == (True, "")
    desc = get_runtime(RUNTIME_WAN_I2V)
    assert desc is not None
    assert desc.adapter == "WanI2VAdapter"
    assert SURFACE_IMAGE_TO_VIDEO in desc.surfaces
    assert desc.local is True


def test_diffusers_runtime_is_still_unwired():
    supported, reason = runtime_status(RUNTIME_DIFFUSERS)
    assert supported is False and "not wired in this build" in reason


def test_wan_i2v_registration_targets_the_wired_runtime():
    reg = get_generation_registration(WAN_I2V_MODEL_ID)
    assert reg is not None and reg.runtime == RUNTIME_WAN_I2V and reg.is_i2v


def test_generation_module_has_no_download_path_still():
    assert AUTOMATIC_DOWNLOAD is False
    source = (REPO_ROOT / "models" / "generation_runtime.py").read_text(encoding="utf-8")
    # No remote fetch/download API anywhere.
    for marker in (
        "hf_hub_download",
        "snapshot_download",
        "urlretrieve",
        "requests.get",
        "requests.post",
        "huggingface_hub",
        "from_pretrained(\"",
        "from_pretrained('",
    ):
        assert marker not in source, f"generation_runtime must not contain a download call '{marker}'"
    # The only ``from_pretrained`` reads the *local* checkpoint path we discovered.
    assert "from_pretrained(str(checkpoint)" in source
    # And discovery is a pure filesystem scan (importlib only; no networking module).
    assert "urllib.request" not in source


# --------------------------------------------------------------------------- #
# 2. Discovery — local checkpoint only (no download)
# --------------------------------------------------------------------------- #
def test_detect_returns_none_when_no_checkpoint(checkpoint_dir):
    assert detect_wan_i2v_checkpoint() is None
    assert checkpoint_present() is False


def test_detect_finds_local_checkpoint(checkpoint_dir):
    ckpt = _make_checkpoint(checkpoint_dir)
    assert detect_wan_i2v_checkpoint() == ckpt
    assert checkpoint_present() is True


def test_detect_ignores_non_wan_dirs(checkpoint_dir):
    (checkpoint_dir / "not-a-model").mkdir()
    (checkpoint_dir / "not-a-model" / "model_index.json").write_text("{}")
    assert detect_wan_i2v_checkpoint() is None


def test_detect_ignores_dirs_without_model_index(checkpoint_dir):
    (checkpoint_dir / "Wan2.2-I2V-A14B").mkdir()
    assert detect_wan_i2v_checkpoint() is None


def test_adapter_provisioned_ids_reflects_discovery(checkpoint_dir):
    adapter = WanI2VAdapter()
    assert adapter.provisioned_ids() == set()
    _make_checkpoint(checkpoint_dir)
    fresh = WanI2VAdapter()
    assert fresh.provisioned_ids() == {WAN_I2V_MODEL_ID}


# --------------------------------------------------------------------------- #
# 3. Lazy loading — nothing heavy at import/construct
# --------------------------------------------------------------------------- #
def test_adapter_constructs_lazily(checkpoint_dir):
    adapter = WanI2VAdapter()
    # No weights, no torch/diffusers import, lifecycle is the honest default.
    assert adapter.loaded is False
    assert adapter.lifecycle == LIFECYCLE_NOT_CONFIGURED
    assert adapter.status() == STATUS_NOT_CONFIGURED


def test_generation_runtime_module_imports_no_heavy_runtime():
    source = (REPO_ROOT / "models" / "generation_runtime.py").read_text(encoding="utf-8")
    # No module-scope heavy imports: torch/diffusers are only imported lazily inside
    # functions (via importlib / local imports), never at the top of the file.
    for marker in ("\nimport torch", "\nimport diffusers", "\nfrom diffusers", "\nfrom torch"):
        assert marker not in source, f"module-scope heavy import found: {marker!r}"


def test_manager_constructs_weight_free(checkpoint_dir):
    manager = LocalGenerationManager()
    assert set(manager.adapters) == {RUNTIME_WAN_I2V}
    assert manager.provisioned_ids() == set()
    status = manager.status()
    assert status["models"][0]["loaded"] is False
    assert status["available"] == []


# --------------------------------------------------------------------------- #
# 4. Missing weights — NOT_CONFIGURED / weights_missing (never a failure)
# --------------------------------------------------------------------------- #
def test_missing_weights_not_configured(checkpoint_dir):
    adapter = WanI2VAdapter()
    assert adapter.is_configured() is False
    with pytest.raises(WeightsMissingError) as info:
        adapter.load()
    assert info.value.reason == REASON_WEIGHTS_MISSING
    assert adapter.lifecycle == LIFECYCLE_NOT_CONFIGURED


def test_generate_with_missing_weights_returns_not_configured(checkpoint_dir, tmp_path):
    adapter = WanI2VAdapter()
    result = adapter.generate(GenerationRequest(image=_image(tmp_path), prompt="a fox runs"))
    assert isinstance(result, GenerationResult)
    assert result.status == STATUS_NOT_CONFIGURED
    assert result.reason == REASON_WEIGHTS_MISSING
    assert result.artifact_path == ""
    assert result.available is False and result.ok is False


def test_classify_generation_reports_weights_missing_here():
    outcomes = classify_generation()
    o = outcomes[WAN_I2V_MODEL_ID]
    assert o.state == GEN_NOT_CONFIGURED
    assert o.reason == REASON_WEIGHTS_MISSING
    assert o.runtime_supported is True
    assert o.available is False


def test_classify_generation_installed_when_weights_provisioned():
    outcomes = classify_generation(provisioned_ids={WAN_I2V_MODEL_ID})
    o = outcomes[WAN_I2V_MODEL_ID]
    assert o.state == GEN_INSTALLED
    assert o.installed is True and o.available is False


# --------------------------------------------------------------------------- #
# 5. Real probe → AVAILABLE only after a genuine load
# --------------------------------------------------------------------------- #
def test_load_reaches_available_with_a_real_probe(checkpoint_dir, monkeypatch):
    _make_checkpoint(checkpoint_dir)
    _install_fake_modules(monkeypatch)
    adapter = WanI2VAdapter()
    adapter.ensure_available()
    assert adapter.lifecycle == LIFECYCLE_AVAILABLE
    assert adapter.loaded is True
    assert adapter.describe()["probe"]["ok"] is True
    assert adapter.describe()["probe"]["components"]


def test_probe_failure_is_unavailable_not_available(checkpoint_dir, monkeypatch):
    _make_checkpoint(checkpoint_dir)
    _install_fake_modules(monkeypatch, empty_pipe=True)  # components missing → probe fails
    adapter = WanI2VAdapter()
    with pytest.raises(RuntimeUnavailableError):
        adapter.load()
    assert adapter.lifecycle == LIFECYCLE_UNAVAILABLE
    assert adapter.loaded is False


def test_missing_heavy_dependency_is_unavailable(checkpoint_dir):
    """No fake torch/diffusers installed → typed UNAVAILABLE, never fabricated."""
    _make_checkpoint(checkpoint_dir)
    adapter = WanI2VAdapter()
    with pytest.raises(RuntimeUnavailableError) as info:
        adapter.load()
    assert info.value.reason in (REASON_RUNTIME_DEPS_MISSING, "load_failed")
    assert adapter.lifecycle in (LIFECYCLE_UNAVAILABLE, LIFECYCLE_ERROR)


def test_build_failure_is_classified_error(checkpoint_dir, monkeypatch):
    _make_checkpoint(checkpoint_dir)
    _install_fake_modules(monkeypatch)

    def _boom(*a, **k):  # noqa: ANN002, ANN003
        raise ValueError("corrupt checkpoint")

    monkeypatch.setattr(_FakePipeClass, "from_pretrained", classmethod(lambda cls, path, **kw: _boom()))
    adapter = WanI2VAdapter()
    with pytest.raises(Exception) as info:
        adapter.load()
    assert getattr(info.value, "reason", "") in (REASON_LOAD_FAILED, REASON_RUNTIME_DEPS_MISSING)
    assert adapter.lifecycle in (LIFECYCLE_ERROR, LIFECYCLE_UNAVAILABLE)


# --------------------------------------------------------------------------- #
# 6. Invalid input
# --------------------------------------------------------------------------- #
def test_validate_rejects_remote_url():
    problems = GenerationRequest(image="https://example.com/a.png").validate()
    assert any("remote URLs" in p for p in problems)


def test_validate_rejects_missing_image(tmp_path):
    problems = GenerationRequest(image=str(tmp_path / "nope.png")).validate()
    assert any("not found on disk" in p for p in problems)


def test_validate_rejects_non_multiple_of_16(tmp_path):
    problems = GenerationRequest(image=_image(tmp_path), width=833).validate()
    assert any("multiples of 16" in p for p in problems)


def test_validate_rejects_bad_fps_and_duration(tmp_path):
    img = _image(tmp_path)
    assert any("fps" in p for p in GenerationRequest(image=img, fps=0).validate())
    assert any("duration" in p for p in GenerationRequest(image=img, duration=999).validate())


def test_generate_invalid_input_returns_error_result(checkpoint_dir, tmp_path):
    adapter = WanI2VAdapter()
    result = adapter.generate(GenerationRequest(image=str(tmp_path / "missing.png")))
    assert result.status == STATUS_ERROR
    assert result.reason == REASON_INVALID_INPUT
    assert result.artifact_path == ""


def test_num_frames_follows_wan_4k_plus_1(tmp_path):
    req = GenerationRequest(image=_image(tmp_path), duration=2, fps=16)
    assert req.num_frames == 33  # 2 * 16 + 1


# --------------------------------------------------------------------------- #
# 7. Artifact result (real run, faked pipeline)
# --------------------------------------------------------------------------- #
def test_real_run_produces_artifact(checkpoint_dir, tmp_path, monkeypatch):
    _make_checkpoint(checkpoint_dir)
    _install_fake_modules(monkeypatch)
    adapter = WanI2VAdapter()
    result = adapter.generate(
        GenerationRequest(image=_image(tmp_path), prompt="waves", duration=1, fps=8, name="clip")
    )
    assert result.status == STATUS_AVAILABLE
    assert result.available is True and result.ok is True
    assert result.artifact_path
    assert Path(result.artifact_path).is_file()
    assert result.metadata["kind"] in ("video", "frames")
    assert result.metadata["fps"] == 8
    assert result.to_dict()["secrets_exposed"] is False


def test_result_dict_is_secret_free(checkpoint_dir, tmp_path, monkeypatch):
    _make_checkpoint(checkpoint_dir)
    _install_fake_modules(monkeypatch)
    adapter = WanI2VAdapter()
    result = adapter.generate(GenerationRequest(image=_image(tmp_path), prompt="x"))
    blob = str(result.to_dict())
    for marker in ("sk-", "gsk-", "ghp_", "Bearer ", "api_key", "password"):
        assert marker not in blob, f"leaked {marker}"


# --------------------------------------------------------------------------- #
# 8. Failure handling during a real run
# --------------------------------------------------------------------------- #
def test_run_failure_reports_error_not_fake_artifact(checkpoint_dir, tmp_path, monkeypatch):
    _make_checkpoint(checkpoint_dir)
    _install_fake_modules(monkeypatch, fail=RuntimeError("cuda OOM"))
    adapter = WanI2VAdapter()
    result = adapter.generate(GenerationRequest(image=_image(tmp_path), prompt="x", duration=1, fps=8))
    assert result.status == STATUS_ERROR
    assert result.artifact_path == ""
    assert result.available is False


# --------------------------------------------------------------------------- #
# 9. Capability routing — hard video_generation + image,video gate
# --------------------------------------------------------------------------- #
def test_i2v_gate_requires_video_generation_and_image_video():
    req = GENERATION_REQUIREMENTS[TASK_I2V]
    assert CAP_VIDEO_GENERATION in req.required
    assert MODALITY_IMAGE in req.modalities and MODALITY_VIDEO in req.modalities


def test_router_selects_wired_i2v_runtime():
    decision = GenerationRouter().select(TASK_I2V, model_id=WAN_I2V_MODEL_ID)
    assert decision.outcome == OUTCOME_SELECTED
    assert decision.runtime == RUNTIME_WAN_I2V
    assert decision.model == WAN_I2V_MODEL_ID
    assert decision.supported is True


def test_router_rejects_chat_vision_image_models_for_i2v():
    for model_id in ("qwen3:4b", "qwen3-vl:8b", "wan2.2-t2v", "hunyuanvideo-i2v", "flux.1-schnell"):
        decision = GenerationRouter().select(TASK_I2V, model_id=model_id)
        assert decision.model != model_id, model_id
        assert decision.outcome in (OUTCOME_NO_CAPABLE_RUNTIME, OUTCOME_INVALID_REQUEST)


def test_router_does_not_serve_i2v_for_an_unwired_runtime():
    """The diffusers (unwired) runtime must never satisfy an I2V task."""
    assert GenerationRouter().select(TASK_I2V, model_id="hunyuanvideo-i2v").selected is False


def test_router_rejects_text_to_video_and_image_tasks():
    router = GenerationRouter()
    assert router.select(TASK_T2V).outcome == OUTCOME_NO_CAPABLE_RUNTIME
    assert router.select(TASK_IMAGE).outcome == OUTCOME_NO_CAPABLE_RUNTIME


def test_router_unknown_task_is_invalid():
    assert GenerationRouter().select("nonsense").outcome == OUTCOME_INVALID_REQUEST


def test_chat_models_are_never_selected_as_i2v():
    """A chat model declaring image generation still cannot satisfy I2V (no video)."""
    class ChatWithImage:
        model_id = "chat-that-claims-images"
        name = "Fake"
        capability = CAP_IMAGE_GENERATION
        declared_capabilities = (CAP_IMAGE_GENERATION,)
        declared_modalities = (MODALITY_IMAGE,)

    class Mgr:
        adapters = {"fake": ChatWithImage()}

    decision = GenerationRouter(Mgr()).select(TASK_I2V)
    assert decision.outcome == OUTCOME_NO_CAPABLE_RUNTIME


# --------------------------------------------------------------------------- #
# 10. Configuration discovery (real detection only; no invented VRAM)
# --------------------------------------------------------------------------- #
def test_discover_runtime_config_never_fabricates_when_torch_absent(monkeypatch):
    import models.generation_runtime as gr

    original_import = __import__

    def _no_torch(name, *a, **k):  # noqa: ANN001, ANN002, ANN003
        if name == "torch" or name.startswith("torch."):
            raise ModuleNotFoundError("No module named 'torch'")
        return original_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _no_torch)
    cfg = gr.discover_runtime_config()
    assert cfg.available is False
    assert cfg.dtype == ""
    assert cfg.supports_device_map is False
    assert cfg.total_memory_gb == 0.0


def test_manager_provisioned_ids_is_offline_and_empty(checkpoint_dir):
    manager = LocalGenerationManager()
    assert manager.provisioned_ids() == set()


# --------------------------------------------------------------------------- #
# 11. API surface — additive, protected, secret-free
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path",
    ["/api/models/generation/status", "/api/models/generation/router"],
)
def test_generation_endpoints_require_auth(path):
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as fresh:
        assert fresh.get(path).status_code == 401


def test_generation_post_requires_auth():
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as fresh:
        assert fresh.post("/api/models/generation", json={}).status_code == 401


def test_generation_status_endpoint_shape(auth_client):
    body = auth_client.get("/api/models/generation/status").json()
    assert body["secrets_exposed"] is False
    assert body["automatic_download"] is False
    assert body["available"] == []
    model = next(m for m in body["models"] if m["model"] == WAN_I2V_MODEL_ID)
    assert model["runtime"] == RUNTIME_WAN_I2V
    assert model["loaded"] is False
    assert model["checkpoint_present"] is False


def test_generation_router_endpoint_gates(auth_client):
    body = auth_client.get("/api/models/generation/router").json()
    assert body["capability_gated"] is True
    assert body["tasks"]["i2v"]["outcome"] == OUTCOME_SELECTED
    assert body["tasks"]["t2v"]["outcome"] == OUTCOME_NO_CAPABLE_RUNTIME
    assert body["tasks"]["image"]["outcome"] == OUTCOME_NO_CAPABLE_RUNTIME


def test_generation_post_rejects_a_chat_model(auth_client):
    resp = auth_client.post("/api/models/generation", json={"model": "qwen3:4b", "image": "/tmp/x.png"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["outcome"] in (OUTCOME_NO_CAPABLE_RUNTIME, OUTCOME_INVALID_REQUEST)


def test_generation_post_invalid_input_is_400(auth_client):
    resp = auth_client.post("/api/models/generation", json={"model": WAN_I2V_MODEL_ID, "image": ""})
    assert resp.status_code == 400
    assert resp.json()["detail"]["reason"] == REASON_INVALID_INPUT


def test_generation_post_without_weights_is_503(auth_client, tmp_path):
    img = tmp_path / "src.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nREALIMAGE")
    resp = auth_client.post(
        "/api/models/generation",
        json={"model": WAN_I2V_MODEL_ID, "image": str(img), "prompt": "a fox runs"},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["reason"] == REASON_WEIGHTS_MISSING


def test_generation_endpoints_never_leak_secrets(auth_client):
    for path in ("/api/models/generation/status", "/api/models/generation/router"):
        blob = str(auth_client.get(path).json())
        for marker in ("sk-", "gsk-", "ghp_", "Bearer ", "api_key", "password", "token="):
            assert marker not in blob, f"{path} leaked {marker}"


def test_existing_endpoints_remain_backward_compatible(auth_client):
    for path in (
        "/api/models",
        "/api/models/catalog",
        "/api/models/router",
        "/api/models/runtimes",
        "/api/models/generation",
        "/api/models/provisioning",
        "/api/models/local/activation",
    ):
        assert auth_client.get(path).status_code == 200, path


# --------------------------------------------------------------------------- #
# 12. Startup guarantee — no weights loaded, no generation at import
# --------------------------------------------------------------------------- #
def test_startup_loads_no_generation_weights(checkpoint_dir, monkeypatch):
    """Importing + building the app must not load the generation runtime."""
    import importlib

    _make_checkpoint(checkpoint_dir)
    monkeypatch.setenv("LAIW_WAN_I2V_CHECKPOINT", str(checkpoint_dir / "Wan2.2-I2V-A14B"))
    import models.generation_runtime as gr

    importlib.reload(gr)
    manager = gr.LocalGenerationManager()
    adapter = manager.adapters[RUNTIME_WAN_I2V]
    # Weights are on disk, yet nothing was loaded at construct/import time.
    assert adapter.loaded is False
    assert adapter.lifecycle == LIFECYCLE_NOT_CONFIGURED


def test_no_generation_is_triggered_by_a_read_only_summary(checkpoint_dir, monkeypatch):
    _make_checkpoint(checkpoint_dir)
    _install_fake_modules(monkeypatch)
    manager = LocalGenerationManager()
    status = manager.status(load=False)
    assert status["models"][0]["loaded"] is False
    assert _FakePipeClass.built == []  # form_pretrained never called by a read-only view
