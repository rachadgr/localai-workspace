"""Recovery component: classification, bounded retry, and compensating actions.

Guarantees:
* Only transient/safe failure classes are retried (never UserError/ValidationError).
* Retries are bounded per step, with increasing backoff, preventing infinite loops.
* A failed step degrades to an explicit error or a declared fallback tool.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.app.core.errors import RETRYABLE, AppError, ErrorClass, classify
from backend.app.core.observability import get_logger

logger = get_logger("recovery")

MAX_TOTAL_ATTEMPTS = 4


@dataclass
class RecoveryDecision:
    action: str  # retry | fallback | fail
    attempt: int
    delay: float
    fallback_tool: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "attempt": self.attempt, "delay": self.delay, "fallback_tool": self.fallback_tool, "reason": self.reason}


class Recovery:
    def __init__(self, max_attempts: int = MAX_TOTAL_ATTEMPTS) -> None:
        self.max_attempts = max_attempts
        self.history: list[dict[str, Any]] = []

    def decide(self, exc: BaseException | AppError, attempt: int, fallback_tool: str | None = None, error_class: str | None = None) -> RecoveryDecision:
        app_err = exc if isinstance(exc, AppError) else classify(exc)
        error_class = error_class or app_err.error_class.value

        budget = RETRYABLE.get(app_err.error_class, 0)
        can_retry = app_err.retryable and attempt < min(budget, self.max_attempts)

        if can_retry:
            delay = min(2.0, 0.25 * (2 ** attempt))
            decision = RecoveryDecision(action="retry", attempt=attempt + 1, delay=delay, reason=f"{error_class} is transient (attempt {attempt + 1})")
        elif fallback_tool and error_class in (ErrorClass.MODEL_UNAVAILABLE.value, ErrorClass.TOOL_ERROR.value, "UNAVAILABLE"):
            decision = RecoveryDecision(action="fallback", attempt=attempt, delay=0.0, fallback_tool=fallback_tool, reason=f"{error_class}: degrade to '{fallback_tool}'")
        else:
            decision = RecoveryDecision(action="fail", attempt=attempt, delay=0.0, reason=f"{error_class} is not retryable")

        self.history.append({"error_class": error_class, **decision.to_dict()})
        return decision

    def sleep(self, decision: RecoveryDecision) -> None:
        if decision.delay:
            time.sleep(decision.delay)

    @staticmethod
    def wrap(exc: BaseException) -> AppError:
        return classify(exc)


def with_retries(fn: Callable[[], Any], fallback: Callable[[], Any] | None, recovery: Recovery, fallback_tool: str | None = None) -> tuple[Any, list[dict[str, Any]]]:
    """Execute ``fn`` with bounded recovery. Returns (result, decisions)."""
    decisions: list[dict[str, Any]] = []
    attempt = 0
    last_exc: BaseException | None = None
    while attempt < recovery.max_attempts:
        try:
            return fn(), decisions
        except BaseException as exc:  # noqa: BLE001
            last_exc = exc
            decision = recovery.decide(exc, attempt, fallback_tool=fallback_tool)
            decisions.append(decision.to_dict())
            if decision.action == "retry":
                recovery.sleep(decision)
                attempt = decision.attempt
                continue
            if decision.action == "fallback" and fallback is not None:
                try:
                    return fallback(), decisions
                except BaseException as fb_exc:  # noqa: BLE001
                    decisions.append({"action": "fallback_failed", "reason": classify(fb_exc).message})
                    raise fb_exc
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry loop exhausted")


__all__ = ["Recovery", "RecoveryDecision", "with_retries", "MAX_TOTAL_ATTEMPTS"]
