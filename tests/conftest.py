"""Shared pytest fixtures.

Tests run against an isolated SQLite database and a temporary workspace so no
production data or files are touched. The LLM provider is never required: tools
that need it degrade honestly (UNAVAILABLE) or use the labelled deterministic
composers, and the developer tool is exercised with real local execution.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="laiw-tests-"))
os.environ.setdefault("LAIW_DATA_DIR", str(_TMP / "data"))
os.environ.setdefault("LAIW_STORAGE_DIR", str(_TMP / "storage"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("LAIW_ENABLE_NETWORK_TOOLS", "false")


@pytest.fixture(scope="session", autouse=True)
def _fresh_db():
    from database.migrations import init_db

    init_db()
    yield


@pytest.fixture()
def ctx():
    from configs.settings import settings
    from database.models import new_id
    from models.registry import registry as model_registry
    from tools.base import ToolContext

    project_id = new_id("prj_test_")
    (Path(settings.projects_dir) / project_id).mkdir(parents=True, exist_ok=True)
    return ToolContext(project_id=project_id, user_id="usr_test", task_id=new_id("tsk_"), settings=settings, model_registry=model_registry)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def auth_client(client):
    import uuid

    email = f"user_{uuid.uuid4().hex[:8]}@test.local"
    resp = client.post("/api/auth/register", json={"email": email, "password": "password123", "display_name": "Tester"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    try:
        yield client
    finally:
        # The ``client`` fixture is session-scoped, so the auth header we injected
        # would otherwise leak into later unauthenticated tests (e.g. the auth
        # boundary tests). Remove it when this fixture is torn down.
        client.headers.pop("Authorization", None)
