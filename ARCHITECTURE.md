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

`ModelRegistry` (`models/registry.py`) states: `AVAILABLE / UNAVAILABLE /
MISCONFIGURED / DISABLED`. Because a provider can list models yet refuse
completions, `chat_available()` performs a real round-trip probe and caches the
verdict briefly. Availability is never assumed.

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
