# DEVELOPMENT

## Requirements
- Python ≥ 3.11 (3.13 tested), Node ≥ 18 (only for optional frontend tooling)
- No GPU, no external services required for the default configuration

## Setup
```bash
python -m pip install -e .          # or: pip install -r requirements.txt
cp .env.example .env
python -m scripts.seed              # migrate + demo user
python -m scripts.serve             # http://localhost:5060
```

## Commands
```bash
pytest -q                           # full suite
pytest tests/test_tools.py -q       # tools only
python -m scripts.validate          # deps + tests + artifact smoke + API smoke
python -m scripts.smoke             # API smoke only
```

## Configuration
All settings come from environment variables (see `.env.example`). Key ones:

| Var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `` (SQLite) | set to a Postgres DSN for production |
| `LAIW_WORKER_MODE` | `inline` | `celery` needs `REDIS_URL` |
| `LAIW_ENABLE_NETWORK_TOOLS` | `true` | gates search/research/image network calls |
| `LAIW_ENABLE_CODE_EXECUTION` | `true` | gates sandboxed execution |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | from environment | any OpenAI-compatible endpoint |
| `LAIW_IMAGE_PROVIDER_URL` | `` | image generation; empty → UNAVAILABLE |

## Conventions
- No fabricated outputs: unavailable capabilities return `UNAVAILABLE`.
- Errors carry an `ErrorClass` (User/Tool/ModelUnavailable/Network/Validation/Permission/Internal).
- Secrets are redacted by `backend/app/core/security.py::redact` before logging/persisting.
- New tools: subclass `tools.base.BaseTool`, decorate with `@register`.

## Database migrations
`database/migrations.py` applies ordered, idempotent steps recorded in
`schema_migrations`. Add a `(version, description, callable)` tuple to `MIGRATIONS`.

## Docker
```bash
docker compose up --build           # api + postgres + redis
docker compose run --rm api python -m scripts.seed
```

## Troubleshooting
- **`/api/models` says UNAVAILABLE**: expected when the provider refuses completions
  (billing/quota). Point `OPENAI_BASE_URL`/`OPENAI_API_KEY` at a working endpoint.
- **search returns UNAVAILABLE**: this sandbox filters outbound web traffic; run
  where egress is permitted.
