# ARCHITECTURE

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│ frontend/  (static workspace UI served by FastAPI at "/")     │
└───────────────▲──────────────────────────────────────────────┘
                │  /api/*  (REST + SSE)
┌───────────────┴──────────────────────────────────────────────┐
│ backend/app   routers · schemas · deps · middleware · main    │
│   core: security · errors · events(SSE) · observability       │
└───────────────▲──────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────┐
│ agents/  Super Agent Orchestrator                             │
│   Planner → Router → Executor → Validator → Recovery →Memory  │
│   Context assembler (project · history · memory · artifacts)  │
└───────────────▲──────────────────────────────────────────────┘
                │
     ┌──────────┴───────────┐
┌────┴─────┐          ┌─────┴─────┐
│ tools/   │          │ models/   │
│ Registry │          │ Registry  │
│ 10 tools │          │ adapters  │
└────┬─────┘          └─────┬─────┘
     │                      │
┌────┴──────────────────────┴────┐   ┌──────────────────────┐
│ database/ (SQLAlchemy)         │   │ workers/ job runtime │
│ users projects conversations   │   │ + sandbox execution  │
│ messages tasks task_steps tools│   └──────────────────────┘
│ models artifacts files memory  │
│ events permissions migrations  │
└────────────────────────────────┘
```

## Orchestration flow

`USER REQUEST → INTENT → CONTEXT → PLAN → TOOL SELECTION → EXECUTION → OBSERVATION → VALIDATION → RECOVERY → ARTIFACTS → FINAL RESPONSE`

Every task persists `task_id, status, steps, artifacts, errors, started_at, completed_at`.

- **Planner** (`agents/planner.py`): intent detection (deterministic keyword signals first, optional LLM refinement) + step decomposition scoped to registered tools only.
- **Router** (`agents/router.py`): checks tool availability, binds previous-step outputs into current-step inputs (e.g. research → slides), chooses a declared fallback when a tool is unavailable.
- **Executor** (`agents/orchestrator.py`): runs each step through the Tool Registry; records `task_steps`; emits SSE events.
- **Validator** (`agents/validator.py`): tool `validate()` **plus** cross-cutting checks (artifacts exist & non-empty, summaries present). `UNAVAILABLE` is honest, not a failure.
- **Recovery** (`agents/recovery.py`): classifies errors into the 7 categories; retries only transient classes with bounded backoff; otherwise fails or falls back. No infinite loops.
- **Memory** (`agents/memory.py`): session/project/user scopes, task history, artifact refs; secrets redacted before persistence.
- **Context** (`agents/context.py`): project metadata, conversation history, memory block, recent artifacts/files.

## Tool contract

Each tool exposes `name, description, category, input_schema, output_schema,
permissions, cost_estimate, availability(), execute(), validate()`
(`tools/base.py`). Permissions use `READ/WRITE/EXECUTE/NETWORK/WEB/FILES/CODE/MODEL`.

## Model contract

The model layer is a **production-ready, extensible Model Provider system**
(`models/`). The Super Agent never hardcodes provider names.

- **Unified interface** — `models/base.py::ModelAdapter` defines one contract with
  chat, streaming, tool calling, vision, embeddings, image generation and
  (forward-looking) video generation. Unsupported operations raise
  `ModelUnavailableError`; they are never fabricated.
- **Provider adapters** (`models/adapters.py`):
  - `OpenAICompatibleAdapter` — any OpenAI-compatible HTTP API (the sandbox proxy,
    Groq, Together, vLLM, LM Studio, llama.cpp server…).
  - `AnthropicAdapter` — Anthropic Messages API.
  - `OllamaAdapter` — a local Ollama runtime (native `/api/tags` discovery + `/v1`
    chat/embeddings). Other local OpenAI-compatible servers attach the same way.
  - `EchoAdapter` — deterministic, offline, DISABLED unless `LAIW_ENABLE_ECHO_MODEL=true`.
- **Registry** (`models/registry.py::ModelRegistry`) — discovers models across all
  providers and probes each with a **real minimal request** before marking it
  `AVAILABLE`. States: `AVAILABLE / UNAVAILABLE / MISCONFIGURED / DISABLED /
  LOADING / ERROR`. Rich metadata per model: `id, name, provider, type,
  capabilities, context_length, vision, tools, streaming, local, endpoint, status,
  health, last_checked, error, config_source`. Health verdicts are **cached with a
  TTL** (`LAIW_MODEL_HEALTH_TTL`) so providers are not hammered. If no provider is
  configured the registry reports `UNAVAILABLE` and the app keeps running.
- **Router** (`models/router.py::ModelRouter`) — selects models by **task
  requirement**, not provider name: `chat→LLM`, `code→coding/tool-use`,
  `document→long-context LLM`, `vision→vision model`, `image→image model`,
  `embedding→embedding model`, `video→video model`. It excludes any model that is
  not `AVAILABLE` and applies a **deterministic fallback ordering**
  (capability score, then provider/id).

Provider configuration is environment-only (`.env.example`): `OPENAI_BASE_URL`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_BASE_URL`, and optional
`LAIW_PROVIDER_<NAME>_URL/_KEY` pairs. Secrets are never stored in the database,
never returned by the API and never rendered in the frontend.

## Storage

Project-scoped: `data/projects/<project_id>/{uploads,generated,research,documents,spreadsheets,presentations,code,website}`.
Artifacts carry `id, name, type, mime_type, size, project_id, created_at, source_task_id, status`.

## Database portability

`DATABASE_URL` → PostgreSQL (compose default). Blank → SQLite for zero-infra local
runs. Migrations (`database/migrations.py`) are ordered and idempotent on both.

## Jobs

`workers/runtime.py` provides a real lifecycle (`QUEUED/RUNNING/WAITING/COMPLETED/FAILED/CANCELLED`)
with progress and cancellation on an in-process pool. `workers/celery_app.py` is the
optional scale-out path (`LAIW_WORKER_MODE=celery` + `REDIS_URL`).
