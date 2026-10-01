"""Typed error taxonomy + recovery classification.

Every failure in the orchestrator is classified so the Recovery component can
decide whether a retry is safe. The seven categories mirror the spec:
User Error, Tool Error, Model Unavailable, Network Error, Validation Error,
Permission Error, Internal Error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorClass(str, Enum):
    USER_ERROR = "UserError"
    TOOL_ERROR = "ToolError"
    MODEL_UNAVAILABLE = "ModelUnavailable"
    NETWORK_ERROR = "NetworkError"
    VALIDATION_ERROR = "ValidationError"
    PERMISSION_ERROR = "PermissionError"
    INTERNAL_ERROR = "InternalError"


#: Only transient/safe-to-retry classes are listed here.
RETRYABLE: dict[ErrorClass, int] = {
    ErrorClass.NETWORK_ERROR: 3,
    ErrorClass.INTERNAL_ERROR: 2,
    ErrorClass.MODEL_UNAVAILABLE: 2,
    ErrorClass.TOOL_ERROR: 1,
}


@dataclass
class AppError(Exception):
    """Base application error carrying an ErrorClass and a recovery hint."""

    message: str
    error_class: ErrorClass = ErrorClass.INTERNAL_ERROR
    detail: str = ""
    retryable: bool | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)
        if self.retryable is None:
            self.retryable = self.error_class in RETRYABLE

    @property
    def max_retries(self) -> int:
        return RETRYABLE.get(self.error_class, 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.message,
            "class": self.error_class.value,
            "detail": self.detail,
            "retryable": bool(self.retryable),
            "context": self.context,
        }


class UserError(AppError):
    def __init__(self, message: str, detail: str = "", **ctx: Any) -> None:
        super().__init__(message, ErrorClass.USER_ERROR, detail, retryable=False, context=ctx)


class ToolError(AppError):
    def __init__(self, message: str, detail: str = "", retryable: bool = False, **ctx: Any) -> None:
        super().__init__(message, ErrorClass.TOOL_ERROR, detail, retryable=retryable, context=ctx)


class ModelUnavailableError(AppError):
    def __init__(self, message: str, detail: str = "", **ctx: Any) -> None:
        super().__init__(message, ErrorClass.MODEL_UNAVAILABLE, detail, retryable=True, context=ctx)


class NetworkError(AppError):
    def __init__(self, message: str, detail: str = "", **ctx: Any) -> None:
        super().__init__(message, ErrorClass.NETWORK_ERROR, detail, retryable=True, context=ctx)


class ValidationError(AppError):
    def __init__(self, message: str, detail: str = "", **ctx: Any) -> None:
        super().__init__(message, ErrorClass.VALIDATION_ERROR, detail, retryable=False, context=ctx)


class PermissionError_(AppError):
    def __init__(self, message: str, detail: str = "", **ctx: Any) -> None:
        super().__init__(message, ErrorClass.PERMISSION_ERROR, detail, retryable=False, context=ctx)


def classify(exc: BaseException) -> AppError:
    """Best-effort classification of an arbitrary exception."""
    if isinstance(exc, AppError):
        return exc

    name = type(exc).__name__.lower()
    text = str(exc).lower()

    if isinstance(exc, (ConnectionError, TimeoutError)) or "timeout" in text or "timed out" in text:
        return NetworkError("Network request failed", detail=str(exc))
    if "connection" in text or "unreachable" in text or "dns" in text:
        return NetworkError("Network unreachable", detail=str(exc))
    if isinstance(exc, (ValueError, KeyError, TypeError)) or "validation" in text:
        return ValidationError("Invalid input or output", detail=f"{name}: {exc}")
    if isinstance(exc, PermissionError):
        return PermissionError_("Permission denied", detail=str(exc))
    return AppError("Internal error", detail=f"{name}: {exc}")


UNAVAILABLE = "UNAVAILABLE"
