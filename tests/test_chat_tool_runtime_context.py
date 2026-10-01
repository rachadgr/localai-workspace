"""ChatTool runtime-context tests.

These tests lock in the dynamic *Runtime Context* the ChatTool injects from the
model registry. They assert:

* a selected model that is ``AVAILABLE`` with ``local=True`` surfaces those facts;
* ``provider`` and ``endpoint`` come straight from the registry metadata;
* nothing is hardcoded (no ``ollama`` / ``qwen3:4b`` / endpoint constant leaks in);
* the ChatTool answer never fails when registry metadata is absent or broken.

All provider I/O is replaced by deterministic fakes, so the suite never depends
on a real provider being reachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from backend.app.core.errors import ModelUnavailableError
from models.base import STATUS_AVAILABLE, ChatMessage, Completion
from tools.base import ToolContext
from tools.chat_tool import ChatTool

#: Strings that must never appear unless the registry itself put them there.
_HARDCODED_MARKERS = ("ollama", "qwen3:4b", "localhost", "11434")


@dataclass
class FakeModelInfo:
    """Minimal stand-in for ``models.registry.ModelInfo`` (only what the tool reads)."""

    id: str
    name: str = ""
    provider: str = ""
    status: str = STATUS_AVAILABLE
    local: bool = False
    endpoint: str = ""
    vision: bool = False
    tools: bool = False
    streaming: bool = False
    context_window: int = 0
    context_length: int = 0


class RecordingRegistry:
    """Fake registry that records the messages it is asked to complete."""

    def __init__(
        self,
        info: FakeModelInfo | None = None,
        *,
        default_id: str | None = None,
        raises: bool = False,
    ) -> None:
        self._info = info
        # ``default_chat_model`` id: explicit override, else the info id, else None.
        self._default_id = default_id if default_id is not None else (info.id if info else None)
        self._raises = raises
        self.captured: list[ChatMessage] | None = None
        self.complete_calls = 0

    # The tool resolves the model through this method when ``model`` is not given.
    def default_chat_model(self) -> str:
        if self._default_id is None:
            raise ModelUnavailableError("No chat model AVAILABLE")
        return self._default_id

    # Metadata lookup used by the runtime-context injection.
    def get(self, model_id: str) -> FakeModelInfo | None:
        if self._raises:
            raise RuntimeError("registry lookup exploded")
        return self._info

    def complete(self, messages: list[Any], model: str | None = None, **opts: Any) -> Completion:
        self.complete_calls += 1
        self.captured = list(messages)
        return Completion(text="ok", model=model or "", provider=(self._info.provider if self._info else ""))

    # -- helpers ------------------------------------------------------------
    def system_text(self) -> str:
        assert self.captured is not None, "complete() was never called"
        return "\n".join(m.content for m in self.captured if m.role == "system")

    def roles(self) -> list[str]:
        assert self.captured is not None
        return [m.role for m in self.captured]


def _execute(registry: RecordingRegistry, payload: dict[str, Any]):
    ctx = ToolContext(project_id="prj_test", model_registry=registry)
    return ChatTool().execute(ctx, payload)


# --------------------------------------------------------------------------- #
# AVAILABLE + local=True facts are surfaced
# --------------------------------------------------------------------------- #
def test_runtime_context_surfaces_available_local_model():
    info = FakeModelInfo(
        id="acme-local-1",
        name="Acme Local 1",
        provider="acme_local",
        status=STATUS_AVAILABLE,
        local=True,
        endpoint="http://127.0.0.1:9000/v1",
        vision=True,
        tools=True,
        streaming=True,
        context_window=131072,
    )
    reg = RecordingRegistry(info)
    result = _execute(reg, {"message": "Are you running locally?"})

    assert result.status == "SUCCESS"
    text = reg.system_text()
    assert "acme-local-1" in text
    assert "Acme Local 1" in text
    assert "acme_local" in text
    assert STATUS_AVAILABLE in text
    assert "local: true" in text
    assert "http://127.0.0.1:9000/v1" in text
    assert "vision: true" in text
    assert "tools: true" in text
    assert "streaming: true" in text
    assert "131072" in text


def test_runtime_context_instructs_facts_are_authoritative():
    info = FakeModelInfo(id="m-1", provider="p-1", local=True)
    reg = RecordingRegistry(info)
    _execute(reg, {"message": "hi"})

    text = reg.system_text().lower()
    # The model must be told these are runtime facts it must not override.
    assert "runtime facts" in text
    assert "authoritative" in text
    assert "do not contradict" in text


def test_runtime_context_falls_back_to_context_length_alias():
    """``context_window`` may be absent; the ``context_length`` alias is used."""
    info = FakeModelInfo(id="alias-1", provider="alias-prov", context_window=0, context_length=65536)
    reg = RecordingRegistry(info)
    _execute(reg, {"message": "size?"})
    assert "65536" in reg.system_text()


# --------------------------------------------------------------------------- #
# provider / endpoint come from the registry (dynamic)
# --------------------------------------------------------------------------- #
def test_provider_and_endpoint_are_read_from_registry():
    info = FakeModelInfo(
        id="cloudy-7",
        provider="sky_provider",
        local=False,
        endpoint="https://sky.example/api/v2",
    )
    reg = RecordingRegistry(info)
    result = _execute(reg, {"message": "Which provider serves you?"})

    assert result.status == "SUCCESS"
    text = reg.system_text()
    assert "provider: sky_provider" in text
    assert "endpoint: https://sky.example/api/v2" in text
    assert "local: false" in text
    # Output data still carries the completion's provider (unchanged behaviour).
    assert result.data["provider"] == "sky_provider"


# --------------------------------------------------------------------------- #
# No hardcoding: facts track the registry, not constants
# --------------------------------------------------------------------------- #
def test_no_hardcoded_provider_or_endpoint():
    info = FakeModelInfo(
        id="totally-different-9",
        name="Totally Different",
        provider="unrelated_provider",
        local=True,
        endpoint="https://unrelated.example/v1",
    )
    reg = RecordingRegistry(info)
    _execute(reg, {"message": "status?"})

    text = reg.system_text().lower()
    for marker in _HARDCODED_MARKERS:
        assert marker not in text, f"hardcoded marker leaked into runtime context: {marker}"


def test_runtime_context_tracks_the_selected_model():
    """Two different registries produce two different runtime contexts."""
    first = RecordingRegistry(FakeModelInfo(id="model-a", provider="prov-a", endpoint="https://a.example/v1"))
    _execute(first, {"message": "hi"})
    second = RecordingRegistry(FakeModelInfo(id="model-b", provider="prov-b", endpoint="https://b.example/v1"))
    _execute(second, {"message": "hi"})

    assert "model-a" in first.system_text() and "model-b" not in first.system_text()
    assert "model-b" in second.system_text() and "model-a" not in second.system_text()


# --------------------------------------------------------------------------- #
# Ordering is preserved (system → runtime facts → context → history → user)
# --------------------------------------------------------------------------- #
def test_message_ordering_is_preserved():
    info = FakeModelInfo(id="order-1", provider="order-prov")
    reg = RecordingRegistry(info)
    _execute(
        reg,
        {
            "message": "final question",
            "context": "PROJECT_CTX",
            "history": [
                {"role": "user", "content": "HIST_USER"},
                {"role": "assistant", "content": "HIST_ASSISTANT"},
            ],
        },
    )

    assert reg.roles() == ["system", "system", "system", "user", "assistant", "user"]
    contents = [m.content for m in reg.captured]
    assert contents[0].startswith("You are LocalAI Workspace")  # default system first
    assert "runtime facts" in contents[1].lower()  # runtime context second
    assert contents[2] == "Project context:\nPROJECT_CTX"
    assert contents[-1] == "final question"


def test_single_call_adds_exactly_one_runtime_context_message():
    info = FakeModelInfo(id="stable-1", provider="stable-prov")
    reg = RecordingRegistry(info)
    _execute(reg, {"message": "one"})
    assert reg.roles() == ["system", "system", "user"]
    # Exactly one system message carries the runtime-context banner.
    runtime_messages = [m for m in reg.captured if m.role == "system" and "runtime facts" in m.content.lower()]
    assert len(runtime_messages) == 1


# --------------------------------------------------------------------------- #
# Graceful degradation when metadata is missing or broken
# --------------------------------------------------------------------------- #
def test_answer_succeeds_without_model_info_metadata():
    """A registry that exposes no ModelInfo still answers (no runtime context, no crash)."""
    reg = RecordingRegistry(None, default_id="ghost-model")
    result = _execute(reg, {"message": "hello"})

    assert result.status == "SUCCESS"
    assert reg.complete_calls == 1
    # No runtime-context message is injected when metadata is unavailable.
    assert "runtime facts" not in reg.system_text().lower()
    assert reg.roles() == ["system", "user"]


def test_explicit_model_without_metadata_still_succeeds():
    reg = RecordingRegistry(None)
    result = _execute(reg, {"message": "hello", "model": "explicit-model"})

    assert result.status == "SUCCESS"
    assert reg.complete_calls == 1
    assert "runtime facts" not in reg.system_text().lower()


def test_no_model_at_all_preserves_existing_behaviour():
    """With no model and no metadata, the pre-existing ``ModelUnavailableError`` path is kept."""
    reg = RecordingRegistry(None)
    with pytest.raises(ModelUnavailableError):
        _execute(reg, {"message": "hello"})
    assert reg.complete_calls == 0


def test_answer_succeeds_when_registry_lookup_raises():
    info = FakeModelInfo(id="explosive-1", provider="boom")
    reg = RecordingRegistry(info, raises=True)

    result = _execute(reg, {"message": "hi", "model": "explosive-1"})
    assert result.status == "SUCCESS"
    assert reg.complete_calls == 1
    assert "runtime facts" not in reg.system_text().lower()


def test_system_override_still_precedes_runtime_context():
    """A caller-provided ``system`` override keeps position 0; runtime facts follow."""
    info = FakeModelInfo(id="ovr-1", provider="ovr-prov", local=True)
    reg = RecordingRegistry(info)
    _execute(reg, {"message": "hi", "system": "CUSTOM_SYSTEM"})

    contents = [m.content for m in reg.captured]
    assert contents[0] == "CUSTOM_SYSTEM"
    assert "runtime facts" in contents[1].lower()
