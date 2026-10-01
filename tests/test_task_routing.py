"""Task-routing contract tests — the Model Catalog actually driving Task Routing.

This module locks in the behaviour added on top of the declarative Model Catalog:

* a single, explicit **task vocabulary**
  (``chat``/``text``/``reasoning``/``coding``/``vision``/``image``/``embedding``/
  ``video``/``i2v``/``tools``/``document``);
* **category is never availability** — a model is a candidate only while the
  runtime probed it ``AVAILABLE``;
* **capability + modality are hard constraints** — the router must never send a
  ``vision`` / ``image`` / ``video`` / ``embedding`` task to a chat-only model;
* an honest, machine-readable ``NO_CAPABLE_MODEL`` verdict (never a wrong pick)
  when no AVAILABLE model satisfies the task;
* the deterministic fallback ordering and the preserved ``Qwen3:4B`` local model.

Everything runs against in-memory stubs / deterministic fakes — **no network I/O**
is performed anywhere in this module.
"""

from __future__ import annotations

import pytest

from models.base import (
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
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_IMAGE,
    KIND_VIDEO,
    MODALITY_EMBEDDING,
    MODALITY_IMAGE,
    MODALITY_TEXT,
    MODALITY_VIDEO,
    STATUS_AVAILABLE,
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_LOADING,
    STATUS_MISCONFIGURED,
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
)
from models.router import (
    OUTCOME_NO_CAPABLE_MODEL,
    OUTCOME_REGISTRY_UNAVAILABLE,
    OUTCOME_SELECTED,
    TASK_CHAT,
    TASK_CODE,
    TASK_CODING,
    TASK_DOCUMENT,
    TASK_EMBEDDING,
    TASK_I2V,
    TASK_IMAGE,
    TASK_REASONING,
    TASK_REQUIREMENTS,
    TASK_TEXT,
    TASK_TOOLS,
    TASK_VIDEO,
    TASK_VISION,
    ModelRouter,
    requirement_for,
    satisfies_requirements,
)

#: Every task the router must understand.
ALL_TASKS = (
    TASK_CHAT,
    TASK_TEXT,
    TASK_CODING,
    TASK_CODE,
    TASK_DOCUMENT,
    TASK_VISION,
    TASK_IMAGE,
    TASK_EMBEDDING,
    TASK_VIDEO,
    TASK_I2V,
    TASK_REASONING,
    TASK_TOOLS,
)

#: Tasks that must never be routed to a chat-only (text, no vision) model.
NON_CHAT_MODALITIES = (TASK_VISION, TASK_IMAGE, TASK_VIDEO, TASK_I2V, TASK_EMBEDDING)

#: Every non-AVAILABLE status a capable model can hold.
NON_AVAILABLE_STATUSES = (
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
    STATUS_MISCONFIGURED,
    STATUS_DISABLED,
    STATUS_LOADING,
    STATUS_ERROR,
)


# --------------------------------------------------------------------------- #
# Test doubles (pure in-memory — no adapters, no sockets, no network calls)
# --------------------------------------------------------------------------- #
class StubModel:
    """A model row shaped like ``ModelInfo`` but fully controllable."""

    def __init__(
        self,
        model_id: str,
        capabilities: list[str],
        *,
        kind: str = KIND_CHAT,
        status: str = STATUS_AVAILABLE,
        provider: str = "stub",
        modality: list[str] | None = None,
        vision: bool | None = None,
        local: bool = False,
        context_length: int = 4096,
    ) -> None:
        self.id = model_id
        self.capabilities = list(capabilities)
        self.type = kind
        self.kind = kind
        self.status = status
        self.provider = provider
        self.modality = list(modality) if modality is not None else []
        self.vision = (CAP_VISION in capabilities) if vision is None else vision
        self.local = local
        self.context_length = context_length


class StubRegistry:
    """Minimal registry surface the router relies on (``refresh`` + ``get``)."""

    def __init__(self, models: list[StubModel], *, error: Exception | None = None) -> None:
        self._models = {m.id: m for m in models}
        self.error = error
        self.refresh_calls = 0

    def refresh(self, force: bool = False) -> dict[str, StubModel]:
        self.refresh_calls += 1
        if self.error is not None:
            raise self.error
        return dict(self._models)

    def get(self, model_id: str) -> StubModel | None:
        return self._models.get(model_id)


def chat_only(model_id: str = "plain-chat", *, status: str = STATUS_AVAILABLE, local: bool = False) -> StubModel:
    """A text chat model that carries **no** image/video/embedding capability."""
    return StubModel(model_id, [CAP_CHAT, CAP_STREAMING], kind=KIND_CHAT, status=status, local=local)


def vision_model(model_id: str = "vision-model") -> StubModel:
    return StubModel(model_id, [CAP_CHAT, CAP_STREAMING, CAP_VISION], kind=KIND_CHAT, modality=[MODALITY_TEXT, MODALITY_IMAGE])


def coding_model(model_id: str = "code-model") -> StubModel:
    return StubModel(model_id, [CAP_CHAT, CAP_STREAMING, CAP_CODE, CAP_TOOLS], kind=KIND_CHAT)


def reasoning_model(model_id: str = "reason-model") -> StubModel:
    return StubModel(model_id, [CAP_CHAT, CAP_STREAMING, CAP_REASONING, CAP_LONG_CONTEXT], kind=KIND_CHAT, context_length=131072)


def tools_model(model_id: str = "tools-model") -> StubModel:
    return StubModel(model_id, [CAP_CHAT, CAP_STREAMING, CAP_TOOLS], kind=KIND_CHAT)


def image_model(model_id: str = "img-model") -> StubModel:
    return StubModel(model_id, [CAP_IMAGE_GENERATION], kind=KIND_IMAGE, modality=[MODALITY_TEXT, MODALITY_IMAGE])


def embedding_model(model_id: str = "embed-model") -> StubModel:
    return StubModel(model_id, [CAP_EMBEDDINGS], kind=KIND_EMBEDDING, modality=[MODALITY_TEXT, MODALITY_EMBEDDING])


def video_model(model_id: str = "vid-model") -> StubModel:
    return StubModel(model_id, [CAP_VIDEO_GENERATION], kind=KIND_VIDEO, modality=[MODALITY_TEXT, MODALITY_VIDEO])


# --------------------------------------------------------------------------- #
# 1. Task vocabulary & requirement shape
# --------------------------------------------------------------------------- #
def test_every_required_task_class_is_defined():
    for task in ALL_TASKS:
        assert task in TASK_REQUIREMENTS, f"task '{task}' missing from TASK_REQUIREMENTS"


def test_requirements_are_well_formed():
    for task, req in TASK_REQUIREMENTS.items():
        assert req.kind in (KIND_CHAT, KIND_EMBEDDING, KIND_IMAGE, KIND_VIDEO), task
        # Hard constraints are tuples, never None, so callers can rely on them.
        assert isinstance(req.required, tuple) and isinstance(req.modalities, tuple)
        assert isinstance(req.preferred, tuple)


def test_unknown_task_defaults_to_a_safe_text_chat_gate():
    req = requirement_for("no-such-task")
    assert req.kind == KIND_CHAT
    assert req.modalities == (MODALITY_TEXT,)
    # A plain text chat model satisfies the fallback requirement…
    assert satisfies_requirements(chat_only(), req) is True
    # …and the router (which also enforces the chat category) never routes an
    # image generator through the fallback.
    assert ModelRouter(StubRegistry([image_model()])).select("no-such-task").model is None


def test_vision_image_embedding_video_are_hard_capability_gated():
    assert CAP_VISION in TASK_REQUIREMENTS[TASK_VISION].required
    assert CAP_IMAGE_GENERATION in TASK_REQUIREMENTS[TASK_IMAGE].required
    assert CAP_EMBEDDINGS in TASK_REQUIREMENTS[TASK_EMBEDDING].required
    assert CAP_VIDEO_GENERATION in TASK_REQUIREMENTS[TASK_VIDEO].required
    assert CAP_VIDEO_GENERATION in TASK_REQUIREMENTS[TASK_I2V].required


def test_reasoning_and_tools_are_hard_capability_gated():
    assert CAP_REASONING in TASK_REQUIREMENTS[TASK_REASONING].required
    assert CAP_TOOLS in TASK_REQUIREMENTS[TASK_TOOLS].required


def test_chat_and_coding_keep_no_hard_capability_gate():
    """Backwards compatible: plain chat/coding stay soft (no required caps)."""
    for task in (TASK_CHAT, TASK_TEXT, TASK_CODING, TASK_CODE, TASK_DOCUMENT):
        assert TASK_REQUIREMENTS[task].required == (), task


def test_every_task_requires_the_text_modality_or_its_output_modality():
    for task, req in TASK_REQUIREMENTS.items():
        assert req.modalities, f"{task} must declare at least one modality"


# --------------------------------------------------------------------------- #
# 2. Modality hard gate — a chat-only model is never eligible for multimodal tasks
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("task", NON_CHAT_MODALITIES)
def test_chat_only_model_is_never_eligible_for_multimodal_tasks(task):
    reg = StubRegistry([chat_only()])
    decision = ModelRouter(reg).select(task)
    assert decision.model is None
    assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


@pytest.mark.parametrize(
    "task,selector",
    [
        (TASK_VISION, vision_model),
        (TASK_IMAGE, image_model),
        (TASK_EMBEDDING, embedding_model),
        (TASK_VIDEO, video_model),
        (TASK_I2V, video_model),
        (TASK_REASONING, reasoning_model),
        (TASK_TOOLS, tools_model),
        (TASK_CODING, coding_model),
        (TASK_CHAT, chat_only),
    ],
)
def test_capable_model_is_selected_per_task(task, selector):
    model = selector()
    reg = StubRegistry([model])
    decision = ModelRouter(reg).select(task)
    assert decision.model == model.id
    assert decision.outcome == OUTCOME_SELECTED
    assert decision.available is True


def test_vision_requires_image_input_modality_not_just_a_flag_in_a_comment():
    """A model flagged vision but lacking image modality is rejected."""
    liar = StubModel("vision-liar", [CAP_CHAT, CAP_VISION], kind=KIND_CHAT, modality=[MODALITY_TEXT], vision=True)
    assert satisfies_requirements(liar, TASK_REQUIREMENTS[TASK_VISION]) is False
    reg = StubRegistry([liar])
    assert ModelRouter(reg).select(TASK_VISION).model is None


def test_image_task_rejects_a_chat_model_even_when_it_lists_image_generation_incorrectly():
    """Category is enforced *as well as* capabilities: an image task needs an
    image-kind model, so a chat model that (wrongly) lists image_generation is
    still not routed."""
    wrong_kind = StubModel("chat-that-claims-images", [CAP_CHAT, CAP_IMAGE_GENERATION], kind=KIND_CHAT, modality=[MODALITY_TEXT, MODALITY_IMAGE])
    # The capability gate alone would pass…
    assert satisfies_requirements(wrong_kind, TASK_REQUIREMENTS[TASK_IMAGE]) is True
    # …but the router's category gate rejects it.
    decision = ModelRouter(StubRegistry([wrong_kind])).select(TASK_IMAGE)
    assert decision.model is None
    assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


def test_text_task_never_selects_an_image_generator():
    reg = StubRegistry([image_model("img")])
    decision = ModelRouter(reg).select(TASK_CHAT)
    assert decision.model is None
    assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


# --------------------------------------------------------------------------- #
# 3. Availability is authoritative (NOT_CONFIGURED / UNAVAILABLE / … excluded)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", NON_AVAILABLE_STATUSES)
@pytest.mark.parametrize(
    "task,selector",
    [
        (TASK_CHAT, chat_only),
        (TASK_VISION, vision_model),
        (TASK_IMAGE, image_model),
        (TASK_EMBEDDING, embedding_model),
        (TASK_VIDEO, video_model),
        (TASK_I2V, video_model),
    ],
)
def test_only_available_models_are_routed(status, task, selector):
    model = selector()
    model.status = status
    reg = StubRegistry([model])
    decision = ModelRouter(reg).select(task)
    assert decision.model is None
    assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL
    assert "No AVAILABLE model" in decision.reason


def test_category_alone_is_not_availability():
    """Correct category + capability, but NOT_CONFIGURED → never selected."""
    pending = vision_model("vision-not-configured")
    pending.status = STATUS_NOT_CONFIGURED
    reg = StubRegistry([pending])
    decision = ModelRouter(reg).select(TASK_VISION)
    assert decision.model is None
    assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL
    # The reason names the real blocker status.
    assert STATUS_NOT_CONFIGURED in decision.reason
    # And the diagnostic histogram reports the excluded status.
    assert any(entry.startswith(STATUS_NOT_CONFIGURED) for entry in decision.excluded_status)


def test_available_model_alongside_unavailable_peers_is_selected():
    pending = vision_model("vision-pending")
    pending.status = STATUS_NOT_CONFIGURED
    ready = vision_model("vision-ready")
    reg = StubRegistry([pending, ready])
    decision = ModelRouter(reg).select(TASK_VISION)
    assert decision.model == "vision-ready"
    assert decision.outcome == OUTCOME_SELECTED


# --------------------------------------------------------------------------- #
# 4. NO_CAPABLE_MODEL outcome (explicit, never a wrong pick)
# --------------------------------------------------------------------------- #
def test_no_capable_model_outcome_is_explicit_and_serialisable():
    reg = StubRegistry([chat_only()])
    decision = ModelRouter(reg).select(TASK_VISION)
    assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL
    data = decision.to_dict()
    assert data["outcome"] == OUTCOME_NO_CAPABLE_MODEL
    assert data["model"] is None
    assert data["available"] is False
    assert data["required"] == [CAP_VISION]
    assert MODALITY_IMAGE in data["modalities"]
    assert data["reason"]


def test_no_capable_model_when_registry_is_empty():
    reg = StubRegistry([])
    for task in ALL_TASKS:
        decision = ModelRouter(reg).select(task)
        assert decision.model is None
        assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


def test_registry_failure_yields_registry_unavailable_not_a_crash():
    reg = StubRegistry([], error=RuntimeError("boom"))
    decision = ModelRouter(reg).select(TASK_CHAT)
    assert decision.model is None
    assert decision.outcome == OUTCOME_REGISTRY_UNAVAILABLE
    assert "registry unavailable" in decision.reason


def test_no_capable_model_reason_distinguishes_missing_capability_from_status():
    # Capability exists but the model is not available → reason names the status.
    pending = reasoning_model("reason-pending")
    pending.status = STATUS_UNAVAILABLE
    decision = ModelRouter(StubRegistry([pending])).select(TASK_REASONING)
    assert STATUS_UNAVAILABLE in decision.reason
    # Nothing in the whole (chat) category carries reasoning → generic reason.
    decision2 = ModelRouter(StubRegistry([chat_only()])).select(TASK_REASONING)
    assert "no model provides the required capability" in decision2.reason


# --------------------------------------------------------------------------- #
# 5. Fallback ordering & local preference
# --------------------------------------------------------------------------- #
def test_candidate_ordering_is_deterministic_and_preference_ranked():
    plain = chat_only("zeta-chat")
    coder = coding_model("alpha-code")
    reg = StubRegistry([plain, coder])
    router = ModelRouter(reg)
    first = router.select(TASK_CODING).candidates
    second = router.select(TASK_CODING).candidates
    assert first == second
    # The code-capable model wins the soft preference, so it sorts first.
    assert first[0] == "alpha-code"
    assert set(first) == {"alpha-code", "zeta-chat"}


def test_local_preference_breaks_ties_toward_local_models():
    remote = chat_only("a-remote", local=False)
    local = chat_only("b-local", local=True)
    reg = StubRegistry([remote, local])
    router = ModelRouter(reg)
    assert router.select(TASK_CHAT).model == "a-remote"  # alphabetical, no preference
    assert router.select(TASK_CHAT, prefer_local=True).model == "b-local"


def test_prefer_local_never_promotes_an_ineligible_model():
    """A local *chat-only* model must not win a vision task over a remote vision model."""
    local_chat = chat_only("local-chat", local=True)
    remote_vision = vision_model("remote-vision")
    reg = StubRegistry([local_chat, remote_vision])
    decision = ModelRouter(reg).select(TASK_VISION, prefer_local=True)
    assert decision.model == "remote-vision"


def test_candidates_helpers_respect_the_hard_gate():
    reg = StubRegistry([chat_only()])
    assert ModelRouter(reg).candidates(TASK_VISION) == []
    assert ModelRouter(reg).candidates(TASK_CHAT) == ["plain-chat"]


def test_exclude_removes_a_model_from_consideration():
    reg = StubRegistry([chat_only("only-chat")])
    decision = ModelRouter(reg).select(TASK_CHAT, exclude={"only-chat"})
    assert decision.model is None
    assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


# --------------------------------------------------------------------------- #
# 6. resolve() — explicit model must satisfy the same hard constraints
# --------------------------------------------------------------------------- #
def test_resolve_honours_an_explicit_available_capable_model():
    reg = StubRegistry([chat_only("plain"), vision_model("sees")])
    router = ModelRouter(reg)
    assert router.resolve(TASK_VISION, "sees") == "sees"


def test_resolve_rejects_an_explicit_model_missing_the_capability():
    reg = StubRegistry([chat_only("plain"), vision_model("sees")])
    # "plain" is AVAILABLE but cannot see → resolve must fall back to a capable one.
    assert ModelRouter(reg).resolve(TASK_VISION, "plain") == "sees"


def test_resolve_rejects_an_explicit_model_of_the_wrong_category():
    reg = StubRegistry([image_model("img"), chat_only("plain")])
    # Asking for chat but forcing an image model → not honoured, falls back.
    assert ModelRouter(reg).resolve(TASK_CHAT, "img") == "plain"


def test_resolve_returns_none_when_nothing_can_serve():
    reg = StubRegistry([chat_only("plain")])
    assert ModelRouter(reg).resolve(TASK_VISION, "plain") is None
    assert ModelRouter(reg).resolve(TASK_VISION, "does-not-exist") is None


def test_resolve_without_explicit_routes_by_task():
    reg = StubRegistry([chat_only("plain"), image_model("img")])
    assert ModelRouter(reg).resolve(TASK_IMAGE) == "img"


# --------------------------------------------------------------------------- #
# 7. Qwen3:4B remains the local, usable chat model
# --------------------------------------------------------------------------- #
def _qwen3_4b() -> StubModel:
    """Qwen3:4B as the registry would expose it: local, chat, reasoning, tools."""
    return StubModel(
        "qwen3:4b",
        [CAP_CHAT, CAP_STREAMING, CAP_REASONING, CAP_TOOLS, CAP_LONG_CONTEXT],
        kind=KIND_CHAT,
        provider="ollama",
        modality=[MODALITY_TEXT],
        local=True,
        context_length=131072,
    )


def test_qwen3_4b_is_routed_for_chat_and_reasoning():
    reg = StubRegistry([_qwen3_4b()])
    router = ModelRouter(reg)
    assert router.select(TASK_CHAT).model == "qwen3:4b"
    assert router.select(TASK_REASONING).model == "qwen3:4b"
    assert router.select(TASK_CHAT, prefer_local=True).model == "qwen3:4b"


def test_qwen3_4b_is_not_used_for_vision_or_image_or_video():
    """It is a text model — it must never be handed a multimodal task."""
    reg = StubRegistry([_qwen3_4b()])
    router = ModelRouter(reg)
    for task in (TASK_VISION, TASK_IMAGE, TASK_VIDEO, TASK_I2V, TASK_EMBEDDING):
        decision = router.select(task)
        assert decision.model is None, task
        assert decision.outcome == OUTCOME_NO_CAPABLE_MODEL


# --------------------------------------------------------------------------- #
# 8. Router performs no network I/O (reads the registry's cached probe only)
# --------------------------------------------------------------------------- #
def _counting_registry():
    from models.base import ChatMessage, Completion, ModelAdapter
    from models.registry import ModelRegistry

    class CountingAdapter(ModelAdapter):
        name = "openai_compatible"
        provider = "openai_compatible"

        def __init__(self) -> None:
            self.complete_calls = 0

        def is_configured(self) -> bool:
            return True

        def list_models(self) -> list[str]:
            return ["qwen3:4b", "qwen3-vl:8b"]

        def complete(self, messages: list[ChatMessage], model: str, **opts) -> Completion:
            self.complete_calls += 1
            return Completion(text="pong", model=model, provider=self.provider)

    adapter = CountingAdapter()
    reg = ModelRegistry(build_adapters=False)
    reg.register_adapter("openai_compatible", adapter)
    return reg, adapter


def test_routing_never_triggers_new_provider_calls():
    reg, adapter = _counting_registry()
    reg.refresh(force=True)  # one discovery + probe per listed model
    calls_after_discovery = adapter.complete_calls
    router = ModelRouter(reg)

    for task in ALL_TASKS:
        router.select(task)  # must reuse the cached probe; no new I/O

    assert adapter.complete_calls == calls_after_discovery
    # And the router itself added no probe side-effects on the adapters.
    assert reg.refresh(force=False)  # cached
    assert adapter.complete_calls == calls_after_discovery
