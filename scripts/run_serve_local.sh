#!/usr/bin/env bash
# Runtime launcher for the ASAF AI backend (Kaggle/local).
# Reads runtime config from the environment; never hardcodes secrets.
set -u
cd /home/user/localai-workspace
export LAIW_HOST="${LAIW_HOST:-0.0.0.0}"
export LAIW_PORT="${LAIW_PORT:-5060}"
export LAIW_ALLOW_REGISTRATION="${LAIW_ALLOW_REGISTRATION:-true}"
export LOCALAI_BASE_URL="${LOCALAI_BASE_URL:-http://127.0.0.1:8080}"
export LAIW_DISABLE_CLOUD_PROVIDERS="${LAIW_DISABLE_CLOUD_PROVIDERS:-true}"
exec python3 -m scripts.serve
