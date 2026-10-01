"""Super Agent Orchestrator.

Flow: USER REQUEST → INTENT → CONTEXT → PLAN → TOOL SELECTION → EXECUTION →
OBSERVATION → VALIDATION → RECOVERY → ARTIFACTS → FINAL RESPONSE.

Every task carries: task_id, status, steps, artifacts, errors, started_at,
completed_at. Nothing is fabricated: steps that cannot run return UNAVAILABLE and
are reported as such.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Any

from agents.context import ContextAssembler, TaskContext
from agents.memory import MemoryManager
from agents.planner import Plan, Planner
from agents.recovery import Recovery
from agents.router import Router
from agents.validator import Validator
from backend.app.core.errors import AppError, classify
from backend.app.core.events import emit_artifact, emit_done, emit_error, emit_failed, emit_plan, emit_status, emit_step
from backend.app.core.observability import Observation, get_logger, record_observation
from database.models import Task, TaskStep, session_scope, utcnow
from models.registry import registry as model_registry
from tools.base import ToolContext, ToolResult
from tools.registry import registry as tool_registry

logger = get_logger("orchestrator")

FINAL_STATUSES = ("COMPLETED", "FAILED", "CANCELLED")


@dataclass
class OrchestrationResult:
    task_id: str
    status: str
    intent: str
    plan: dict[str, Any]
    steps: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    response: str
    started_at: str
    completed_at: str
    observations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "intent": self.intent,
            "plan": self.plan,
            "steps": self.steps,
            "artifacts": self.artifacts,
            "errors": self.errors,
            "response": self.response,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "observations": self.observations,
        }


class SuperAgentOrchestrator:
    def __init__(
        self,
        tool_reg: Any = None,
        model_reg: Any = None,
        memory: MemoryManager | None = None,
    ) -> None:
        self.tools = tool_reg or tool_registry
        self.tools.load_builtin_tools()
        self.models = model_reg or model_registry
        self.memory = memory or MemoryManager()
        self.planner = Planner(self.tools, self.models, self.memory)
        self.router = Router(self.tools)
        self.validator = Validator(self.tools)
        self.context_assembler = ContextAssembler(self.memory)

    # ------------------------------------------------------------------ api
    def run(
        self,
        request: str,
        project_id: str,
        user_id: str = "",
        conversation_id: str = "",
        task_id: str | None = None,
        cancel_event: threading.Event | None = None,
        extra_context: dict[str, Any] | None = None,
        persist_assistant_message: bool = False,
    ) -> OrchestrationResult:
        from database.models import Artifact, Message, new_id

        task_id = task_id or new_id("tsk_")
        started = utcnow()

        # ---- create task record ------------------------------------------
        with session_scope() as db:
            task = Task(
                id=task_id,
                project_id=project_id,
                conversation_id=conversation_id or None,
                kind="agent",
                title=request[:200],
                request=request,
                status="RUNNING",
                started_at=started,
                progress=0.0,
            )
            db.add(task)

        emit_status(task_id, "RUNNING", "Understanding the request…", 0.02, project_id=project_id)

        errors: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        step_records: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []

        try:
            # ---- intent + context + plan ---------------------------------
            context = self.context_assembler.build(project_id, user_id, conversation_id, request, extra=extra_context)
            plan = self.planner.plan(request, context.planner_context())
            emit_plan(task_id, plan.to_dict())
            emit_status(task_id, "RUNNING", f"Plan ready ({len(plan.steps)} step(s))", 0.08)

            with session_scope() as db:
                row = db.get(Task, task_id)
                if row is not None:
                    row.kind = plan.intent
                    row.plan_json = plan.to_dict()

            self.memory.remember("project", project_id, "note", f"task:{task_id}", f"{plan.intent}: {request[:300]}")

            # ---- execute steps -------------------------------------------
            previous: dict[str, Any] = {}
            total = max(1, len(plan.steps))
            step_ctx = ToolContext(
                project_id=project_id,
                user_id=user_id,
                task_id=task_id,
                conversation_id=conversation_id,
                settings=self._settings(),
                model_registry=self.models,
            )

            for step in plan.steps:
                if cancel_event is not None and cancel_event.is_set():
                    emit_status(task_id, "CANCELLED", "Cancelled by user", 1.0)
                    record = self._record_step(task_id, step, "CANCELLED", "Cancelled before execution")
                    step_records.append(record)
                    return self._finish(task_id, "CANCELLED", plan, step_records, artifacts, errors, "Task cancelled.", started, observations)

                routing = self.router.route(plan, step, step_ctx, previous)
                emit_step(
                    task_id,
                    {
                        "index": step.index,
                        "name": step.name,
                        "tool": routing.tool,
                        "status": "RUNNING",
                        "available": routing.available,
                        "message": routing.reason,
                    },
                )

                result = self._execute_step(task_id, step, routing, step_ctx, previous, cancel_event)
                validation = self.validator.validate_step(routing.tool, step_ctx, result)

                # ---- observation ----------------------------------------
                obs = Observation(
                    task_id=task_id,
                    project_id=project_id,
                    tool=routing.tool,
                    model=str(result.data.get("model", "")) if isinstance(result.data, dict) else "",
                    status=result.status,
                    error=result.error or "",
                    artifact_ids=[a.get("id", "") for a in result.artifacts],
                    tokens_in=int(result.data.get("tokens_in", 0) or 0) if isinstance(result.data, dict) else 0,
                    tokens_out=int(result.data.get("tokens_out", 0) or 0) if isinstance(result.data, dict) else 0,
                    extra={"validation_valid": validation.valid, "step_index": step.index},
                )
                observations.append(record_observation(obs))

                if result.artifacts:
                    artifacts.extend(result.artifacts)
                    for art in result.artifacts:
                        emit_artifact(task_id, art)

                if result.status == "SUCCESS":
                    previous[routing.tool] = result.data
                    if routing.tool == "chat":
                        previous["chat"] = result.data
                    status_value = "COMPLETED"
                elif result.status == "UNAVAILABLE":
                    status_value = "UNAVAILABLE"
                    errors.append({"step": step.index, "tool": routing.tool, "class": "UNAVAILABLE", "error": result.summary})
                else:
                    status_value = "FAILED"
                    errors.append({"step": step.index, "tool": routing.tool, "class": result.error_class or "ToolError", "error": result.error or result.summary})

                record = self._record_step(task_id, step, status_value, result.summary, result=result.to_dict(), validation=validation.to_dict())
                step_records.append(record)
                emit_step(
                    task_id,
                    {
                        "index": step.index,
                        "name": step.name,
                        "tool": routing.tool,
                        "status": status_value,
                        "message": result.summary,
                        "validation": validation.to_dict(),
                    },
                )

                progress = 0.08 + (0.85 * (len(step_records) / total))
                emit_status(task_id, "RUNNING", f"{step.name}: {status_value.lower()}", progress)
                self._update_task(task_id, progress=progress)

                if status_value == "FAILED" and not step.optional:
                    break

            if cancel_event is not None and cancel_event.is_set():
                return self._finish(task_id, "CANCELLED", plan, step_records, artifacts, errors, "Task cancelled.", started, observations)

            # ---- final response ------------------------------------------
            response = self._compose_response(request, plan, step_records, errors)
            final_status = self._final_status(step_records, errors)

            if persist_assistant_message and conversation_id:
                with session_scope() as db:
                    db.add(Message(conversation_id=conversation_id, role="assistant", content=response, meta_json={"task_id": task_id, "intent": plan.intent}))

            result_obj = self._finish(task_id, final_status, plan, step_records, artifacts, errors, response, started, observations)
            self.memory.record_task(project_id, {"id": task_id, "kind": plan.intent, "request": request, "status": final_status})
            if final_status == "FAILED":
                emit_failed(task_id, errors[-1] if errors else {"error": "Task failed"})
            else:
                emit_done(task_id, result_obj.to_dict())
            return result_obj

        except AppError as exc:
            errors.append(exc.to_dict())
            emit_error(task_id, exc.to_dict())
            emit_failed(task_id, exc.to_dict())
            return self._finish(task_id, "FAILED", None, step_records, artifacts, errors, f"Task failed: {exc.message}", started, observations)
        except Exception as exc:  # noqa: BLE001
            app_err = classify(exc)
            errors.append(app_err.to_dict())
            logger.exception("orchestrator crashed")
            emit_error(task_id, app_err.to_dict())
            emit_failed(task_id, app_err.to_dict())
            return self._finish(task_id, "FAILED", None, step_records, artifacts, errors, f"Task failed: {app_err.message}", started, observations)

    # ------------------------------------------------------------- internal
    @staticmethod
    def _settings() -> Any:
        from configs.settings import settings

        return settings

    def _execute_step(
        self,
        task_id: str,
        step: Any,
        routing: Any,
        ctx: ToolContext,
        previous: dict[str, Any],
        cancel_event: threading.Event | None,
    ) -> ToolResult:
        if not routing.available:
            # Honest UNAVAILABLE, with an optional fallback attempt.
            if routing.fallback_tool and self.tools.has(routing.fallback_tool) and self.tools.availability(routing.fallback_tool, ctx) == "AVAILABLE":
                fallback_inputs = self._fallback_inputs(routing.fallback_tool, routing.inputs)
                res = self.tools.execute(routing.fallback_tool, ctx, fallback_inputs)
                res.summary = f"{routing.tool} unavailable ({routing.reason}); used fallback '{routing.fallback_tool}'. {res.summary}"
                return res
            return ToolResult(status="UNAVAILABLE", summary=routing.reason, error=routing.reason, error_class="UNAVAILABLE")

        recovery = Recovery()
        attempt = 0
        while attempt <= min(2, recovery.max_attempts):
            if cancel_event is not None and cancel_event.is_set():
                return ToolResult(status="FAILED", summary="Cancelled", error="Cancelled", error_class="UserError")
            res = self.tools.execute(routing.tool, ctx, routing.inputs)
            if res.status == "SUCCESS":
                return res
            if res.status == "UNAVAILABLE":
                if routing.fallback_tool and self.tools.has(routing.fallback_tool) and self.tools.availability(routing.fallback_tool, ctx) == "AVAILABLE":
                    fallback_inputs = self._fallback_inputs(routing.fallback_tool, routing.inputs)
                    fb = self.tools.execute(routing.fallback_tool, ctx, fallback_inputs)
                    fb.summary = f"{routing.tool} unavailable; used fallback '{routing.fallback_tool}'. {fb.summary}"
                    return fb
                return res

            decision = recovery.decide(
                AppError(res.error or res.summary, error_class_from_string(res.error_class)),
                attempt,
                fallback_tool=routing.fallback_tool,
                error_class=res.error_class,
            )
            emit_status(task_id, "RUNNING", f"Recovering from {res.error_class or 'error'} ({decision.action})", None)
            if decision.action == "retry":
                recovery.sleep(decision)
                attempt = decision.attempt
                continue
            if decision.action == "fallback" and decision.fallback_tool and self.tools.has(decision.fallback_tool):
                fb = self.tools.execute(decision.fallback_tool, ctx, self._fallback_inputs(decision.fallback_tool, routing.inputs))
                fb.summary = f"Recovered via fallback '{decision.fallback_tool}'. {fb.summary}"
                return fb
            return res

        return ToolResult(status="FAILED", summary="Step failed after retries", error="retry budget exhausted", error_class="ToolError")

    @staticmethod
    def _fallback_inputs(fallback_tool: str, inputs: dict[str, Any]) -> dict[str, Any]:
        if fallback_tool == "chat":
            msg = inputs.get("message") or inputs.get("prompt") or inputs.get("query") or inputs.get("question") or ""
            return {"message": f"{msg}\n\n(Note: the preferred tool was unavailable; answer from general knowledge and state any uncertainty.)"}
        if fallback_tool == "docs":
            return {"title": inputs.get("title", "Document"), "prompt": inputs.get("prompt") or inputs.get("description") or inputs.get("message", ""), "format": "md"}
        if fallback_tool == "search":
            return {"query": inputs.get("query") or inputs.get("question") or inputs.get("prompt", ""), "limit": 8}
        return inputs

    def _compose_response(self, request: str, plan: Plan, steps: list[dict[str, Any]], errors: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        chat_data = next((s.get("result", {}).get("data", {}) for s in steps if s["tool"] == "chat" and s["status"] == "COMPLETED"), None)
        if chat_data and chat_data.get("text"):
            return chat_data["text"]

        lines.append(f"**{plan.title}**")
        lines.append("")
        lines.append(f"Intent: `{plan.intent}` · Steps executed: {len(steps)}")
        lines.append("")
        for s in steps:
            icon = {"COMPLETED": "✓", "UNAVAILABLE": "⊘", "FAILED": "✕", "CANCELLED": "⊘"}.get(s["status"], "•")
            lines.append(f"{icon} **{s['name']}** ({s['tool']}) — {s['status']}: {s.get('summary', '')[:200]}")
        artifacts = [a for s in steps for a in s.get("artifacts", [])]
        if artifacts:
            lines.append("")
            lines.append("**Artifacts**")
            for a in artifacts:
                lines.append(f"- `{a['name']}` ({a.get('mime_type', '')}, {a.get('size', 0)} bytes) → `/api/artifacts/{a['id']}/content`")
        if errors:
            lines.append("")
            lines.append("**Errors**")
            for e in errors:
                lines.append(f"- [{e.get('class', 'Error')}] step {e.get('step')} ({e.get('tool')}): {e.get('error', '')[:200]}")
        if not artifacts and not errors and plan.intent != "chat":
            lines.append("")
            lines.append("_No artifacts were produced. See step statuses above._")
        return "\n".join(lines)

    @staticmethod
    def _final_status(steps: list[dict[str, Any]], errors: list[dict[str, Any]]) -> str:
        if not steps:
            return "FAILED"
        statuses = {s["status"] for s in steps}
        if statuses == {"COMPLETED"}:
            return "COMPLETED"
        if "COMPLETED" in statuses:
            return "COMPLETED"  # partial success is still usable; errors are reported
        if statuses == {"UNAVAILABLE"}:
            return "FAILED" if errors else "COMPLETED"
        return "FAILED"

    def _record_step(
        self,
        task_id: str,
        step: Any,
        status: str,
        summary: str,
        result: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with session_scope() as db:
            record = TaskStep(
                task_id=task_id,
                index=step.index,
                name=step.name,
                tool=step.tool,
                status=status,
                input_json=step.inputs,
                output_json={"summary": summary, **(result or {}), **({"validation": validation} if validation else {})},
                started_at=utcnow(),
                completed_at=utcnow(),
            )
            db.add(record)
            db.flush()
            step_id = record.id
        return {
            "id": step_id,
            "index": step.index,
            "name": step.name,
            "tool": step.tool,
            "status": status,
            "summary": summary,
            "result": result or {},
            "validation": validation or {},
            "artifacts": (result or {}).get("artifacts", []),
        }

    @staticmethod
    def _update_task(task_id: str, progress: float | None = None, status: str | None = None) -> None:
        with session_scope() as db:
            row = db.get(Task, task_id)
            if row is None:
                return
            if progress is not None:
                row.progress = max(0.0, min(1.0, progress))
            if status:
                row.status = status

    def _finish(
        self,
        task_id: str,
        status: str,
        plan: Plan | None,
        steps: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        response: str,
        started: dt.datetime,
        observations: list[dict[str, Any]],
    ) -> OrchestrationResult:
        completed = utcnow()
        with session_scope() as db:
            row = db.get(Task, task_id)
            if row is not None:
                row.status = status
                row.completed_at = completed
                row.progress = 1.0 if status in ("COMPLETED", "FAILED", "CANCELLED") else row.progress
                row.error = errors[-1]["error"] if errors else ""
                row.result_json = {
                    "response": response,
                    "artifacts": artifacts,
                    "errors": errors,
                    "plan": plan.to_dict() if plan else {},
                    "steps": [{k: v for k, v in s.items() if k != "result"} for s in steps],
                }
        return OrchestrationResult(
            task_id=task_id,
            status=status,
            intent=plan.intent if plan else "unknown",
            plan=plan.to_dict() if plan else {},
            steps=steps,
            artifacts=artifacts,
            errors=errors,
            response=response,
            started_at=(started or utcnow()).isoformat(),
            completed_at=completed.isoformat(),
            observations=observations,
        )


def error_class_from_string(value: str) -> Any:
    from backend.app.core.errors import ErrorClass

    try:
        return ErrorClass(value)
    except Exception:  # noqa: BLE001
        return ErrorClass.INTERNAL_ERROR


orchestrator = SuperAgentOrchestrator()

__all__ = ["SuperAgentOrchestrator", "OrchestrationResult", "orchestrator"]
