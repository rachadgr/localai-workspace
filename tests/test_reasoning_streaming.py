"""Reasoning / thinking separation tests (Qwen3-style providers).

The bug being locked down: a model whose chain-of-thought is exposed by the
provider (``delta.reasoning`` on Ollama's ``/v1`` surface, ``message.thinking`` on
its native ``/api/chat``, or inline `` thinking…`` markers) must **never** have its
raw reasoning emitted to the client as the assistant answer. ``content`` is the
final answer; reasoning is captured internally.

All provider I/O is replaced by deterministic fakes, so the suite never depends on
a real runtime.
"""

from __future__ import annotations

import json

import pytest

import models.adapters as adapters_module
from models.adapters import (
    OllamaAdapter,
    OpenAICompatibleAdapter,
    ReasoningStreamSplitter,
    _first_reasoning_field,
    _split_reasoning_fields,
    _strip_inline_reasoning,
)
from models.base import ChatMessage

# --------------------------------------------------------------------------- #
# Fakes: SSE (/v1) and NDJSON (native /api/chat) streaming responses
# --------------------------------------------------------------------------- #
OPEN = "<" + "think" + ">"
CLOSE = "<" + "/" + "think" + ">"


class FakeStreamResponse:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def iter_lines(self, decode_unicode: bool = False):  # noqa: ARG002 - signature match
        yield from self._lines


class FakeJsonResponse:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def sse_delta(**delta) -> str:
    return "data: " + json.dumps({"choices": [{"delta": delta, "index": 0}]})


def native_line(content=None, thinking=None, done=False) -> str:
    message = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if thinking is not None:
        message["thinking"] = thinking
    return json.dumps({"model": "qwen3:4b", "message": message, "done": done})


def patch_stream(monkeypatch, lines: list[str]):
    monkeypatch.setattr(adapters_module.requests, "post", lambda *a, **k: FakeStreamResponse(lines))


# --------------------------------------------------------------------------- #
# Unit: helpers + splitter
# --------------------------------------------------------------------------- #
def test_split_reasoning_fields_separated():
    answer, reasoning = _split_reasoning_fields({"content": "the answer", "reasoning": "the chain"})
    assert answer == "the answer"
    assert reasoning == "the chain"


def test_split_reasoning_fields_thinking_key():
    answer, reasoning = _split_reasoning_fields({"content": "", "thinking": "pondering"})
    assert answer == ""
    assert reasoning == "pondering"


def test_split_reasoning_fields_inline_markers():
    answer, reasoning = _split_reasoning_fields({"content": f"visible {OPEN}hidden{CLOSE} world"})
    assert answer == "visible  world" or answer.replace(" ", "") == "visibleworld"
    assert "hidden" in reasoning


def test_strip_inline_reasoning_plain_answer_untouched():
    answer, reasoning = _strip_inline_reasoning("just a normal answer")
    assert answer == "just a normal answer"
    assert reasoning == ""


def test_splitter_handles_markers_split_across_chunks():
    splitter = ReasoningStreamSplitter()
    emitted = ""
    for chunk in ["a<thi", "nk>hid", "den", CLOSE + "b"]:
        emitted += splitter.feed(chunk)
    emitted += splitter.flush()
    assert emitted == "ab"
    assert splitter.reasoning == "hidden"


def test_splitter_reasoning_only_yields_nothing():
    splitter = ReasoningStreamSplitter()
    emitted = splitter.feed(OPEN + "thinking hard" + CLOSE)
    emitted += splitter.flush()
    assert emitted == ""
    assert splitter.reasoning == "thinking hard"


def test_first_reasoning_field_prefers_reasoning():
    assert _first_reasoning_field({"reasoning": "r", "thinking": "t"}) == "r"
    assert _first_reasoning_field({"content": "c"}) == ""


# --------------------------------------------------------------------------- #
# /v1 (OpenAI-compatible) streaming — the Ollama default path
# --------------------------------------------------------------------------- #
def test_v1_stream_reasoning_only_then_content(monkeypatch):
    """reasoning-only chunks first, then content: only the answer is emitted."""
    lines = [
        sse_delta(reasoning="why "),
        sse_delta(reasoning="because"),
        sse_delta(content="The "),
        sse_delta(content="answer."),
        "data: [DONE]",
    ]
    patch_stream(monkeypatch, lines)
    adapter = OpenAICompatibleAdapter("http://localhost:11434/v1", "k", label="ollama")
    out = list(adapter.stream([ChatMessage("user", "hi")], model="qwen3:4b"))
    assert out == ["The ", "answer."]
    assert adapter.last_reasoning == "why because"
    # No reasoning token ever leaked into the answer.
    assert "why" not in "".join(out)


def test_v1_stream_reasoning_and_content_in_same_delta(monkeypatch):
    lines = [
        sse_delta(content="", reasoning="reasoning part"),
        sse_delta(content="final answer", reasoning=""),
        "data: [DONE]",
    ]
    patch_stream(monkeypatch, lines)
    adapter = OpenAICompatibleAdapter("http://localhost:11434/v1", "k", label="ollama")
    out = list(adapter.stream([ChatMessage("user", "hi")], model="qwen3:4b"))
    assert "".join(out) == "final answer"
    assert adapter.last_reasoning == "reasoning part"


def test_v1_stream_content_only(monkeypatch):
    lines = [sse_delta(content="hello "), sse_delta(content="world"), "data: [DONE]"]
    patch_stream(monkeypatch, lines)
    adapter = OpenAICompatibleAdapter("http://localhost:11434/v1", "k", label="ollama")
    out = list(adapter.stream([ChatMessage("user", "hi")], model="qwen3:4b"))
    assert "".join(out) == "hello world"
    assert adapter.last_reasoning == ""


def test_v1_stream_inline_reasoning_stripped(monkeypatch):
    """A provider that inlines  thinking…<｜end▁of▁thinking｜> inside content must not leak it."""
    lines = [
        sse_delta(content=f"{OPEN}hmm"),
        sse_delta(content=f" let me think{CLOSE}The answer is 42."),
        "data: [DONE]",
    ]
    patch_stream(monkeypatch, lines)
    adapter = OpenAICompatibleAdapter("http://localhost:11434/v1", "k", label="ollama")
    out = "".join(adapter.stream([ChatMessage("user", "hi")], model="qwen3:4b"))
    assert out == "The answer is 42."
    assert "hmm" in adapter.last_reasoning and "let me think" in adapter.last_reasoning


def test_v1_stream_ignores_unknown_reasoning_key(monkeypatch):
    lines = [sse_delta(content="ok"), "data: [DONE]"]
    patch_stream(monkeypatch, lines)
    adapter = OpenAICompatibleAdapter("http://localhost:11434/v1", "k", label="ollama")
    assert "".join(adapter.stream([ChatMessage("user", "hi")], model="qwen3:4b")) == "ok"


# --------------------------------------------------------------------------- #
# /v1 non-streaming — extraction
# --------------------------------------------------------------------------- #
def test_v1_complete_extracts_reasoning_separately(monkeypatch):
    payload = {
        "model": "qwen3:4b",
        "choices": [{"message": {"role": "assistant", "content": "2 + 2 = 4.", "reasoning": "add two and two"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 9},
    }
    monkeypatch.setattr(adapters_module.requests, "post", lambda *a, **k: FakeJsonResponse(payload))
    adapter = OpenAICompatibleAdapter("http://localhost:11434/v1", "k", label="ollama")
    completion = adapter.complete([ChatMessage("user", "hi")], model="qwen3:4b")
    assert completion.text == "2 + 2 = 4."
    assert completion.reasoning == "add two and two"
    assert completion.raw.get("reasoning") == "add two and two"


def test_v1_complete_reasoning_only_has_empty_text(monkeypatch):
    payload = {"model": "m", "choices": [{"message": {"role": "assistant", "content": "", "reasoning": "only thinking"}, "finish_reason": "length"}], "usage": {}}
    monkeypatch.setattr(adapters_module.requests, "post", lambda *a, **k: FakeJsonResponse(payload))
    adapter = OpenAICompatibleAdapter("http://localhost:11434/v1", "k", label="ollama")
    completion = adapter.complete([ChatMessage("user", "hi")], model="m")
    assert completion.text == ""
    assert completion.reasoning == "only thinking"


# --------------------------------------------------------------------------- #
# Ollama think control — native /api/chat is the only surface that honours it
# --------------------------------------------------------------------------- #
def test_ollama_without_think_uses_v1(monkeypatch):
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return FakeStreamResponse([sse_delta(content="hi"), "data: [DONE]"])

    monkeypatch.setattr(adapters_module.requests, "post", fake_post)
    adapter = OllamaAdapter("http://localhost:11434")
    out = list(adapter.stream([ChatMessage("user", "x")], model="qwen3:4b"))
    assert out == ["hi"]
    assert captured["url"].endswith("/v1/chat/completions")


def test_ollama_think_false_routes_to_native_api(monkeypatch):
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["body"] = json.loads(kwargs["data"])
        # native: thinking separated; content is the clean answer
        return FakeStreamResponse(
            [
                native_line(thinking="let me reason"),
                native_line(content="The answer"),
                native_line(content=" is 4.", done=True),
            ]
        )

    monkeypatch.setattr(adapters_module.requests, "post", fake_post)
    adapter = OllamaAdapter("http://localhost:11434")
    out = "".join(adapter.stream([ChatMessage("user", "x")], model="qwen3:4b", think=False))
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["think"] is False
    assert out == "The answer is 4."
    assert adapter.last_reasoning == "let me reason"


def test_ollama_think_true_routes_to_native_and_separates_thinking(monkeypatch):
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["body"] = json.loads(kwargs["data"])
        return FakeStreamResponse([native_line(thinking="chain"), native_line(content="answer", done=True)])

    monkeypatch.setattr(adapters_module.requests, "post", fake_post)
    adapter = OllamaAdapter("http://localhost:11434")
    out = "".join(adapter.stream([ChatMessage("user", "x")], model="qwen3:4b", think=True))
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["think"] is True
    assert out == "answer"
    assert adapter.last_reasoning == "chain"


def test_ollama_native_inline_reasoning_markers_stripped(monkeypatch):
    """Marker-wrapped inline reasoning is stripped wherever it appears."""
    def fake_post(url, **kwargs):
        return FakeStreamResponse([native_line(content=f"{OPEN}noise{CLOSE}The answer is 5.", done=True)])

    monkeypatch.setattr(adapters_module.requests, "post", fake_post)
    adapter = OllamaAdapter("http://localhost:11434")
    out = "".join(adapter.stream([ChatMessage("user", "x")], model="qwen3:4b", think=False))
    assert out == "The answer is 5."
    assert "noise" in adapter.last_reasoning


def test_ollama_native_unmarked_reasoning_is_honest_passthrough(monkeypatch):
    """Documented limitation: an unmarked reasoning leak (native think=false on
    some builds) cannot be separated — only marked blocks can. The adapter must
    not invent a separator; it passes the content through unchanged."""
    def fake_post(url, **kwargs):
        return FakeStreamResponse([native_line(content="plain reasoning The answer is 5.", done=True)])

    monkeypatch.setattr(adapters_module.requests, "post", fake_post)
    adapter = OllamaAdapter("http://localhost:11434")
    out = "".join(adapter.stream([ChatMessage("user", "x")], model="qwen3:4b", think=False))
    assert out == "plain reasoning The answer is 5."


def test_ollama_think_default_setting_used(monkeypatch):
    monkeypatch.setattr(adapters_module.settings, "ollama_think", "false")
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["body"] = json.loads(kwargs["data"])
        return FakeStreamResponse([native_line(content="ok", done=True)])

    monkeypatch.setattr(adapters_module.requests, "post", fake_post)
    adapter = OllamaAdapter("http://localhost:11434")
    list(adapter.stream([ChatMessage("user", "x")], model="qwen3:4b"))
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["think"] is False


def test_ollama_native_complete_extracts_thinking(monkeypatch):
    payload = {"model": "qwen3:4b", "message": {"role": "assistant", "content": "answer text", "thinking": "the chain"}, "done_reason": "stop", "eval_count": 7, "prompt_eval_count": 3}
    monkeypatch.setattr(adapters_module.requests, "post", lambda *a, **k: FakeJsonResponse(payload))
    adapter = OllamaAdapter("http://localhost:11434")
    completion = adapter.complete([ChatMessage("user", "x")], model="qwen3:4b", think=True)
    assert completion.text == "answer text"
    assert completion.reasoning == "the chain"
    assert completion.tokens_out == 7
    assert completion.tokens_in == 3


# --------------------------------------------------------------------------- #
# SSE contract: /api/chat sends answer tokens only, then done
# --------------------------------------------------------------------------- #
def test_sse_chat_sends_answer_tokens_only_then_done(monkeypatch, auth_client):
    from backend.app.routers import agent as agent_module

    # Stream that would (if unfiltered) include reasoning — but the adapter layer
    # already guarantees only answer tokens; here we assert the router forwards
    # exactly those tokens then a single done event.
    def fake_stream(messages, model=None, **opts):  # noqa: ARG001
        yield "The "
        yield "answer."

    monkeypatch.setattr(agent_module.model_registry, "stream", fake_stream)

    pid = auth_client.post("/api/projects", json={"name": "Reasoning SSE"}).json()["id"]
    resp = auth_client.post(
        "/api/chat",
        json={"message": "hello", "project_id": pid, "model": "qwen3:4b", "stream": True},
    )
    assert resp.status_code == 200
    body = resp.text
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    # token(s) first, then exactly one done — no reasoning/thinking event types.
    assert types.count("done") == 1
    assert types[-1] == "done"
    assert "reasoning" not in types and "thinking" not in types
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert tokens == "The answer."


def test_sse_chat_reasoning_only_produces_no_answer_tokens(monkeypatch, auth_client):
    """If the adapter yields nothing (reasoning-only), SSE still emits done only."""
    from backend.app.routers import agent as agent_module

    def fake_stream(messages, model=None, **opts):  # noqa: ARG001
        return iter([])

    monkeypatch.setattr(agent_module.model_registry, "stream", fake_stream)

    pid = auth_client.post("/api/projects", json={"name": "Reasoning-only SSE"}).json()["id"]
    resp = auth_client.post(
        "/api/chat",
        json={"message": "hello", "project_id": pid, "model": "qwen3:4b", "stream": True},
    )
    assert resp.status_code == 200
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["done"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
