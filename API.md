# API

Base path: `/api`. Auth: `Authorization: Bearer <jwt>` (except health/version and auth routes).

## System
- `GET /api/health` — overall status, model usability, tool counts
- `GET /api/version`
- `GET /api/models` — registry health (`chat_usable`, provider states, model list)
- `GET /api/tools` — tool catalog with schemas + availability
- `GET /api/settings` — non-secret configuration
- `GET /api/observability/events?limit=` — recent observations + live events

## Auth
- `POST /api/auth/register` `{email, password, display_name?}` → `{access_token, user}`
- `POST /api/auth/login` `{email, password}` → `{access_token, user}`
- `GET /api/auth/me`

## Projects & conversations
- `GET /api/projects` · `POST /api/projects` `{name, description?, settings?}`
- `GET /api/projects/{id}` · `PATCH /api/projects/{id}` · `DELETE /api/projects/{id}`
- `POST /api/projects/{id}/conversations`
- `GET /api/conversations/{id}/messages` · `DELETE /api/conversations/{id}`

## Chat & agent
- `POST /api/chat` `{message, project_id, conversation_id?, stream?, history?, model?}`
  → JSON, or `text/event-stream` when `stream: true` (`token` / `error` / `done` events)
- `POST /api/agent/run` `{request, project_id, conversation_id?, async_run?}` → orchestration result
- `POST /api/agent/plan` `{request, project_id}` → plan preview (no execution)
- `GET /api/tasks` · `GET /api/tasks/{id}` · `POST /api/tasks/{id}/cancel`
- `GET /api/tasks/{id}/events` — SSE progress stream (`heartbeat`, `task.status`, `task.plan`, `task.step`, `token`, `task.artifact`, `task.completed`, `task.failed`)

## Modules (each returns `{task_id, status, summary, response, data, artifacts, validation}`)
- `POST /api/search` `{query, limit?, fetch_pages?, summarize?, project_id}`
- `POST /api/research` `{question, max_sources?, produce_report?, project_id}`
- `POST /api/documents` `{title, prompt?, format: md|txt|docx|pdf, project_id}`
- `POST /api/spreadsheets` `{title, rows?|generate_sample?, sort?, filter?, aggregate?, formulas?, chart?, project_id}`
- `POST /api/slides` `{title, prompt?, target_slides: 8..12, theme?, project_id}`
- `POST /api/developer` `{task, language, files?, tests?, max_fix_attempts?, project_id}`
- `POST /api/websites` `{prompt, site_name?, pages?, style?, project_id}`
- `POST /api/images` `{description, action: brief|prompt|generate|variant, project_id}`

## Artifacts & files
- `GET /api/projects/{id}/artifacts?type=` · `GET /api/artifacts/{id}`
- `GET /api/artifacts/{id}/content` (download) · `GET /api/artifacts/{id}/preview` · `DELETE /api/artifacts/{id}`
- `GET /api/projects/{id}/files` · `POST /api/projects/{id}/files` (multipart) · `POST /api/projects/{id}/files/action`

## Memory & jobs
- `GET /api/projects/{id}/memory?scope=` · `POST /api/projects/{id}/memory` · `DELETE /api/memory/{id}`
- `GET /api/jobs` · `GET /api/jobs/{id}` · `DELETE /api/jobs/{id}`

Interactive docs: `/docs` (OpenAPI at `/openapi.json`).

## Error shape
```json
{ "error": "message", "class": "ToolError", "detail": "...", "retryable": false, "context": {} }
```
Status map: UserError→400, ValidationError→422, PermissionError→403, ModelUnavailable→503, NetworkError→502, ToolError→400, InternalError→500.
