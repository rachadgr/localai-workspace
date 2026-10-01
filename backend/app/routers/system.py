"""Authentication, health, models, tools, observability and settings routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.security import create_access_token, hash_password, verify_password
from backend.app.core.observability import recent_observations
from backend.app.deps import get_current_user
from backend.app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from configs.settings import settings
from database.models import User, get_db, new_id
from models.registry import registry as model_registry
from tools.registry import registry as tool_registry

router = APIRouter()


# --------------------------------------------------------------------------- #
# health & meta
# --------------------------------------------------------------------------- #
@router.get("/health", tags=["system"])
def health() -> dict[str, Any]:
    tool_registry.load_builtin_tools()
    models_health = model_registry.health()
    tools = tool_registry.describe_all()
    available_tools = [t for t in tools if t["availability"] == "AVAILABLE"]
    return {
        "status": "ok" if models_health["chat_available"] > 0 else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "database": "postgresql" if settings.resolved_database_url.startswith("postgres") else "sqlite",
        "worker_mode": settings.worker_mode,
        "models": {"status": models_health["status"], "chat_available": models_health["chat_available"], "providers": models_health["providers"]},
        "tools": {"total": len(tools), "available": len(available_tools)},
        "network_tools": settings.enable_network_tools,
        "code_execution": settings.enable_code_execution,
        "image_provider": bool(settings.image_provider_url),
    }


@router.get("/version", tags=["system"])
def version() -> dict[str, str]:
    return {"app": settings.app_name, "version": settings.app_version}


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
@router.post("/auth/register", response_model=TokenResponse, tags=["auth"])
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if not settings.allow_registration:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled")
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        id=new_id("usr_"),
        email=payload.email,
        display_name=payload.display_name or payload.email.split("@")[0],
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    token = create_access_token(user.id, user.email, user.role)
    return TokenResponse(access_token=token, user={"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role})


@router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email.strip().lower()).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    token = create_access_token(user.id, user.email, user.role)
    return TokenResponse(access_token=token, user={"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role})


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role)


# --------------------------------------------------------------------------- #
# registries (read-only)
# --------------------------------------------------------------------------- #
@router.get("/models", tags=["registry"])
def list_models(_: User = Depends(get_current_user)) -> dict[str, Any]:
    return model_registry.health()


@router.get("/tools", tags=["registry"])
def list_tools(_: User = Depends(get_current_user)) -> dict[str, Any]:
    tool_registry.load_builtin_tools()
    return {"tools": tool_registry.describe_all(), "catalog": tool_registry.catalog()}


@router.get("/observability/events", tags=["system"])
def observability_events(limit: int = 100, _: User = Depends(get_current_user)) -> dict[str, Any]:
    from backend.app.core.events import bus

    return {"observations": recent_observations(limit), "events": bus.recent(limit)}


@router.get("/settings", tags=["system"])
def get_settings_view(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """Public, non-secret configuration (never exposes API keys)."""
    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "default_model": settings.llm_default_model,
        "network_tools": settings.enable_network_tools,
        "code_execution": settings.enable_code_execution,
        "image_provider_configured": bool(settings.image_provider_url),
        "max_upload_mb": settings.max_upload_mb,
        "worker_mode": settings.worker_mode,
        "llm_provider_configured": bool(settings.llm_base_url and settings.llm_api_key),
        "anthropic_configured": bool(settings.llm_anthropic_base_url and settings.llm_anthropic_api_key),
    }
