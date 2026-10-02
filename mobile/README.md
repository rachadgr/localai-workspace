# ASAF AI — Android client

The **ASAF AI** mobile app: an AI Creation & Generation Studio client that talks
to a self-hosted [ASAF AI / LocalAI Workspace](../README.md) backend.

This is a **real** client — every model, provider, runtime and generation status
shown in the app comes from your backend. Nothing is hardcoded and nothing is
fabricated: unavailable capabilities are displayed as `UNAVAILABLE`,
`NOT_CONFIGURED`, `MISCONFIGURED`, etc., exactly as the backend reports them.

## Features

| Section | What it does |
|---|---|
| **Dashboard** | Live health, usable-model count, provider status, task-routing diagnostics |
| **Chat** | Streaming generation via `POST /api/chat` (SSE), model selector limited to models that pass the backend's hard "chat" gate |
| **Image** | `POST /api/images` brief / prompt / generate / variant, with honest unavailable states |
| **Video** | Experimental image-to-video runtime status + `POST /api/models/generation` |
| **Models** | Catalog merged with live runtime status; filter by category; per-model real health probe |
| **Providers** | Provider status, real connection test (`POST /api/models/test-connection`), runtime capability matrix |
| **History** | Real task records from `GET /api/tasks` with per-task detail |
| **Settings** | Server URL, session, backend settings view, sign out |

Authentication uses the backend's real JWT flow (`/api/auth/login`,
`/api/auth/register`, `/api/auth/me`); the bearer token is stored locally.

## Backend endpoints consumed

`/api/health`, `/api/version`, `/api/settings`, `/api/auth/*`, `/api/models`,
`/api/models/catalog`, `/api/models/providers`, `/api/models/router`,
`/api/models/runtimes`, `/api/models/provisioning`, `/api/models/local/activation`,
`/api/models/generation`, `/api/models/generation/status`,
`/api/models/generation/router`, `/api/models/test-connection`,
`/api/models/{id}`, `/api/models/{id}/health`, `/api/projects`, `/api/chat`,
`/api/images`, `/api/tasks`.

## Configuration

On the sign-in screen, set the **Server URL** to your backend:

* `http://10.0.2.2:5060` — the host machine from the Android emulator (default)
* `http://<your-lan-ip>:5060` — from a physical device on the same network
* `https://<your-host>` — a remote/tunnelled deployment

Cleartext HTTP is enabled (`usesCleartextTraffic="true"`) so local development
servers work out of the box.

## Build

```bash
cd mobile
flutter pub get
flutter build apk --release           # universal APK
flutter build apk --release --split-per-abi   # per-ABI APKs
```

Output: `build/app/outputs/flutter-apk/`.

The GitHub Actions workflow [`.github/workflows/build-apk.yml`](../.github/workflows/build-apk.yml)
builds the APK on every push touching `mobile/**`, on `v*` tags (attached to a
Release) and on manual dispatch.

## Run in development

```bash
cd mobile
flutter run            # on a connected device / emulator
flutter run -d chrome  # web preview (set the server URL + CORS accordingly)
flutter test           # unit + widget tests
```

## Tests

```bash
flutter analyze        # must be clean
flutter test
```

## Notes & honest limitations

* Absence of a GPU / model weights / a running provider is **not hidden**: the
  backend degrades gracefully and returns explicit states that the UI renders.
* The video section only runs when the backend has a genuinely wired generation
  runtime with local weights; otherwise it reports `NOT_CONFIGURED`.
* No API key, token or credential is ever displayed — the backend redacts them
  and the client only shows status/latency/redacted errors.
