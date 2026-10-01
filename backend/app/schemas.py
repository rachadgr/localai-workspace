"""Pydantic request/response schemas (contract for the public API)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("invalid email")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str


# --------------------------------------------------------------------------- #
# Projects / conversations
# --------------------------------------------------------------------------- #
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    settings: dict[str, Any] | None = None
    status: str | None = None


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=300)
    mode: Literal["chat", "research", "agent"] = "chat"
    model: str = Field(default="")


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
class HistoryItem(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100000)
    project_id: str
    conversation_id: str | None = None
    model: str = ""
    history: list[HistoryItem] = Field(default_factory=list)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=16, le=32000)


class ChatResponse(BaseModel):
    task_id: str
    conversation_id: str
    response: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


# --------------------------------------------------------------------------- #
# Agent / tasks
# --------------------------------------------------------------------------- #
class RunRequest(BaseModel):
    request: str = Field(min_length=1, max_length=100000)
    project_id: str
    conversation_id: str | None = None
    mode: Literal["auto", "chat", "research", "agent"] = "auto"
    async_run: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Module endpoints
# --------------------------------------------------------------------------- #
class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=20)
    fetch_pages: bool = True
    summarize: bool = True
    model: str = ""
    project_id: str


class ResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    max_sources: int = Field(default=12, ge=3, le=30)
    model: str = ""
    project_id: str
    produce_report: bool = True


class DocumentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    prompt: str = Field(default="", max_length=40000)
    format: Literal["md", "txt", "docx", "pdf"] = "md"
    author: str = ""
    subtitle: str = ""
    sections: list[dict[str, Any]] | None = None
    model: str = ""
    project_id: str


class SpreadsheetRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    columns: list[dict[str, Any]] | None = None
    rows: list[dict[str, Any]] | None = None
    generate_sample: bool = False
    sample_rows: int = Field(default=10, ge=1, le=500)
    sort: dict[str, Any] | None = None
    filter: dict[str, Any] | None = None
    aggregate: list[dict[str, Any]] | None = None
    formulas: list[dict[str, Any]] | None = None
    chart: dict[str, Any] | None = None
    model: str = ""
    project_id: str


class SlidesRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(default="", max_length=40000)
    subtitle: str = ""
    audience: str = ""
    target_slides: int = Field(default=10, ge=8, le=12)
    slides: list[dict[str, Any]] | None = None
    theme: Literal["default", "dark", "light"] = "default"
    model: str = ""
    project_id: str


class DeveloperRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20000)
    language: Literal["python", "node", "bash"] = "python"
    files: dict[str, str] | None = None
    tests: dict[str, str] | None = None
    run_tests: bool = True
    generate_tests: bool = True
    max_fix_attempts: int = Field(default=2, ge=0, le=5)
    timeout: float = Field(default=30, ge=1, le=120)
    model: str = ""
    project_id: str


class WebsiteRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=40000)
    site_name: str = Field(default="site", max_length=80)
    pages: list[str] = Field(default_factory=lambda: ["index"])
    style: str = ""
    model: str = ""
    project_id: str


class ImageRequest(BaseModel):
    description: str = Field(min_length=1, max_length=8000)
    action: Literal["brief", "prompt", "generate", "variant"] = "brief"
    style: str = ""
    aspect_ratio: str = "1:1"
    variants: int = Field(default=1, ge=1, le=4)
    base_image_url: str = ""
    model: str = ""
    project_id: str


class FilesActionRequest(BaseModel):
    project_id: str
    action: Literal["list", "read", "write", "delete", "stat"] = "list"
    path: str = ""
    content: str = ""
    category: str = "generated"


class MemoryWriteRequest(BaseModel):
    project_id: str
    scope: Literal["session", "project", "user"] = "project"
    kind: str = "note"
    key: str = Field(min_length=1, max_length=200)
    value: str = Field(max_length=20000)
