"""LocalAI provider integration tests.

Verifies the LocalAI runtime adapter is wired honestly: it is a *local*,
OpenAI-compatible provider that is only registered when ``LOCALAI_BASE_URL`` is
set, reports ``MISCONFIGURED`` when unset (never fabricated), participates in the
runtime matrix and the catalog, and never leaks secrets.
"""

from __future__ import annotations

import pytest

from models.adapters import LocalAIAdapter
from models.base import STATUS_MISCONFIGURED, ModelAdapter
from models.catalog import LOCAL_PROVIDERS, catalog_entries
from models.registry import ModelRegistry
from models.runtimes import RUNTIME_LOCALAI, runtime_view


def test_localai_adapter_implement_contract():
    adapter = LocalAIAdapter("http://localhost:8080")
    assert isinstance(adapter, ModelAdapter)
    assert adapter.name == "localai"
    assert adapter.provider == "localai"
    assert adapter.is_local is True
    for method in ("is_configured", "status", "list_models", "discover", "complete", "stream", "health_check", "endpoint_label"):
        assert callable(getattr(adapter, method))


def test_localai_unset_reports_misconfigured():
    adapter = LocalAIAdapter("")
    assert adapter.is_configured() is False
    assert adapter.status() == STATUS_MISCONFIGURED


def test_localai_registered_only_when_configured(monkeypatch):
    # Unset → provider not registered (honest absence).
    reg = ModelRegistry(build_adapters=True)
    reg._build_adapters()
    assert "localai" not in reg.adapters()


def test_localai_runtime_present_in_matrix():
    view = runtime_view()
    ids = {r["id"] for r in view.get("runtimes", [])}
    assert RUNTIME_LOCALAI in ids
    localai = next(r for r in view["runtimes"] if r["id"] == RUNTIME_LOCALAI)
    assert localai["local"] is True
    assert localai["supported"] is True


def test_localai_is_a_local_provider():
    assert "localai" in LOCAL_PROVIDERS


def test_localai_catalog_entries_declared():
    ids = {e.id for e in catalog_entries()}
    # A representative subset of the declared LocalAI catalog models.
    for mid in ("llama-3.2-3b-instruct", "all-minilm-l6-v2", "stablediffusion"):
        assert mid in ids, mid


def test_runtime_view_never_leaks_secrets():
    view = runtime_view()
    blob = str(view)
    for marker in ("sk-", "gsk-", "ghp_", "Bearer "):
        assert marker not in blob, f"leaked {marker}"
