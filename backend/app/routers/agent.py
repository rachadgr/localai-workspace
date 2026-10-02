"""Chat, tasks (agent/super-agent), SSE events and all module endpoints."""

from __future__ import annotations

import json
import threading
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.orchestrator import orchestrator
from backend.app.core.events import bus
from backend.app.deps import get_current_user, require_project
from backend.app.schemas import (
    ChatRequest,
    ChatResponse,
    DeveloperRequest,
    DocumentRequest,
    ImageRequest,
    ResearchRequest,
    RunRequest,
    SearchRequest,
    SlidesRequest,
    SpreadsheetRequest,
    WebsiteRequest,
)
from configs.settings import settings
from database.models import Conversation, Message, Task, TaskStep, User, get_db, new_id, session_scope
from models.registry import registry as model_registry
from tools.base import ToolContext
from tools.registry import registry as tool_registry
from workers.runtime import Stage, job_manager

router = APIRouter()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _tool_context(project_id: str, user: User, task_id: str = "", conversation_id: str = "") -> ToolContext:
    return ToolContext(
        project_id=project_id,
        user_id=user.id,
        task_id=task_id,
        conversation_id=conversation_id,
        settings=settings,
        model_registry=model_registry,
    )


def _ensure_conversation(db: Session, project_id: str, conversation_id: str | None, title: str, mode: str = "chat") -> str:
    if conversation_id:
        convo = db.get(Conversation, conversation_id)
        if convo is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return convo.id
    convo = Conversation(project_id=project_id, title=title[:120] or "New conversation", mode=mode)
    db.add(convo)
    db.flush()
    return convo.id


def _persist_user_message(db: Session, conversation_id: str, content: str, meta: dict | None = None) -> None:
    db.add(Message(conversation_id=conversation_id, role="user", content=content, meta_json=meta or {}))


def _run_tool_endpoint(tool_name: str, payload: dict[str, Any], project_id: str, user: User):
    """Execute a single tool synchronously with a task record for traceability."""
    task_id = new_id("tsk_")
    with session_scope() as db:
        db.add(Task(id=task_id, project_id=project_id, kind=tool_name, title=str(payload.get("title") or payload.get("query") or payload.get("request") or tool_name)[:200], request=json.dumps(payload)[:4000], status="RUNNING"))
    ctx = _tool_context(project_id, user, task_id=task_id)
    result = tool_registry.execute(tool_name, ctx, payload)
    validation = tool_registry.validate(tool_name, ctx, result)
    with session_scope() as db:
        row = db.get(Task, task_id)
        if row is not None:
            row.status = "COMPLETED" if result.status == "SUCCESS" else ("FAILED" if result.status == "FAILED" else "COMPLETED")
            row.completed_at = __import__("database.models", fromlist=["utcnow"]).utcnow()
            row.progress = 1.0
            row.result_json = {"result": result.to_dict(), "validation": validation.to_dict()}
            row.error = result.error
    return result, validation, task_id


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
@router.post("/chat", tags=["chat"])
def chat(payload: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = require_project(payload.project_id, user, db)
    conversation_id = _ensure_conversation(db, project.id, payload.conversation_id, payload.message[:80], "chat")
    _persist_user_message(db, conversation_id, payload.message)
    db.commit()

    history = [h.model_dump() for h in payload.history] if payload.history else []
    if not history:
        rows = db.execute(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).limit(20)).scalars().all()
        history = [{"role": m.role, "content": m.content} for m in reversed(rows) if m.role in ("user", "assistant")]

    task_id = new_id("tsk_")
    with session_scope() as db2:
        db2.add(Task(id=task_id, project_id=project.id, conversation_id=conversation_id, kind="chat", title=payload.message[:200], request=payload.message, status="RUNNING"))

    ctx = _tool_context(project.id, user, task_id=task_id, conversation_id=conversation_id)
    tool_input = {"message": payload.message, "history": history[:-1] if history and history[-1]["content"] == payload.message else history}
    if payload.model:
        tool_input["model"] = payload.model
    if payload.temperature is not None:
        tool_input["temperature"] = payload.temperature
    if payload.max_tokens is not None:
        tool_input["max_tokens"] = payload.max_tokens

    if payload.stream:
        def _gen():
            model = payload.model or _safe_default_model()
            registry = model_registry
            messages = [{"role": "system", "content": "You are LocalAI Workspace, a precise, honest assistant. If unsure or lacking data, say so explicitly."}]
            messages += tool_input["history"]
            messages.append({"role": "user", "content": payload.message})
            collected: list[str] = []
            try:
                from models.adapters import ChatMessage

                for chunk in registry.stream([ChatMessage(**m) for m in messages], model=model):
                    collected.append(chunk)
                    yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
            except Exception as exc:  # noqa: BLE001
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            text = "".join(collected)
            with session_scope() as db3:
                db3.add(Message(conversation_id=conversation_id, role="assistant", content=text, meta_json={"task_id": task_id, "model": model}))
                row = db3.get(Task, task_id)
                if row is not None:
                    row.status = "COMPLETED" if text else "FAILED"
                    row.completed_at = __import__("database.models", fromlist=["utcnow"]).utcnow()
            yield f"data: {json.dumps({'type': 'done', 'task_id': task_id, 'conversation_id': conversation_id, 'model': model})}\n\n"

        return StreamingResponse(_gen(), media_type="text/event-stream")

    result = tool_registry.execute("chat", ctx, tool_input)
    text = result.data.get("text", "") if result.status == "SUCCESS" else result.summary
    with session_scope() as db3:
        db3.add(Message(conversation_id=conversation_id, role="assistant", content=text, meta_json={"task_id": task_id, "status": result.status}))
        row = db3.get(Task, task_id)
        if row is not None:
            row.status = "COMPLETED" if result.status == "SUCCESS" else "FAILED"
            row.completed_at = __import__("database.models", fromlist=["utcnow"]).utcnow()
            row.result_json = result.to_dict()

    if result.status != "SUCCESS":
        return {"task_id": task_id, "conversation_id": conversation_id, "response": result.summary, "status": result.status, "model": "", "tokens_in": 0, "tokens_out": 0}

    return ChatResponse(
        task_id=task_id,
        conversation_id=conversation_id,
        response=text,
        model=result.data.get("model", ""),
        tokens_in=result.data.get("tokens_in", 0),
        tokens_out=result.data.get("tokens_out", 0),
    )


def _safe_default_model() -> str:
    try:
        return model_registry.default_chat_model()
    except Exception:  # noqa: BLE001
        return ""


# --------------------------------------------------------------------------- #
# agent / tasks
# --------------------------------------------------------------------------- #
@router.post("/agent/run", tags=["agent"])
def run_agent(payload: RunRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = require_project(payload.project_id, user, db)
    conversation_id = _ensure_conversation(db, project.id, payload.conversation_id, payload.request[:80], "agent")
    _persist_user_message(db, conversation_id, payload.request)
    db.commit()

    if payload.async_run:
        task_id = new_id("tsk_")

        def _job(job, cancel_event):
            return orchestrator.run(
                request=payload.request,
                project_id=project.id,
                user_id=user.id,
                conversation_id=conversation_id,
                task_id=task_id,
                cancel_event=cancel_event,
                extra_context=payload.extra,
                persist_assistant_message=True,
            ).to_dict()

        job = job_manager.submit(task_id, "agent", _job)
        return {"task_id": task_id, "job_id": job.id, "status": job.status.value, "conversation_id": conversation_id, "async": True}

    result = orchestrator.run(
        request=payload.request,
        project_id=project.id,
        user_id=user.id,
        conversation_id=conversation_id,
        extra_context=payload.extra,
        persist_assistant_message=True,
    )
    return result.to_dict()


@router.get("/tasks", tags=["tasks"])
def list_tasks(project_id: str | None = None, limit: int = Query(default=50, ge=1, le=200), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if project_id:
        require_project(project_id, user, db, "READ")
        stmt = select(Task).where(Task.project_id == project_id)
    else:
        owned = [p.id for p in db.execute(select(__import__("database.models", fromlist=["Project"]).Project).where(__import__("database.models", fromlist=["Project"]).Project.user_id == user.id)).scalars().all()]
        stmt = select(Task).where(Task.project_id.in_(owned))
    rows = db.execute(stmt.order_by(Task.created_at.desc()).limit(limit)).scalars().all()
    return {"tasks": [_serialize_task(t, include_steps=False) for t in rows]}


@router.get("/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project(task.project_id, user, db, "READ")
    return _serialize_task(task, include_steps=True)


@router.get("/tasks/{task_id}/events", tags=["tasks"])
async def task_events(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project(task.project_id, user, db, "READ")

    async def _stream() -> AsyncIterator[str]:
        async for item in bus.subscribe(task_id, replay=True):
            yield f"data: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/tasks/{task_id}/cancel", tags=["tasks"])
def cancel_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project(task.project_id, user, db)
    cancelled = job_manager.cancel(task_id)
    if not cancelled:
        task.status = "CANCELLED"
        db.flush()
    return {"task_id": task_id, "cancelled": True}


def _serialize_task(task: Task, include_steps: bool = True) -> dict[str, Any]:
    steps = []
    if include_steps:
        with session_scope() as db:
            rows = db.execute(select(TaskStep).where(TaskStep.task_id == task.id).order_by(TaskStep.index.asc())).scalars().all()
            steps = [
                {
                    "id": s.id,
                    "index": s.index,
                    "name": s.name,
                    "tool": s.tool,
                    "status": s.status,
                    "summary": (s.output_json or {}).get("summary", ""),
                    "artifacts": (s.output_json or {}).get("artifacts", []),
                    "validation": (s.output_json or {}).get("validation", {}),
                    "error": s.error,
                }
                for s in rows
            ]
    # Surface the model/provider that genuinely served this task (never fabricated:
    # both stay empty when the backend did not record one).
    model = _extract_task_model(task)
    provider = ""
    if model:
        try:
            from models.registry import registry as _model_registry

            info = _model_registry.get(model)
            if info is not None:
                provider = info.provider
        except Exception:  # noqa: BLE001
            provider = ""

    return {
        "task_id": task.id,
        "project_id": task.project_id,
        "conversation_id": task.conversation_id,
        "kind": task.kind,
        "title": task.title,
        "status": task.status,
        "progress": task.progress,
        "model": model,
        "provider": provider,
        "plan": task.plan_json,
        "result": task.result_json,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "started_at": task.started_at.isoformat() if task.started_at else "",
        "completed_at": task.completed_at.isoformat() if task.completed_at else "",
        "steps": steps,
    }


def _extract_task_model(task: "Task") -> str:
    """Best-effort model id from a task's stored result/plan (bounded, honest)."""

    def walk(obj: Any, depth: int = 0) -> str:
        if depth > 4 or obj is None:
            return ""
        if isinstance(obj, dict):
            for key in ("model", "model_id", "model_used"):
                value = obj.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in obj.values():
                found = walk(value, depth + 1)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj[:20]:
                found = walk(item, depth + 1)
                if found:
                    return found
        return ""

    return walk(task.result_json) or walk(task.plan_json)


# --------------------------------------------------------------------------- #
# module endpoints (all route through the tool registry)
# --------------------------------------------------------------------------- #
def _module_response(tool_name: str, payload: dict[str, Any], project_id: str, user: User) -> dict[str, Any]:
    result, validation, task_id = _run_tool_endpoint(tool_name, payload, project_id, user)

    # If the tool produced a research report, surface it directly (no extra LLM call).
    data = result.data
    if tool_name == "research" and isinstance(data, dict):
        response_text = data.get("markdown", "") or result.summary
    elif isinstance(data, dict) and data.get("text"):
        response_text = data["text"]
    else:
        response_text = result.summary

    return {
        "task_id": task_id,
        "tool": tool_name,
        "status": result.status,
        "summary": result.summary,
        "response": response_text,
        "data": data,
        "artifacts": result.artifacts,
        "error": result.error,
        "error_class": result.error_class,
        "validation": validation.to_dict(),
    }


@router.post("/search", tags=["modules"])
def search_endpoint(payload: SearchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(payload.project_id, user, db)
    return _module_response("search", payload.model_dump(exclude={"project_id"}), payload.project_id, user)


@router.post("/research", tags=["modules"])
def research_endpoint(payload: ResearchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(payload.project_id, user, db)
    return _module_response("research", payload.model_dump(exclude={"project_id"}), payload.project_id, user)


@router.post("/documents", tags=["modules"])
def documents_endpoint(payload: DocumentRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(payload.project_id, user, db)
    return _module_response("docs", payload.model_dump(exclude={"project_id"}), payload.project_id, user)


@router.post("/spreadsheets", tags=["modules"])
def spreadsheets_endpoint(payload: SpreadsheetRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(payload.project_id, user, db)
    return _module_response("sheets", payload.model_dump(exclude={"project_id"}), payload.project_id, user)


@router.post("/slides", tags=["modules"])
def slides_endpoint(payload: SlidesRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(payload.project_id, user, db)
    return _module_response("slides", payload.model_dump(exclude={"project_id"}), payload.project_id, user)


@router.post("/developer", tags=["modules"])
def developer_endpoint(payload: DeveloperRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(payload.project_id, user, db)
    return _module_response("developer", payload.model_dump(exclude={"project_id"}), payload.project_id, user)


@router.post("/websites", tags=["modules"])
def websites_endpoint(payload: WebsiteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(payload.project_id, user, db)
    return _module_response("website", payload.model_dump(exclude={"project_id"}), payload.project_id, user)


@router.post("/images", tags=["modules"])
def images_endpoint(payload: ImageRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_project(payload.project_id, user, db)
    return _module_response("image", payload.model_dump(exclude={"project_id"}), payload.project_id, user)


# --------------------------------------------------------------------------- #
# jobs
# --------------------------------------------------------------------------- #
@router.get("/jobs", tags=["jobs"])
def list_jobs(limit: int = Query(default=50, ge=1, le=200), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"jobs": job_manager.list(limit), "active": job_manager.active_count, "mode": settings.worker_mode}


@router.get("/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str, _: User = Depends(get_current_user)) -> dict[str, Any]:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.delete("/jobs/{job_id}", tags=["jobs"])
def cancel_job(job_id: str, _: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"job_id": job_id, "cancelled": job_manager.cancel(job_id)}


# --------------------------------------------------------------------------- #
# plan preview (dynamic agent-plan progress without executing)
# --------------------------------------------------------------------------- #
@router.post("/agent/plan", tags=["agent"])
def plan_preview(payload: RunRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_project(payload.project_id, user, db)
    ctx = orchestrator.context_assembler.build(project.id, user.id, payload.conversation_id or "", payload.request, extra=payload.extra)
    plan = orchestrator.planner.plan(payload.request, ctx.planner_context())
    return {"intent": plan.intent, "title": plan.title, "source": plan.source, "plan": plan.to_dict(), "context": ctx.to_dict()}
