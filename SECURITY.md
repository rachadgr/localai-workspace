# SECURITY

## Authentication & authorisation
- Passwords hashed with **bcrypt** (cost 12) — never stored or logged in clear.
- Access tokens: **JWT HS256**, signed with a per-installation secret
  (`LAIW_JWT_SECRET`, or auto-generated and written to `data/.jwt_secret` with `0600`).
- Every project route enforces ownership or an explicit `permissions` grant
  (`READ`/`WRITE`) via `require_project()`; cross-project access returns 403/404.

## Input validation
- All request bodies validated by **Pydantic** schemas (`backend/app/schemas.py`)
  with length bounds and enums. Invalid input → 422.
- File uploads restricted by size (`LAIW_MAX_UPLOAD_MB`, default 25 MB) and a
  blocklist of executable extensions (`.exe .dll .so .bat .cmd .msi .sh .jar .scr .com`).

## Path traversal
- `safe_join()` resolves every relative component and rejects anything escaping
  the project workspace. Verified by unit + API tests.
- Artifact deletion only removes files inside `storage/`.

## Sandboxed code execution
- `workers/sandbox.py` runs only allow-listed interpreters (`python -I`, node, bash, sh),
  never `shell=True`, with a scrubbed environment (secrets removed), a hard
  wall-clock timeout, output caps and a token blocklist.
- Host filesystem access is confined to a per-invocation temp directory under the
  project workspace; no arbitrary host paths are exposed through the API.

## Secret protection
- API keys live only in the backend process environment; `/api/settings` exposes
  booleans (`llm_provider_configured`, `image_provider_configured`), never values.
- `redact()` scrubs token-like strings from logs, events and persisted memory.
- `.env` is git-ignored; `.env.example` contains no real credentials.

## Project isolation
- Files/artifacts are stored under `data/projects/<project_id>/…` and queries are
  scoped by `project_id` with an ownership check.

## Rate limiting & headers
- Sliding-window limiter per client IP (`LAIW_RATE_LIMIT`, default 240/min) →
  429 with `retry_after`.
- Response headers: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: SAMEORIGIN`, plus per-request `x-request-id`.

## Reporting
This is a local workspace intended for a single trusted operator. Before exposing
it publicly, set a strong `LAIW_JWT_SECRET`, restrict `LAIW_CORS_ORIGINS`, disable
`LAIW_ALLOW_REGISTRATION`, and front it with TLS. Never enable
`LAIW_ENABLE_ECHO_MODEL` in production (it is a deterministic test adapter only).
