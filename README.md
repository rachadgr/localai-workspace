# LocalAI Workspace

An independent, local AI workspace with a **Super Agent Orchestrator**. Accept a
natural-language request, understand intent, plan, auto-select tools, execute
multi-step tasks, validate results, and return ready-to-use artifacts — without
the user choosing tools manually.

This is a real, runnable system. Everything documented here was implemented and
verified. Where a capability genuinely cannot run in the current environment, the
system reports **UNAVAILABLE** instead of fabricating output.

---

## What actually works (verified)

| Capability | Status | Evidence |
|---|---|---|
| Super Agent Orchestrator (plan → route → execute → validate → recover → artifacts) | ✅ IMPLEMENTED/TESTED | `agents/orchestrator.py`, `tests/test_agent_api_security.py` |
| Tool Registry (10 tools) | ✅ | `tools/registry.py`, `/api/tools` |
| Model Provider system (unified adapters, discovery, real probing, router) | ✅ | `models/`, `/api/models`, `tests/test_models_provider.py` |
| Model Registry (provider probed, honest status, health caching) | ✅ | `models/registry.py`, `/api/models` |
| AI Docs → real `.md/.txt/.docx/.pdf` | ✅ | `tests/test_tools.py::test_docs_*` |
| AI Sheets → real `.csv/.xlsx` + stats + charts | ✅ | `tests/test_tools.py::test_sheets_*` |
| AI Slides → real `.pptx` (8–12 slides, notes) | ✅ | `tests/test_tools.py::test_slides_*` |
| AI Website Builder → responsive, accessible site + zip | ✅ | `tests/test_tools.py::test_website_*` |
| AI Developer → runs **real** tests in a sandbox | ✅ | `tests/test_tools.py::test_developer_*` |
| AI Search / Deep Research (cited report) | ⚠️ code complete; network egress is filtered in this sandbox → returns UNAVAILABLE | `tools/search_backends.py` |
| AI Image/Design (brief/prompt) | ✅ brief works; image **generation** returns UNAVAILABLE without a provider | `tools/image_tool.py` |
| AI Chat (streaming, history, context) | ⚠️ code complete; provider returned a billing notice in this sandbox → UNAVAILABLE | `models/adapters.py` |
| Files, Artifacts, Projects, Conversations, Memory, Jobs, Permissions, Observability | ✅ | `backend/app/routers/*` |
| Security (auth, RBAC, path traversal, upload limits, rate limit, redaction) | ✅ | `tests/test_agent_api_security.py` |

> **Honesty note.** During development this sandbox's LLM proxy returned HTTP 200
> with a *"credits can't be used with the Genspark API / LLM proxy"* notice. That
> is detected (`_guard_control_message`) and surfaced as `ModelUnavailable`, never
> as model output. To compensate, documents/decks/websites fall back to a
> **labelled deterministic composer** that only reorganises the user's own brief
> (no invented facts). Set `OPENAI_BASE_URL` / `OPENAI_API_KEY` to enable full
> LLM synthesis.

---

## Quick start

```bash
cp .env.example .env
pip install -e .

# initialise the database (SQLite by default) + demo login
python -m scripts.seed

# run the API + UI
python -m scripts.serve            # http://localhost:5060
```

Then register your own account from the sign-in screen (or, for automated
tests only, seed a local-only account — never use demo credentials in a public
deployment).

### With Docker

```bash
docker compose up --build
# API + UI on :5060, Postgres on :5432, Redis on :6379
```

---

## Layout

```
backend/     FastAPI app (routers, schemas, deps, core: security/errors/events/observability)
agents/      Super Agent: planner, router, executor(orchestrator), context, validator, recovery, memory
tools/       Tool registry + chat/search/research/docs/sheets/slides/developer/website/image/files
models/      Model Provider system: unified ModelAdapter interface, OpenAI-compatible /
             Anthropic / Ollama / echo adapters, ModelRegistry (discovery + real
             probing + health caching) and ModelRouter (task-based selection)
workers/     Job runtime (inline default, Celery optional) + sandboxed code execution
database/    SQLAlchemy models + migrations + seed
configs/     Settings (env-driven)
frontend/out Static workspace UI served by the API (no build step required)
tests/       unit / tools / agent / API / security / E2E
scripts/     serve, seed, smoke, validate
docker/      Dockerfile + compose assets
```

See `ARCHITECTURE.md`, `DEVELOPMENT.md`, `API.md`, `TOOLS.md`, `SECURITY.md`.

---

## Models & Providers

The model layer is provider-agnostic: the Super Agent asks for a **capability**,
never a provider name.

* **Unified interface** — `models/base.py::ModelAdapter` (chat, streaming, tools,
  vision, embeddings, image generation, video-ready). Unsupported operations raise
  honestly; nothing is fabricated.
* **Adapters** — `OpenAICompatibleAdapter`, `AnthropicAdapter`, `OllamaAdapter`
  (local), `EchoAdapter` (tests only, disabled by default).
* **Discovery + real probing** — `ModelRegistry` lists models, then performs a
  **real minimal request** before marking a model `AVAILABLE`. Listing a model is
  never treated as proof of usability. Health verdicts are cached
  (`LAIW_MODEL_HEALTH_TTL`).
* **Router** — `ModelRouter` maps tasks to models: `chat, code, document, vision,
  tools, reasoning, image, embedding, video`, excluding unavailable models with a
  deterministic fallback ordering.
* **API** — `GET /api/models`, `/api/models/providers`, `/api/models/router`,
  `POST /api/models/test-connection` (real request, redacted diagnostics).
* **UI** — open `/models.html` for the Models & Providers settings page (provider
  status, models, capabilities, health, routing, connection test). No key is ever
  shown.

Configuration is environment-only — see `.env.example` for `OPENAI_BASE_URL`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_BASE_URL` and optional
`LAIW_PROVIDER_<NAME>_URL/_KEY`. When no provider is configured the app keeps
running and reports `UNAVAILABLE` instead of failing.

---

## CLI

| Command | Purpose |
|---|---|
| `python -m scripts.seed` | migrate DB (+ demo user) |
| `python -m scripts.serve` | run API + UI |
| `python -m scripts.smoke` | API smoke test |
| `python -m scripts.validate` | full validation (deps, tests, artifact smoke) |
| `pytest` | test suite |

## License

Provided as-is for the user who commissioned it.
