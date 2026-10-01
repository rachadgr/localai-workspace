"""Projects, conversations, files, artifacts and memory routes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.deps import get_current_user, require_project
from backend.app.schemas import ConversationCreate, FilesActionRequest, MemoryWriteRequest, ProjectCreate, ProjectUpdate
from configs.settings import settings
from database.models import (
    Artifact,
    Conversation,
    FileRecord,
    Message,
    PermissionRecord,
    Project,
    User,
    get_db,
    session_scope,
)
from agents.memory import memory_manager
from tools.files_tool import ingest_upload
from tools.registry import ToolContext

router = APIRouter()


# --------------------------------------------------------------------------- #
# projects
# --------------------------------------------------------------------------- #
@router.get("/projects", tags=["projects"])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    owned = db.execute(select(Project).where(Project.user_id == user.id).order_by(Project.updated_at.desc())).scalars().all()
    shared_ids = [
        p.scope_id
        for p in db.execute(
            select(PermissionRecord).where(
                PermissionRecord.subject_type == "user",
                PermissionRecord.subject_id == user.id,
                PermissionRecord.scope == "project",
                PermissionRecord.permission == "READ",
                PermissionRecord.granted.is_(True),
            )
        )
        .scalars()
        .all()
    ]
    shared = db.execute(select(Project).where(Project.id.in_(shared_ids))).scalars().all() if shared_ids else []

    def _ser(p: Project) -> dict[str, Any]:
        counts = {
            "conversations": db.query(Conversation).filter(Conversation.project_id == p.id).count(),
            "artifacts": db.query(Artifact).filter(Artifact.project_id == p.id).count(),
            "files": db.query(FileRecord).filter(FileRecord.project_id == p.id).count(),
        }
        return {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "status": p.status,
            "settings": p.settings_json,
            "created_at": p.created_at.isoformat() if p.created_at else "",
            "updated_at": p.updated_at.isoformat() if p.updated_at else "",
            "role": "owner" if p.user_id == user.id else "shared",
            "counts": counts,
        }

    return {"projects": [_ser(p) for p in owned], "shared": [_ser(p) for p in shared]}


@router.post("/projects", status_code=status.HTTP_201_CREATED, tags=["projects"])
def create_project(payload: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = Project(user_id=user.id, name=payload.name.strip(), description=payload.description, settings_json=payload.settings)
    db.add(project)
    db.flush()
    # Ensure the on-disk workspace exists with the canonical category layout.
    base = Path(settings.projects_dir) / project.id
    for category in ("uploads", "generated", "research", "documents", "spreadsheets", "presentations", "code", "website"):
        (base / category).mkdir(parents=True, exist_ok=True)
    conversation = Conversation(project_id=project.id, title="New conversation", mode="chat")
    db.add(conversation)
    db.flush()
    return {"id": project.id, "name": project.name, "description": project.description, "conversation_id": conversation.id}


@router.get("/projects/{project_id}", tags=["projects"])
def get_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_project(project_id, user, db, "READ")
    conversations = db.execute(select(Conversation).where(Conversation.project_id == project_id).order_by(Conversation.updated_at.desc())).scalars().all()
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "settings": project.settings_json,
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "updated_at": project.updated_at.isoformat() if project.updated_at else "",
        "conversations": [
            {"id": c.id, "title": c.title, "mode": c.mode, "model": c.model, "updated_at": c.updated_at.isoformat() if c.updated_at else ""}
            for c in conversations
        ],
        "memory": memory_manager.summary(project_id, user.id, ""),
    }


@router.patch("/projects/{project_id}", tags=["projects"])
def update_project(project_id: str, payload: ProjectUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_project(project_id, user, db)
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.settings is not None:
        project.settings_json = {**(project.settings_json or {}), **payload.settings}
    if payload.status is not None:
        project.status = payload.status
    db.flush()
    return {"id": project.id, "name": project.name, "description": project.description, "status": project.status}


@router.delete("/projects/{project_id}", tags=["projects"])
def delete_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_project(project_id, user, db)
    if project.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the owner can delete a project")
    db.delete(project)
    return {"deleted": project_id}


# --------------------------------------------------------------------------- #
# conversations & messages
# --------------------------------------------------------------------------- #
@router.post("/projects/{project_id}/conversations", status_code=201, tags=["conversations"])
def create_conversation(project_id: str, payload: ConversationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(project_id, user, db)
    convo = Conversation(project_id=project_id, title=payload.title, mode=payload.mode, model=payload.model)
    db.add(convo)
    db.flush()
    return {"id": convo.id, "title": convo.title, "mode": convo.mode}


@router.get("/conversations/{conversation_id}/messages", tags=["conversations"])
def list_messages(conversation_id: str, limit: int = Query(default=100, ge=1, le=500), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    require_project(convo.project_id, user, db, "READ")
    rows = db.execute(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc()).limit(limit)).scalars().all()
    return {
        "conversation_id": conversation_id,
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "meta": m.meta_json, "created_at": m.created_at.isoformat() if m.created_at else ""}
            for m in rows
        ],
    }


@router.delete("/conversations/{conversation_id}", tags=["conversations"])
def delete_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    require_project(convo.project_id, user, db)
    db.delete(convo)
    return {"deleted": conversation_id}


# --------------------------------------------------------------------------- #
# artifacts
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/artifacts", tags=["artifacts"])
def list_artifacts(project_id: str, type: str | None = None, limit: int = Query(default=100, ge=1, le=500), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(project_id, user, db, "READ")
    stmt = select(Artifact).where(Artifact.project_id == project_id)
    if type:
        stmt = stmt.where(Artifact.type == type)
    rows = db.execute(stmt.order_by(Artifact.created_at.desc()).limit(limit)).scalars().all()
    return {"artifacts": [_serialize_artifact(a) for a in rows]}


@router.get("/artifacts/{artifact_id}", tags=["artifacts"])
def get_artifact(artifact_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    artifact = _load_artifact(artifact_id, user, db)
    return _serialize_artifact(artifact)


@router.get("/artifacts/{artifact_id}/content", tags=["artifacts"])
def download_artifact(artifact_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    artifact = _load_artifact(artifact_id, user, db)
    path = Path(artifact.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing from storage")
    return FileResponse(path, media_type=artifact.mime_type or "application/octet-stream", filename=artifact.name)


@router.get("/artifacts/{artifact_id}/preview", tags=["artifacts"])
def preview_artifact(artifact_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Text-oriented preview for documents/code; metadata-only for binaries."""
    artifact = _load_artifact(artifact_id, user, db)
    path = Path(artifact.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")
    text_types = ("text/", "application/json", "application/xml", "image/svg")
    body: str | None = None
    if any(artifact.mime_type.startswith(t) for t in text_types):
        body = path.read_text(encoding="utf-8", errors="replace")[:200000]
    return {"id": artifact.id, "name": artifact.name, "mime_type": artifact.mime_type, "size": artifact.size, "text": body, "previewable": body is not None}


@router.delete("/artifacts/{artifact_id}", tags=["artifacts"])
def delete_artifact(artifact_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    artifact = _load_artifact(artifact_id, user, db)
    path = Path(artifact.storage_path)
    if path.exists() and str(path).startswith(str(Path(settings.storage_dir))):
        try:
            path.unlink()
        except OSError:
            pass
    db.delete(artifact)
    return {"deleted": artifact_id}


def _load_artifact(artifact_id: str, user: User, db: Session) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    require_project(artifact.project_id, user, db, "READ")
    return artifact


def _serialize_artifact(a: Artifact) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "type": a.type,
        "mime_type": a.mime_type,
        "size": a.size,
        "project_id": a.project_id,
        "task_id": a.task_id,
        "status": a.status,
        "created_at": a.created_at.isoformat() if a.created_at else "",
        "meta": a.meta_json or {},
        "download_url": f"/api/artifacts/{a.id}/content",
        "preview_url": f"/api/artifacts/{a.id}/preview",
    }


# --------------------------------------------------------------------------- #
# files
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/files", tags=["files"])
def list_files(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(project_id, user, db, "READ")
    rows = db.execute(select(FileRecord).where(FileRecord.project_id == project_id).order_by(FileRecord.created_at.desc())).scalars().all()
    return {
        "files": [
            {"id": f.id, "name": f.name, "category": f.category, "size": f.size, "mime_type": f.mime_type, "created_at": f.created_at.isoformat() if f.created_at else ""}
            for f in rows
        ]
    }


@router.post("/projects/{project_id}/files", status_code=201, tags=["files"])
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    category: str = Form(default="uploads"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project(project_id, user, db)
    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds the {settings.max_upload_mb} MB limit")
    from backend.app.core.security import sanitize_filename

    filename = sanitize_filename(file.filename or "upload.bin")
    ext = Path(filename).suffix.lower()
    blocked = {".exe", ".dll", ".so", ".bat", ".cmd", ".msi", ".sh", ".jar", ".scr", ".com"}
    if ext in blocked:
        raise HTTPException(status_code=400, detail=f"File type '{ext}' is not allowed")
    ctx = ToolContext(project_id=project_id, user_id=user.id, settings=settings)
    info = ingest_upload(ctx, filename, data, category)
    return info


@router.post("/projects/{project_id}/files/action", tags=["files"])
def files_action(project_id: str, payload: FilesActionRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(project_id, user, db)
    ctx = ToolContext(project_id=project_id, user_id=user.id, settings=settings)
    result = __import__("tools.registry", fromlist=["registry"]).registry.execute(
        "files", ctx, {"action": payload.action, "path": payload.path, "content": payload.content, "category": payload.category}
    )
    return result.to_dict()


# --------------------------------------------------------------------------- #
# memory
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/memory", tags=["memory"])
def get_memory(project_id: str, scope: str = "project", query: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(project_id, user, db, "READ")
    owner = {"project": project_id, "user": user.id, "session": project_id}.get(scope, project_id)
    items = memory_manager.recall(scope, owner, query=query)
    return {"scope": scope, "items": [i.to_dict() for i in items]}


@router.post("/projects/{project_id}/memory", status_code=201, tags=["memory"])
def write_memory(project_id: str, payload: MemoryWriteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(project_id, user, db)
    owner = {"project": project_id, "user": user.id, "session": project_id}.get(payload.scope, project_id)
    item = memory_manager.remember(payload.scope, owner, payload.kind, payload.key, payload.value)
    return item.to_dict()


@router.delete("/memory/{memory_id}", tags=["memory"])
def delete_memory(memory_id: str, user: User = Depends(get_current_user)) -> dict[str, Any]:
    ok = memory_manager.delete(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"deleted": memory_id}
