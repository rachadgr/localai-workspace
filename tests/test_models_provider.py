"""Model Provider system tests.

Covers: unified adapter contract, provider discovery, health checks, unavailable
providers, misconfigured credentials, successful routing, fallback routing,
streaming, health caching/expiration and secret redaction.

All provider I/O is replaced by deterministic fakes, so the suite never depends
on a real provider being reachable.
"""

from __future__ import annotations

import pytest

from backend.app.core.errors import ModelUnavailableError, NetworkError
from models.adapters import AnthropicAdapter, EchoAdapter, OllamaAdapter, OpenAICompatibleAdapter
from models.base import (
    CAP_CODE,
    CAP_EMBEDDINGS,
    CAP_VISION,
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_IMAGE,
    STATUS_AVAILABLE,
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_MISCONFIGURED,
    STATUS_UNAVAILABLE,
    ChatMessage,
    Completion,
    EmbeddingResult,
    ModelAdapter,
    ModelCapabilities,
    infer_capabilities,
    infer_context,
    infer_kind,
)
from models.registry import ModelRegistry
from models.router import TASK_CODE, TASK_EMBEDDING, TASK_IMAGE, TASK_VISION, ModelRouter


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeAdapter(ModelAdapter):
    """Deterministic adapter whose behaviour is fully controllable."""

    name = "openai_compatible"
    provider = "openai_compatible"

    def __init__(
        self,
        models: list[str] | None = None,
        *,
        configured: bool = True,
        fail_complete: bool = False,
        list_error: Exception | None = None,
        status_code: int | None = None,
        chunks: list[str] | None = None,
    ) -> None:
        self._models = models or ["fake-chat-1"]
        self.configured = configured
        self.fail_complete = fail_complete
        self.list_error = list_error
        self.status_code = status_code
        self.chunks = chunks or ["hel", "lo"]
        self.complete_calls = 0
        self.stream_calls = 0

    def is_configured(self) -> bool:
        return self.configured

    def list_models(self) -> list[str]:
        if self.list_error is not None:
            raise self.list_error
        return list(self._models)

    def complete(self, messages: list[ChatMessage], model: str, **opts) -> Completion:
        self.complete_calls += 1
        if self.fail_complete:
            if self.status_code in (401, 403):
                raise ModelUnavailableError("Model provider rejected credentials", detail=f"HTTP {self.status_code}")
            raise ModelUnavailableError("Model provider refused the request (billing/quota notice)")
        return Completion(text="pong", model=model, provider=self.provider, tokens_in=1, tokens_out=1)

    def stream(self, messages: list[ChatMessage], model: str, **opts):
        self.stream_calls += 1
        for chunk in self.chunks:
            yield chunk

    def embed(self, texts: list[str], model: str, **opts) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[0.1, 0.2, 0.3] for _ in texts], model=model, provider=self.provider, dimensions=3)


def make_registry(*adapters: tuple[str, ModelAdapter]) -> ModelRegistry:
    reg = ModelRegistry(build_adapters=False)
    for name, adapter in adapters:
        reg.register_adapter(name, adapter)
    return reg


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def time(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# --------------------------------------------------------------------------- #
# Unified interface contract
# --------------------------------------------------------------------------- #
def test_unified_interface_all_adapters_implement_contract():
    required = ["is_configured", "status", "list_models", "discover", "complete", "stream", "health_check", "describe", "endpoint_label"]
    for adapter in (
        OpenAICompatibleAdapter("http://localhost:1/v1", "k"),
        AnthropicAdapter("https://api.anthropic.com", "k"),
        OllamaAdapter("http://localhost:11434"),
        EchoAdapter(),
    ):
        assert isinstance(adapter, ModelAdapter)
        for method in required:
            assert callable(getattr(adapter, method)), f"{adapter.name} missing {method}"


def test_interface_supports_capability_surface():
    # Vision / embeddings / image / video entry points exist on the contract.
    for method in ("complete", "stream", "embed", "generate_image", "generate_video"):
        assert callable(getattr(ModelAdapter, method))


def test_embedding_unsupported_raises_not_fabricates():
    adapter = FakeAdapter.__mro__  # placeholder to keep import usage explicit
    del adapter
    plain = ModelAdapter()
    with pytest.raises(ModelUnavailableError):
        plain.embed(["x"], model="m")


# --------------------------------------------------------------------------- #
# Provider configuration / discovery
# --------------------------------------------------------------------------- #
def test_misconfigured_provider_reports_misconfigured():
    reg = make_registry(("openai_compatible", FakeAdapter(configured=False)))
    health = reg.health()
    assert health["providers"]["openai_compatible"]["status"] == STATUS_MISCONFIGURED
    assert health["providers"]["openai_compatible"]["configured"] is False
    assert health["models_total"] == 0


def test_echo_disabled_by_default():
    echo = EchoAdapter()
    assert echo.status() == STATUS_DISABLED
    assert echo.is_configured() is False


def test_unavailable_provider_does_not_crash():
    reg = make_registry(("openai_compatible", FakeAdapter(list_error=NetworkError("connection refused"))))
    health = reg.health()
    assert health["providers"]["openai_compatible"]["status"] == STATUS_UNAVAILABLE
    assert health["status"] == STATUS_UNAVAILABLE
    assert health["chat_usable"] is False


def test_listing_is_not_proof_of_availability():
    """A provider that lists models but refuses completions → models UNAVAILABLE."""
    reg = make_registry(("openai_compatible", FakeAdapter(["gpt-5.4-mini", "gpt-5"], fail_complete=True)))
    models = reg.refresh(force=True)
    assert models, "models should be discovered"
    assert all(m.status == STATUS_UNAVAILABLE for m in models.values())
    assert reg.chat_available(force=True) is False
    assert reg.health()["chat_usable"] is False


def test_successful_probe_marks_available():
    reg = make_registry(("openai_compatible", FakeAdapter(["gpt-5.4-mini"], fail_complete=False)))
    models = reg.refresh(force=True)
    assert models["gpt-5.4-mini"].status == STATUS_AVAILABLE
    assert reg.chat_available(force=True) is True


def test_misconfigured_credentials_classified():
    reg = make_registry(("openai_compatible", FakeAdapter(["m"], fail_complete=True, status_code=401)))
    models = reg.refresh(force=True)
    assert models["m"].status == STATUS_MISCONFIGURED


def test_rich_metadata_present():
    reg = make_registry(("openai_compatible", FakeAdapter(["gpt-5.4-mini"], fail_complete=False)))
    info = reg.get("gpt-5.4-mini")
    for field in ("id", "name", "provider", "type", "capabilities", "context_length", "vision", "tools", "streaming", "local", "endpoint", "status", "health", "last_checked", "error", "config_source"):
        assert hasattr(info, field), field


# --------------------------------------------------------------------------- #
# Health caching
# --------------------------------------------------------------------------- #
def test_health_check_is_cached_and_expires(monkeypatch):
    import importlib

    registry_module = importlib.import_module("models.registry")
    clock = FakeClock()
    monkeypatch.setattr(registry_module.time, "time", clock.time)

    adapter = FakeAdapter(["gpt-5.4-mini"], fail_complete=False)
    reg = make_registry(("openai_compatible", adapter))
    reg.refresh(force=True)
    first_calls = adapter.complete_calls
    assert first_calls == 1

    # Within TTL: cached, no new probe.
    reg.check_model_health("gpt-5.4-mini")
    assert adapter.complete_calls == first_calls

    # Past TTL: probe runs again.
    clock.advance(10_000)
    reg.check_model_health("gpt-5.4-mini")
    assert adapter.complete_calls == first_calls + 1

    # Force always re-probes.
    reg.check_model_health("gpt-5.4-mini", force=True)
    assert adapter.complete_calls == first_calls + 2


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def _router_registry() -> ModelRegistry:
    adapter = FakeAdapter(
        ["gpt-5.4-mini", "gpt-5-code", "claude-vision", "text-embedding-3", "dall-e-3"],
        fail_complete=False,
    )
    reg = make_registry(("openai_compatible", adapter))
    reg.refresh(force=True)
    return reg


def test_router_selects_by_capability_not_provider_name():
    reg = _router_registry()
    router = ModelRouter(reg)

    chat = router.select("chat")
    assert chat.model is not None

    code = router.select(TASK_CODE)
    assert code.model is not None
    # The chosen model must actually carry the code capability.
    assert CAP_CODE in reg.get(code.model).capabilities

    vision = router.select(TASK_VISION)
    assert vision.model is not None
    assert CAP_VISION in reg.get(vision.model).capabilities

    embedding = router.select(TASK_EMBEDDING)
    assert embedding.model == "text-embedding-3"

    image = router.select(TASK_IMAGE)
    assert image.model == "dall-e-3"


def test_router_excludes_unavailable_models():
    adapter = FakeAdapter(["gpt-5-code"], fail_complete=True)  # lists but refuses
    reg = make_registry(("openai_compatible", adapter))
    reg.refresh(force=True)
    decision = ModelRouter(reg).select(TASK_CODE)
    assert decision.model is None
    assert decision.available is False
    assert "No AVAILABLE model" in decision.reason


def test_router_deterministic_fallback_ordering():
    reg = _router_registry()
    router = ModelRouter(reg)
    first = router.select("chat").candidates
    second = router.select("chat").candidates
    assert first == second and first, "candidate ordering must be stable"
    # Deterministic tiebreak by (provider, id).
    assert first == sorted(first)


def test_router_no_models_returns_none_honestly():
    reg = make_registry(("openai_compatible", FakeAdapter(configured=False)))
    decision = ModelRouter(reg).select("chat")
    assert decision.model is None
    assert decision.available is False


def test_router_resolve_prefers_explicit_when_available():
    reg = _router_registry()
    router = ModelRouter(reg)
    assert router.resolve("chat", "gpt-5.4-mini") == "gpt-5.4-mini"
    # Explicit-but-unusable falls back to task routing (never a hard failure).
    assert router.resolve("chat", "does-not-exist") is not None


def test_registry_route_helper_delegates_to_router():
    reg = _router_registry()
    decision = reg.route(TASK_CODE)
    assert decision.available is True
    assert decision.model is not None


# --------------------------------------------------------------------------- #
# Streaming
# --------------------------------------------------------------------------- #
def test_streaming_yields_chunks():
    adapter = FakeAdapter(["gpt-5.4-mini"], chunks=["a", "b", "c"])
    reg = make_registry(("openai_compatible", adapter))
    reg.refresh(force=True)
    out = list(reg.stream([ChatMessage("user", "hi")], model="gpt-5.4-mini"))
    assert out == ["a", "b", "c"]
    assert adapter.stream_calls == 1


def test_complete_routes_through_adapter():
    adapter = FakeAdapter(["gpt-5.4-mini"])
    reg = make_registry(("openai_compatible", adapter))
    reg.refresh(force=True)
    completion = reg.complete([ChatMessage("user", "hi")], model="gpt-5.4-mini")
    assert completion.text == "pong"
    assert completion.provider == "openai_compatible" or completion.provider == "fake"


# --------------------------------------------------------------------------- #
# Inference heuristics
# --------------------------------------------------------------------------- #
def test_inference_kind_and_capabilities():
    assert infer_kind("text-embedding-3-small") == KIND_EMBEDDING
    assert infer_kind("dall-e-3") == KIND_IMAGE
    assert infer_kind("gpt-5.4-mini") == KIND_CHAT

    assert infer_capabilities("gpt-5-code").code is True
    assert infer_capabilities("claude-3-5-sonnet").vision is True
    assert CAP_EMBEDDINGS in infer_capabilities("bge-m3").to_list()
    assert infer_context("gpt-5.4") >= 200_000
    assert ModelCapabilities.from_list(["chat", "tools"]).tools is True


# --------------------------------------------------------------------------- #
# Secret handling
# --------------------------------------------------------------------------- #
def test_openai_adapter_rejects_control_message(monkeypatch):
    """A billing/quota notice in the body must raise, never become model output."""
    import models.adapters as adapters_module

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"role": "assistant", "content": "Free-plan credits can't be used with the Genspark API"}, "finish_reason": "stop"}],
                "usage": {},
            }

    monkeypatch.setattr(adapters_module.requests, "post", lambda *a, **k: FakeResponse())
    adapter = OpenAICompatibleAdapter("https://example.test/v1", "k")
    with pytest.raises(ModelUnavailableError):
        adapter.complete([ChatMessage("user", "hi")], model="m")


def test_redact_hides_keys():
    from backend.app.core.security import redact

    text = "authorization: Bearer sk-abcdef1234567890 and ghp_ABCDEF1234567890"
    out = redact(text)
    assert "sk-abcdef" not in out
    assert "ghp_ABCDEF" not in out


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #
def test_models_api_endpoints(auth_client):
    r = auth_client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body and "models" in body and "chat_usable" in body

    r2 = auth_client.get("/api/models/providers")
    assert r2.status_code == 200
    assert r2.json()["secrets_exposed"] is False

    r3 = auth_client.get("/api/models/router")
    assert r3.status_code == 200
    assert "tasks" in r3.json()
    # Router must exclude unavailable models (never fabricate a selection).
    for decision in r3.json()["tasks"].values():
        if decision["model"] is None:
            assert "No AVAILABLE model" in decision["reason"]


def test_connection_test_endpoint_never_leaks_secrets(auth_client):
    r = auth_client.post("/api/models/test-connection", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["secrets_exposed"] is False
    blob = str(body)
    for marker in ("sk-", "gsk-", "ghp_", "Bearer "):
        assert marker not in blob, f"leaked {marker}"
    for result in body["results"]:
        assert set(result) >= {"provider", "configured", "status", "ok", "model", "latency_ms", "error"}
        assert "api_key" not in str(result).lower()


def test_connection_test_unknown_provider_404(auth_client):
    r = auth_client.post("/api/models/test-connection", json={"provider": "nope"})
    assert r.status_code == 404


def test_health_endpoint_reports_model_state(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["models"]["status"] in (STATUS_AVAILABLE, STATUS_UNAVAILABLE)


def test_models_providers_frontend_is_served(client):
    r = client.get("/models.html")
    assert r.status_code == 200
    assert "Providers" in r.text
    # The page must never render a provider secret.
    assert "OPENAI_API_KEY" not in r.text


def test_settings_never_leak_secrets(auth_client):
    body = auth_client.get("/api/settings").json()
    for key, value in body.items():
        assert not (isinstance(value, str) and value.startswith(("sk-", "gsk-", "ghp_"))), key


# --------------------------------------------------------------------------- #
# Documentation / configuration surface
# --------------------------------------------------------------------------- #
def test_env_example_documents_provider_vars():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    for var in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_BASE_URL"):
        assert var in text, var
    assert "LAIW_PROVIDER_" in text
    assert "LAIW_MODEL_HEALTH_TTL" in text
