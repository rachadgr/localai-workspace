#!/usr/bin/env python3
"""Expose the ASAF AI backend (FastAPI on :5060) through a public HTTPS tunnel.

Designed for hosted notebooks (Kaggle / Colab) where the phone cannot reach the
notebook directly. It prefers **cloudflared** (a free, no-account quick tunnel
that yields a `https://<name>.trycloudflare.com` URL).

Usage:
    python -m scripts.tunnel                 # start + print URL, keep running
    python -m scripts.tunnel --port 5060
    python -m scripts.tunnel --print-build   # also print the flutter build cmd

The URL is written to `.tunnel_url` in the repo root so other tooling (and the
`--print-build` helper) can pick it up. The tunnel URL is **temporary**: never
commit it and never hardcode it — pass it to the app at build time with
`--dart-define=ASAF_API_BASE_URL=$URL`, or type it in the app's Server URL field.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

# Candidate locations for the cloudflared binary (PATH first, then common spots).
_BIN_CANDIDATES = [
    "cloudflared",
    str(Path.home() / "cloudflared"),
    "/usr/local/bin/cloudflared",
    "/usr/bin/cloudflared",
    str(ROOT / "bin" / "cloudflared"),
]


def _find_cloudflared() -> str | None:
    for cand in _BIN_CANDIDATES:
        found = shutil.which(cand) if "/" not in cand else (cand if Path(cand).exists() else None)
        if found:
            return found
    return None


def _install_hint() -> str:
    return (
        "cloudflared not found.\n"
        "  Linux : curl -L -o cloudflared "
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 "
        "&& chmod +x cloudflared\n"
        "  Colab : !curl -L -o cloudflared "
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 "
        "&& chmod +x cloudflared\n"
        "  macOS : brew install cloudflared"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Expose the ASAF AI backend via a public HTTPS tunnel.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LAIW_PORT", "5060")))
    parser.add_argument("--timeout", type=int, default=45, help="seconds to wait for the public URL")
    parser.add_argument("--print-build", action="store_true", help="print the flutter --dart-define build command")
    args = parser.parse_args()

    binary = _find_cloudflared()
    if not binary:
        print(_install_hint(), file=sys.stderr)
        return 2

    target = f"http://localhost:{args.port}"
    print(f"Starting cloudflared quick tunnel -> {target}", file=sys.stderr)

    proc = subprocess.Popen(
        [binary, "tunnel", "--url", target, "--no-autoupdate", "--protocol", "http2"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    url: str | None = None
    deadline = time.time() + args.timeout
    assert proc.stdout is not None
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        match = _URL_RE.search(line)
        if match:
            url = match.group(0)
            break

    if not url:
        proc.terminate()
        print("Failed to obtain a public URL within the timeout.", file=sys.stderr)
        return 1

    (ROOT / ".tunnel_url").write_text(url + "\n", encoding="utf-8")
    print(f"\n✅ Public URL: {url}\n", file=sys.stderr)
    print(f"   Phone Server URL  ->  {url}")
    print(f"   Health check      ->  {url}/api/health")
    if args.print_build:
        print(
            "\n   Build the Android APK against this URL:\n"
            f"   cd mobile && flutter build apk --release "
            f"--dart-define=ASAF_API_BASE_URL={url}\n"
        )

    # Stream the tunnel log to stdout so the process stays in the foreground.
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
