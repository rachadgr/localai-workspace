#!/usr/bin/env python3
"""Development / production server entry point.

Serves the FastAPI application (and the built frontend when present) on a single
port so the whole workspace is reachable from one URL.

Usage:
    python -m scripts.serve            # defaults: 0.0.0.0:5060, reload in dev
    LAIW_PORT=8000 python -m scripts.serve
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    import uvicorn

    host = os.environ.get("LAIW_HOST", "0.0.0.0")
    port = int(os.environ.get("LAIW_PORT", "5060"))
    reload = os.environ.get("LAIW_RELOAD", "false").lower() == "true"

    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=os.environ.get("LAIW_LOG_LEVEL", "info").lower(),
        access_log=False,
        timeout_keep_alive=75,
    )


if __name__ == "__main__":
    main()
