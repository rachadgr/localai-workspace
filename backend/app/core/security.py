"""Authentication and security primitives.

- bcrypt password hashing
- JWT access tokens (HS256)
- path-traversal-safe resolution helpers
- secret redaction utilities
"""

from __future__ import annotations

import datetime as dt
import hmac
import re
import secrets
from pathlib import Path
from typing import Any

import bcrypt
import jwt

from configs.settings import settings

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(ghp_[A-Za-z0-9]{8,})"),
    re.compile(r"(gsk-[A-Za-z0-9_\-\.]{8,})"),
    re.compile(r"(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"),
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([A-Za-z0-9_\-]{12,})"),
]


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def create_access_token(user_id: str, email: str = "", role: str = "user", ttl_minutes: int | None = None) -> str:
    ttl = ttl_minutes or settings.access_token_ttl_minutes
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=ttl)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #
def redact(text: str) -> str:
    """Remove anything that looks like a credential from a string."""
    if not text:
        return text
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: (m.group(1) if m.lastindex and m.lastindex > 1 else "") + "***REDACTED***", out)
    for secret in (settings.llm_api_key, settings.jwt_secret, settings.image_provider_key):
        if secret and len(secret) > 8:
            out = out.replace(secret, "***REDACTED***")
    return out


def redact_mapping(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: ("***REDACTED***" if _looks_secret_key(k) else redact_mapping(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [redact_mapping(v) for v in data]
    if isinstance(data, str):
        return redact(data)
    return data


def _looks_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("api_key", "apikey", "secret", "password", "token", "authorization"))


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Filesystem safety
# --------------------------------------------------------------------------- #
def safe_join(base: Path, *parts: str) -> Path:
    """Join path parts onto ``base`` guaranteeing the result stays inside base."""
    base = Path(base).resolve()
    target = base
    for part in parts:
        candidate = (target / str(part)).resolve()
        if not _is_within(base, candidate):
            raise ValueError(f"Path traversal detected for component: {part!r}")
        target = candidate
    return target


def _is_within(base: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(base)
        return True
    except ValueError:
        return False


def sanitize_filename(name: str, fallback: str = "file") -> str:
    name = (name or "").strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._\- ()\[\]]+", "_", name).strip("._ ")
    if not name or name in {".", ".."}:
        name = fallback
    return name[:180]
