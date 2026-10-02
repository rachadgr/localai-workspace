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

The backend URL is resolved in this order — **it is never hardcoded**:

1. a value the user saved in the app (**Settings → Server URL** / the sign-in field), or
2. the compile-time default baked in with `--dart-define=ASAF_API_BASE_URL=<url>`, or
3. a **development-only** loopback fallback (`10.0.2.2:5060` on the Android
   emulator, `localhost:5060` elsewhere).

So a new (temporary) tunnel URL can be supplied without touching the source:

```bash
# Bake it in at build time:
flutter build apk --release --dart-define=ASAF_API_BASE_URL=https://<tunnel>.trycloudflare.com

# …or type it into the app's Server URL field at runtime.
```

Common values:

* `https://<tunnel>.trycloudflare.com` — the public HTTPS **tunnel URL** (use this
  for a backend running on Kaggle/Colab; the phone cannot reach a notebook directly)
* `http://<your-lan-ip>:5060` — a physical device on the same Wi-Fi as the host
* `http://10.0.2.2:5060` — **Android emulator only** (host loopback alias)

The sign-in screen includes a **Test connection** button that probes
`/api/health` and reports reachability. Cleartext HTTP stays enabled
(`usesCleartextTraffic="true"`) so local/LAN servers work; public tunnels are HTTPS.

### Bring your own backend (Kaggle / Colab)

Start the API (`0.0.0.0:5060`), then expose it with a public HTTPS tunnel and
pass the URL to the app:

```bash
# 1) backend (from the repo root)
python -m scripts.serve                 # binds 0.0.0.0:5060

# 2) public HTTPS tunnel (cloudflared) — prints the URL + the exact build command
python -m scripts.tunnel --print-build
```

The JWT is stored in **secure storage** (`flutter_secure_storage`), never in
plaintext preferences; only the non-secret server URL is kept in `SharedPreferences`.

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
