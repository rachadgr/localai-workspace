"""Agent + API + security + E2E tests."""

from __future__ import annotations

import os

from tools.registry import registry

registry.load_builtin_tools()


# --------------------------------------------------------------------------- #
# planner / router / orchestrator
# --------------------------------------------------------------------------- #
def test_planner_detects_intents():
    from agents.planner import Planner

    p = Planner(registry, None)
    assert p.detect_intent("Create a 10 slide deck about climate") == "slides"
    assert p.detect_intent("Build an Excel spreadsheet of sales") == "sheets"
    assert p.detect_intent("Do deep research on vector databases") == "research"
    assert p.detect_intent("Write a website landing page") == "website"
    assert p.detect_intent("hello there") == "chat"


def test_planner_deterministic_plan_has_steps():
    from agents.planner import Planner

    p = Planner(registry, None)
    plan = p.plan("Create a 10 slide presentation about AI", {"request": "x"})
    assert plan.steps and plan.steps[0].tool == "slides"


def test_orchestrator_produces_artifacts_end_to_end(ctx):
    from agents.orchestrator import SuperAgentOrchestrator
    from configs.settings import settings
    from database.models import Project, User, new_id, session_scope

    with session_scope() as db:
        user = User(id=new_id("usr_"), email=f"e2e_{new_id()}@test.local", display_name="E2E")
        db.add(user)
        db.flush()
        project = Project(id=ctx.project_id, user_id=user.id, name="E2E Project")
        db.add(project)

    orch = SuperAgentOrchestrator(tool_reg=registry)
    result = orch.run(request="Generate a 9 slide deck about renewable energy", project_id=ctx.project_id, user_id=user.id)
    assert result.task_id and result.started_at and result.completed_at
    assert result.status in ("COMPLETED", "FAILED")
    # slides must have produced a real deck
    assert any(a["name"].endswith(".pptx") for a in result.artifacts)
    for art in result.artifacts:
        assert os.path.exists(art["storage_path"])


# --------------------------------------------------------------------------- #
# API smoke
# --------------------------------------------------------------------------- #
def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "tools" in body and "models" in body


def test_auth_required_for_projects(client):
    r = client.get("/api/projects", headers={"Authorization": ""})
    assert r.status_code == 401


def test_register_login_and_project_crud(auth_client):
    r = auth_client.post("/api/projects", json={"name": "API Project", "description": "d"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert auth_client.get(f"/api/projects/{pid}").status_code == 200
    assert auth_client.patch(f"/api/projects/{pid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert any(p["id"] == pid for p in auth_client.get("/api/projects").json()["projects"])
    assert auth_client.post(f"/api/projects/{pid}/conversations", json={"title": "c"}).status_code == 201


def test_documents_endpoint_returns_artifact(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "Docs"}).json()["id"]
    r = auth_client.post("/api/documents", json={"title": "API Doc", "prompt": "brief about APIs", "format": "md", "project_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "SUCCESS"
    assert body["artifacts"]
    art_id = body["artifacts"][0]["id"]
    assert auth_client.get(f"/api/artifacts/{art_id}").status_code == 200
    assert auth_client.get(f"/api/artifacts/{art_id}/content").status_code == 200


def test_slides_and_spreadsheets_endpoints(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "Mods"}).json()["id"]
    s = auth_client.post("/api/slides", json={"title": "Deck", "prompt": "brief", "project_id": pid})
    assert s.json()["status"] == "SUCCESS" and s.json()["data"]["slide_count"] >= 8
    rows = [{"a": i, "b": i * 2} for i in range(5)]
    t = auth_client.post("/api/spreadsheets", json={"title": "Sheet", "rows": rows, "project_id": pid})
    assert t.json()["status"] == "SUCCESS"


def test_agent_plan_preview(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "Plan"}).json()["id"]
    r = auth_client.post("/api/agent/plan", json={"request": "Create a slide deck about X", "project_id": pid})
    assert r.status_code == 200
    assert r.json()["plan"]["steps"]


def test_tools_and_models_registry_endpoints(auth_client):
    assert "tools" in auth_client.get("/api/tools").json()
    assert "chat_usable" in auth_client.get("/api/models").json()


# --------------------------------------------------------------------------- #
# security
# --------------------------------------------------------------------------- #
def test_cross_project_access_is_denied(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "Private"}).json()["id"]
    # A second user must not read the first user's project.
    import uuid

    other = auth_client
    email = f"other_{uuid.uuid4().hex[:8]}@test.local"
    token = auth_client.post("/api/auth/register", json={"email": email, "password": "password123"}).json()["access_token"]
    r = other.get(f"/api/projects/{pid}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (403, 404)


def test_upload_rejects_dangerous_extension(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "Up"}).json()["id"]
    files = {"file": ("evil.exe", b"MZ...", "application/octet-stream")}
    r = auth_client.post(f"/api/projects/{pid}/files", files=files, data={"category": "uploads"})
    assert r.status_code == 400


def test_files_action_blocks_traversal(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "Sec"}).json()["id"]
    r = auth_client.post(f"/api/projects/{pid}/files/action", json={"project_id": pid, "action": "read", "path": "../../etc/passwd"})
    assert r.json()["status"] == "FAILED"


def test_settings_never_leak_secrets(auth_client):
    body = auth_client.get("/api/settings").json()
    for key, value in body.items():
        assert not (isinstance(value, str) and value.startswith(("sk-", "gsk-", "ghp_"))), key
    assert "llm_provider_configured" in body


# --------------------------------------------------------------------------- #
# E2E research → report → pptx smoke (offline-safe; real artifacts)
# --------------------------------------------------------------------------- #
def test_e2e_report_to_pptx_artifacts(auth_client):
    """End-to-end: produce a document and a deck from the same brief, verify files."""
    import zipfile

    pid = auth_client.post("/api/projects", json={"name": "E2E"}).json()["id"]
    brief = "Report on the impact of edge computing on IoT latency."

    doc = auth_client.post("/api/documents", json={"title": "Edge Report", "prompt": brief, "format": "docx", "project_id": pid}).json()
    assert doc["status"] == "SUCCESS"
    deck = auth_client.post("/api/slides", json={"title": "Edge Deck", "prompt": brief, "target_slides": 10, "project_id": pid}).json()
    assert deck["status"] == "SUCCESS"

    docx = next(a for a in doc["artifacts"] if a["name"].endswith(".docx"))
    pptx = next(a for a in deck["artifacts"] if a["name"].endswith(".pptx"))
    for art in (docx, pptx):
        content = auth_client.get(f"/api/artifacts/{art['id']}/content").content
        assert zipfile.is_zipfile(__import__("io").BytesIO(content))
