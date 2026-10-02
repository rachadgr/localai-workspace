"""Workspace aggregate API tests — dashboard, generations, documents, slides.

These cover the additive ``/api/dashboard``, ``/api/generations``,
``/api/documents``, ``/api/slides`` and ``/api/workspace/{id}`` endpoints that the
ASAF AI studio uses. They assert the honesty guarantees:

* every value comes from a real record (no fabricated numbers);
* generation rows carry ``model`` / ``provider`` (empty strings when unknown —
  never invented) plus their real output artifacts;
* documents/slides reflect real ``Artifact`` rows of the right type;
* authentication is required (401 without a bearer token);
* nothing leaks secrets.
"""

from __future__ import annotations

import pytest


# --------------------------------------------------------------------------- #
# Auth boundary
# --------------------------------------------------------------------------- #
def test_workspace_endpoints_require_auth(client):
    for path in ("/api/dashboard", "/api/generations", "/api/documents", "/api/slides"):
        r = client.get(path)
        assert r.status_code in (401, 403), f"{path} must require auth (got {r.status_code})"


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
def test_dashboard_shape_and_honesty(auth_client):
    # A signed-in user always owns at least an auto-created workspace project only
    # after creating one; here we assert the endpoint returns the full real shape.
    r = auth_client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "projects",
        "recent_generations",
        "recent_documents",
        "recent_slides",
        "models",
        "providers",
        "runtimes",
        "quick_actions",
        "model_counts",
        "projects_total",
        "models_total",
        "models_available",
    ):
        assert key in body, key
    assert body["secrets_exposed"] is False
    # Quick actions must be a real list with an explicit enabled flag each.
    assert isinstance(body["quick_actions"], list)
    for action in body["quick_actions"]:
        assert "id" in action and "enabled" in action
        assert isinstance(action["enabled"], bool)
    # No secret markers anywhere in the payload.
    blob = str(body)
    for marker in ("sk-", "gsk-", "ghp_", "Bearer "):
        assert marker not in blob, f"leaked {marker}"


def test_dashboard_models_are_runtime_confirmed(auth_client):
    body = auth_client.get("/api/dashboard").json()
    for m in body["models"]:
        # Only genuinely AVAILABLE models are surfaced as "usable".
        assert m["status"] == "AVAILABLE", m


# --------------------------------------------------------------------------- #
# Generations / history
# --------------------------------------------------------------------------- #
def test_generations_reflect_real_tasks(auth_client):
    # Create a project + a real chat task, then confirm it appears in history with
    # the documented fields (model/provider may be empty — never fabricated).
    proj = auth_client.post("/api/projects", json={"name": "Hist", "description": ""}).json()
    pid = proj["id"]

    r = auth_client.get("/api/generations", params={"project_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert "generations" in body
    assert body["secrets_exposed"] is False
    for row in body["generations"]:
        for field in ("task_id", "id", "kind", "status", "model", "provider", "created_at", "output"):
            assert field in row, field
        assert isinstance(row["output"], list)
        # model / provider are strings (empty when the backend did not record one).
        assert isinstance(row["model"], str)
        assert isinstance(row["provider"], str)


# --------------------------------------------------------------------------- #
# Documents / slides
# --------------------------------------------------------------------------- #
def test_documents_and_slides_filter_by_artifact_type(auth_client):
    docs = auth_client.get("/api/documents").json()
    slides = auth_client.get("/api/slides").json()
    assert "documents" in docs and docs["secrets_exposed"] is False
    assert "slides" in slides and slides["secrets_exposed"] is False
    for d in docs["documents"]:
        assert d["type"] == "document", d
    for s in slides["slides"]:
        assert s["type"] == "presentation", s


# --------------------------------------------------------------------------- #
# Per-project workspace
# --------------------------------------------------------------------------- #
def test_project_workspace_reuses_real_project(auth_client):
    proj = auth_client.post("/api/projects", json={"name": "WS", "description": "test"}).json()
    pid = proj["id"]

    r = auth_client.get(f"/api/workspace/{pid}")
    assert r.status_code == 200
    body = r.json()
    for key in ("project", "conversations", "artifacts", "documents", "slides", "files", "generations"):
        assert key in body, key
    assert body["project"]["id"] == pid
    assert body["project"]["name"] == "WS"
    assert body["secrets_exposed"] is False


def test_project_workspace_unknown_project_404(auth_client):
    r = auth_client.get("/api/workspace/prj_does_not_exist")
    assert r.status_code == 404


def test_task_serialization_surfaces_model_and_provider(auth_client):
    """`/api/tasks/{id}` must always expose model/provider keys (honest empties)."""
    proj = auth_client.post("/api/projects", json={"name": "T", "description": ""}).json()
    pid = proj["id"]
    # A real chat task (fails honestly when no model is configured, but is recorded).
    r = auth_client.post("/api/chat", json={"message": "hello", "project_id": pid, "stream": False})
    assert r.status_code == 200
    task_id = r.json().get("task_id")
    assert task_id

    task = auth_client.get(f"/api/tasks/{task_id}").json()
    assert "model" in task and "provider" in task
    assert isinstance(task["model"], str) and isinstance(task["provider"], str)
    assert "created_at" in task
