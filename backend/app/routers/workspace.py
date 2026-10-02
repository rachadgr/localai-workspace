"""Workspace aggregate API — the real data the ASAF AI studio renders.

These are **aggregate, read-only** endpoints composed entirely from real records:

* generation history (``tasks``) enriched with the **model** / **provider** that
  actually served each task and any **output artifact** it produced;
* the authenticated **dashboard** (projects, recent generations, recent documents,
  recent slides, available models, runtime/provider health, quick actions);
* per-project **workspace** view (conversations, artifacts, files, tasks).

Honesty rules (shared with the rest of the workspace):

* every value comes from a real record — nothing is invented or hardcoded;
* a task's ``model`` / ``provider`` is only reported when the backend genuinely
  recorded it; otherwise it is the empty string (never a fabricated name);
* **no secrets** (API keys / tokens / endpoints) are ever returned.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import redact
from backend.app.deps import get_current_user, require_project
from database.models import (
    Artifact,
    Conversation,
    FileRecord,
    Project,
    Task,
    User,
    get_db,
)

router = APIRouter()

#: Task kinds that represent a *generation* action (as opposed to a chat turn).
_GENERATION_KINDS: frozenset[str] = frozenset(
    {
        "agent",
        "research",
        "search",
        "docs",
        "document",
        "sheets",
        "spreadsheet",
        "slides",
        "presentation",
        "developer",
        "website",
        "image",
        "video",
        "i2v",
    }
)

#: Artifact *types* (see ``tools/*_tool.py``) that classify an output.
_DOCUMENT_TYPES: frozenset[str] = frozenset({"document"})
_SLIDE_TYPES: frozenset[str] = frozenset({"presentation"})
_IMAGE_TYPES: frozenset[str] = frozenset({"image", "design"})
_VIDEO_TYPES: frozenset[str] = frozenset({"video"})


# --------------------------------------------------------------------------- #
# Task / artifact serialisation
# --------------------------------------------------------------------------- #
def _deep_find_model(obj: Any, *, _depth: int = 0) -> str:
    """Best-effort extraction of a model id from a nested result/plan blob.

    Returns the empty string when no genuine model id is present — it never
    invents one. Only small, bounded structures are inspected.
    """
    if _depth > 4 or obj is None:
        return ""
    if isinstance(obj, dict):
        for key in ("model", "model_id", "model_used"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in obj.values():
            found = _deep_find_model(value, _depth=_depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj[:20]:
            found = _deep_find_model(item, _depth=_depth + 1)
            if found:
                return found
    return ""


def _artifact_outputs(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact, download-linked view of a task's output artifacts."""
    out: list[dict[str, Any]] = []
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        aid = art.get("id") or ""
        out.append(
            {
                "id": aid,
                "name": art.get("name", ""),
                "type": art.get("type", ""),
                "mime_type": art.get("mime_type", ""),
                "size": art.get("size", 0),
                "download_url": f"/api/artifacts/{aid}/content" if aid else "",
                "preview_url": f"/api/artifacts/{aid}/preview" if aid else "",
            }
        )
    return out


def _task_view(task: Task, db: Session) -> dict[str, Any]:
    """A single generation-history row, enriched with model / provider / output."""
    result = task.result_json or {}
    plan = task.plan_json or {}
    artifacts = result.get("artifacts") if isinstance(result, dict) else None
    artifacts = artifacts if isinstance(artifacts, list) else []

    # Prefer the genuine recorded model; fall back to a bounded deep search of the
    # stored result/plan (still a real record — never fabricated).
    model = _deep_find_model(result) or _deep_find_model(plan)
    provider = ""
    if model:
        try:
            from models.registry import registry as model_registry

            info = model_registry.get(model)
            if info is not None:
                provider = info.provider
        except Exception:  # noqa: BLE001
            provider = ""

    # Real artifact rows attached to the task (authoritative, includes download path).
    rows = db.execute(select(Artifact).where(Artifact.task_id == task.id)).scalars().all()
    outputs = [
        {
            "id": a.id,
            "name": a.name,
            "type": a.type,
            "mime_type": a.mime_type,
            "size": a.size,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else "",
            "download_url": f"/api/artifacts/{a.id}/content",
            "preview_url": f"/api/artifacts/{a.id}/preview",
        }
        for a in rows
    ]
    if not outputs:
        outputs = _artifact_outputs(artifacts)

    started = task.started_at or task.created_at
    return {
        "task_id": task.id,
        "id": task.id,
        "project_id": task.project_id,
        "conversation_id": task.conversation_id,
        "kind": task.kind,
        "title": task.title,
        "status": task.status,
        "progress": task.progress,
        "model": model,
        "provider": provider,
        "is_generation": task.kind in _GENERATION_KINDS,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "started_at": started.isoformat() if started else "",
        "completed_at": task.completed_at.isoformat() if task.completed_at else "",
        "error": redact(task.error or ""),
        "summary": (result.get("summary") if isinstance(result, dict) else "") or "",
        "output": outputs,
        "output_count": len(outputs),
    }


def _artifact_view(a: Artifact) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "type": a.type,
        "mime_type": a.mime_type,
        "size": a.size,
        "status": a.status,
        "project_id": a.project_id,
        "task_id": a.task_id,
        "created_at": a.created_at.isoformat() if a.created_at else "",
        "meta": a.meta_json or {},
        "download_url": f"/api/artifacts/{a.id}/content",
        "preview_url": f"/api/artifacts/{a.id}/preview",
    }


def _owned_project_ids(db: Session, user: User) -> list[str]:
    return [
        p.id
        for p in db.execute(select(Project).where(Project.user_id == user.id)).scalars().all()
    ]


# --------------------------------------------------------------------------- #
# Generations / history
# --------------------------------------------------------------------------- #
@router.get("/generations", tags=["workspace"])
def list_generations(
    project_id: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Real generation history: id, task, model, provider, status, time, output.

    Covers chat + every generation module, so it doubles as the History screen's
    data source. ``model``/``provider`` reflect only what the backend genuinely
    recorded (empty when unknown).
    """
    if project_id:
        require_project(project_id, user, db, "READ")
        owned = [project_id]
    else:
        owned = _owned_project_ids(db, user)

    if not owned:
        return {"generations": [], "total": 0, "secrets_exposed": False}

    stmt = select(Task).where(Task.project_id.in_(owned))
    if kind:
        stmt = stmt.where(Task.kind == kind)
    rows = db.execute(stmt.order_by(Task.created_at.desc()).limit(limit)).scalars().all()
    gens = [_task_view(t, db) for t in rows]
    return {"generations": gens, "total": len(gens), "secrets_exposed": False}


# --------------------------------------------------------------------------- #
# Documents / slides
# --------------------------------------------------------------------------- #
def _artifact_gallery(
    db: Session,
    owned: list[str],
    types: frozenset[str],
    limit: int,
) -> list[dict[str, Any]]:
    if not owned:
        return []
    rows = (
        db.execute(
            select(Artifact)
            .where(Artifact.project_id.in_(owned), Artifact.type.in_(tuple(types)))
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_artifact_view(a) for a in rows]


@router.get("/documents", tags=["workspace"])
def list_documents(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Real generated **documents** (``Artifact.type == "document"``)."""
    if project_id:
        require_project(project_id, user, db, "READ")
        owned = [project_id]
    else:
        owned = _owned_project_ids(db, user)
    docs = _artifact_gallery(db, owned, _DOCUMENT_TYPES, limit)
    return {"documents": docs, "total": len(docs), "secrets_exposed": False}


@router.get("/slides", tags=["workspace"])
def list_slides(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Real generated **slide decks** (``Artifact.type == "presentation"``)."""
    if project_id:
        require_project(project_id, user, db, "READ")
        owned = [project_id]
    else:
        owned = _owned_project_ids(db, user)
    decks = _artifact_gallery(db, owned, _SLIDE_TYPES, limit)
    return {"slides": decks, "total": len(decks), "secrets_exposed": False}


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
def _task_counts(db: Session, owned: list[str]) -> dict[str, int]:
    if not owned:
        return {}
    rows = db.execute(select(Task.kind, Task.status).where(Task.project_id.in_(owned))).all()
    counts: dict[str, int] = {}
    for kind, status in rows:
        key = f"{kind}:{status}"
        counts[key] = counts.get(key, 0) + 1
    return counts


@router.get("/dashboard", tags=["workspace"])
def dashboard(
    limit: int = Query(default=8, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The authenticated **Dashboard** payload — every field from a real source.

    Sections: ``projects`` (recent), ``recent_generations``, ``recent_documents``,
    ``recent_slides``, ``models`` (runtime-confirmed availability), ``providers``
    (health), ``runtimes`` (capability matrix) and ``quick_actions`` (the real
    capabilities this deployment can serve right now). Additive and read-only:
    it never triggers a cloud round-trip of its own beyond the registry's cached
    discovery, downloads nothing and returns no secrets.
    """
    from models.registry import registry as model_registry

    owned = _owned_project_ids(db, user)

    # --- projects (recent) -------------------------------------------------- #
    projects_rows = (
        db.execute(
            select(Project)
            .where(Project.user_id == user.id)
            .order_by(Project.updated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    projects = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "status": p.status,
            "updated_at": p.updated_at.isoformat() if p.updated_at else "",
            "counts": {
                "conversations": db.query(Conversation).filter(Conversation.project_id == p.id).count(),
                "artifacts": db.query(Artifact).filter(Artifact.project_id == p.id).count(),
                "files": db.query(FileRecord).filter(FileRecord.project_id == p.id).count(),
            },
        }
        for p in projects_rows
    ]

    # --- recent generations ------------------------------------------------- #
    recent_gens: list[dict[str, Any]] = []
    if owned:
        gen_rows = (
            db.execute(
                select(Task)
                .where(Task.project_id.in_(owned))
                .order_by(Task.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        recent_gens = [_task_view(t, db) for t in gen_rows]

    # --- recent documents / slides ----------------------------------------- #
    recent_docs = _artifact_gallery(db, owned, _DOCUMENT_TYPES, limit)
    recent_slides = _artifact_gallery(db, owned, _SLIDE_TYPES, limit)

    # --- models (real runtime-confirmed availability) ---------------------- #
    catalog = model_registry.catalog()
    usable_models = [
        {
            "id": m.id,
            "name": m.name,
            "provider": m.provider,
            "kind": m.type,
            "status": m.status,
            "local": m.local,
            "runtime": m.runtime,
        }
        for m in catalog
        if m.status == "AVAILABLE"
    ]
    model_counts: dict[str, int] = {}
    for m in catalog:
        model_counts[m.status] = model_counts.get(m.status, 0) + 1

    # --- providers (health) ------------------------------------------------- #
    health = model_registry.health()
    providers = health.get("providers", {})

    # --- quick actions (capabilities really served) ------------------------ #
    runtime_probe = {"chat": "", "coding": "", "vision": "", "image": "", "video": ""}
    for task in ("chat", "coding", "vision", "image", "video"):
        try:
            decision = model_registry.route(task)
            runtime_probe[task] = decision.model or ""
        except Exception:  # noqa: BLE001
            runtime_probe[task] = ""
    quick_actions = [
        {"id": "chat", "label": "New chat", "enabled": bool(runtime_probe["chat"]), "model": runtime_probe["chat"]},
        {"id": "image", "label": "Generate image", "enabled": bool(runtime_probe["image"]), "model": runtime_probe["image"]},
        {"id": "video", "label": "Generate video", "enabled": bool(runtime_probe["video"]), "model": runtime_probe["video"]},
        {"id": "documents", "label": "Write document", "enabled": bool(runtime_probe["chat"]), "model": runtime_probe["chat"]},
        {"id": "slides", "label": "Build slides", "enabled": bool(runtime_probe["chat"]), "model": runtime_probe["chat"]},
        {"id": "project", "label": "New project", "enabled": True, "model": ""},
    ]

    return {
        "projects": projects,
        "projects_total": db.query(Project).filter(Project.user_id == user.id).count(),
        "recent_generations": recent_gens,
        "recent_documents": recent_docs,
        "recent_slides": recent_slides,
        "models": usable_models,
        "models_total": len(catalog),
        "models_available": len(usable_models),
        "model_counts": model_counts,
        "providers": providers,
        "runtimes": model_registry.runtimes(),
        "quick_actions": quick_actions,
        "task_counts": _task_counts(db, owned),
        "secrets_exposed": False,
    }


# --------------------------------------------------------------------------- #
# Per-project workspace
# --------------------------------------------------------------------------- #
@router.get("/workspace/{project_id}", tags=["workspace"])
def project_workspace(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Real workspace view of one project: conversations, artifacts, files, tasks.

    Reuses the existing project/conversation/artifact/file records — no duplicate
    storage, no fabricated entries.
    """
    project = require_project(project_id, user, db, "READ")

    conversations = (
        db.execute(
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .order_by(Conversation.updated_at.desc())
        )
        .scalars()
        .all()
    )
    artifacts = (
        db.execute(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    files = (
        db.execute(
            select(FileRecord)
            .where(FileRecord.project_id == project_id)
            .order_by(FileRecord.created_at.desc())
        )
        .scalars()
        .all()
    )
    tasks = (
        db.execute(
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(Task.created_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "created_at": project.created_at.isoformat() if project.created_at else "",
            "updated_at": project.updated_at.isoformat() if project.updated_at else "",
        },
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "mode": c.mode,
                "model": c.model,
                "updated_at": c.updated_at.isoformat() if c.updated_at else "",
            }
            for c in conversations
        ],
        "artifacts": [_artifact_view(a) for a in artifacts],
        "documents": [_artifact_view(a) for a in artifacts if a.type in _DOCUMENT_TYPES],
        "slides": [_artifact_view(a) for a in artifacts if a.type in _SLIDE_TYPES],
        "files": [
            {
                "id": f.id,
                "name": f.name,
                "category": f.category,
                "size": f.size,
                "mime_type": f.mime_type,
                "created_at": f.created_at.isoformat() if f.created_at else "",
            }
            for f in files
        ],
        "generations": [_task_view(t, db) for t in tasks],
        "secrets_exposed": False,
    }


__all__ = ["router"]
