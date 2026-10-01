"""ORM models and engine/session management for LocalAI Workspace.

Schema covers: users, projects, conversations, messages, tasks, task_steps,
tools, models, artifacts, files, memory, events, permissions.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from configs.settings import settings


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex[:20]
    return f"{prefix}{raw}" if prefix else raw


class Base(DeclarativeBase):
    pass


def _json_column() -> Any:
    return mapped_column(JSON, default=dict)


# --------------------------------------------------------------------------- #
# Core entities
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("usr_"))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(32), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prj_"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    settings_json: Mapped[dict] = _json_column()
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped["User"] = relationship(back_populates="projects")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cnv_"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="New conversation")
    mode: Mapped[str] = mapped_column(String(40), default="chat")  # chat | research | agent
    model: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped["Project"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("msg_"))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(24))  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[dict] = _json_column()
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tsk_"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(48), default="chat")
    title: Mapped[str] = mapped_column(String(300), default="")
    request: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", index=True)
    plan_json: Mapped[dict] = _json_column()
    result_json: Mapped[dict] = _json_column()
    error: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    steps: Mapped[list["TaskStep"]] = relationship(back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.index")


class TaskStep(Base):
    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("stp_"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200), default="")
    tool: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    input_json: Mapped[dict] = _json_column()
    output_json: Mapped[dict] = _json_column()
    error: Mapped[str] = mapped_column(Text, default="")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task"] = relationship(back_populates="steps")


class ToolRecord(Base):
    __tablename__ = "tools"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(48), default="general")
    availability: Mapped[str] = mapped_column(String(24), default="AVAILABLE")
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    input_schema: Mapped[dict] = _json_column()
    output_schema: Mapped[dict] = _json_column()
    cost_estimate: Mapped[str] = mapped_column(String(120), default="cheap")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ModelRecord(Base):
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32), default="chat")  # chat | embedding | image | search
    status: Mapped[str] = mapped_column(String(24), default="UNAVAILABLE")
    context_window: Mapped[int] = mapped_column(Integer, default=0)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("art_"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(48), default="file")
    mime_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="READY")
    storage_path: Mapped[str] = mapped_column(String(600), default="")
    meta_json: Mapped[dict] = _json_column()
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FileRecord(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fil_"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(48), default="uploads")
    path: Mapped[str] = mapped_column(String(600), default="")
    mime_type: Mapped[str] = mapped_column(String(120), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(80), default="")
    meta_json: Mapped[dict] = _json_column()
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryEntry(Base):
    __tablename__ = "memory"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mem_"))
    scope: Mapped[str] = mapped_column(String(32), default="project")  # session | project | user
    owner_id: Mapped[str] = mapped_column(String(64), index=True)  # project_id / user_id / conversation_id
    kind: Mapped[str] = mapped_column(String(48), default="note")
    key: Mapped[str] = mapped_column(String(200), default="")
    value: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[dict] = _json_column()
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_memory_scope_owner", "scope", "owner_id"),)


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("evt_"))
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(48), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    data_json: Mapped[dict] = _json_column()
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PermissionRecord(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prm_"))
    subject_type: Mapped[str] = mapped_column(String(32), default="user")
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(64), default="project")
    scope_id: Mapped[str] = mapped_column(String(64), default="")
    permission: Mapped[str] = mapped_column(String(32), default="READ")
    granted: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("subject_type", "subject_id", "scope", "scope_id", "permission", name="uq_permission"),)


# --------------------------------------------------------------------------- #
# Engine / session
# --------------------------------------------------------------------------- #
_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        url = settings.resolved_database_url
        kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(url, **kwargs)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Used by tests to swap databases."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
