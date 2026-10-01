#!/usr/bin/env python3
"""API smoke test against a running server (or TestClient by default)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from database.migrations import init_db
    from fastapi.testclient import TestClient
    from backend.app.main import create_app

    init_db()
    failures: list[str] = []

    with TestClient(create_app()) as client:
        r = client.get("/api/health")
        print(f"health: {r.status_code} {r.json().get('status')}")
        if r.status_code != 200:
            failures.append("health")

        email = f"smoke_{__import__('uuid').uuid4().hex[:8]}@test.local"
        r = client.post("/api/auth/register", json={"email": email, "password": "password123"})
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"register: {r.status_code}")

        pid = client.post("/api/projects", json={"name": "Smoke"}, headers=headers).json()["id"]
        print(f"project: {pid}")

        for path, body in (
            ("/api/documents", {"title": "Smoke Doc", "prompt": "brief", "format": "pdf", "project_id": pid}),
            ("/api/slides", {"title": "Smoke Deck", "prompt": "brief", "project_id": pid}),
        ):
            r = client.post(path, json=body, headers=headers)
            ok = r.status_code == 200 and r.json().get("status") == "SUCCESS" and r.json().get("artifacts")
            print(f"{path}: {r.status_code} status={r.json().get('status')} artifacts={len(r.json().get('artifacts', []))}")
            if not ok:
                failures.append(path)

    print("\nSMOKE:", "PASS" if not failures else f"FAIL {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
