#!/usr/bin/env bash
# Start the ASAF AI / LocalAI Workspace backend (FastAPI + static UI) on :5060.
set -u
cd /home/user/localai-workspace
exec python -m scripts.serve
