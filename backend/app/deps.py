"""FastAPI dependencies: DB session, current user, project authorisation."""

from __future__ import annotations

from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.security import decode_access_token
from database.models import PermissionRecord, Project, User, get_db, session_scope


def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.get(User, payload.get("sub", ""))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def get_optional_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User | None:
    if not authorization:
        return None
    try:
        return get_current_user(authorization, db)
    except HTTPException:
        return None


def require_project(project_id: str, user: User, db: Session, permission: str = "WRITE") -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found")
    if project.user_id == user.id or user.role == "admin":
        return project
    granted = (
        db.query(PermissionRecord)
        .filter(
            PermissionRecord.subject_type == "user",
            PermissionRecord.subject_id == user.id,
            PermissionRecord.scope == "project",
            PermissionRecord.scope_id == project_id,
            PermissionRecord.permission == permission,
            PermissionRecord.granted.is_(True),
        )
        .first()
    )
    if granted is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this project")
    return project


def project_dependency(permission: str = "WRITE"):
    def _dep(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Project:
        return require_project(project_id, user, db, permission)

    return _dep
