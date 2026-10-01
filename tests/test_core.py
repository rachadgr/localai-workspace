"""Unit tests for core primitives: security, errors, memory."""

from __future__ import annotations

import pytest

from backend.app.core.errors import ErrorClass, UserError, classify
from backend.app.core.security import hash_password, redact, safe_join, sanitize_filename, verify_password
from agents.memory import memory_manager


def test_password_hash_roundtrip():
    h = hash_password("s3cret-password")
    assert h != "s3cret-password"
    assert verify_password("s3cret-password", h)
    assert not verify_password("wrong", h)


def test_redact_removes_secrets():
    text = "key sk-abcdef1234567890 and ghp_ABCDEF1234567890 and token eyJhbGciOi.eyJzdWIiOiIxMjM0.SflKxwRJSM"
    out = redact(text)
    assert "sk-abcdef" not in out
    assert "ghp_ABCDEF" not in out
    assert "***REDACTED***" in out


def test_safe_join_blocks_traversal(tmp_path):
    (tmp_path / "ok.txt").write_text("x")
    assert safe_join(tmp_path, "ok.txt").exists()
    with pytest.raises(ValueError):
        safe_join(tmp_path, "..", "etc", "passwd")
    with pytest.raises(ValueError):
        safe_join(tmp_path, "../../secret")


def test_sanitize_filename():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("a b?c*.txt") == "a b_c_.txt"
    assert sanitize_filename("") == "file"


def test_error_classification():
    assert isinstance(classify(TimeoutError("x")), Exception)
    assert classify(TimeoutError("x")).error_class == ErrorClass.NETWORK_ERROR
    assert classify(ValueError("bad")).error_class == ErrorClass.VALIDATION_ERROR
    err = UserError("bad input")
    assert err.retryable is False
    assert err.to_dict()["class"] == "UserError"


def test_memory_never_stores_secret_in_clear():
    item = memory_manager.remember("project", "prj_mem_test", "note", "api", "token=ghp_ABCDEFGHIJ1234567890")
    assert "ghp_ABCDEFGHIJ" not in item.value
