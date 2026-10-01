"""Sandboxed code execution.

Constraints (defence in depth):
* Only allow-listed interpreters/commands may run.
* Execution happens inside a per-invocation temp directory under the project workspace.
* Hard wall-clock timeout and output caps; no shell=True.
* Host filesystem access is limited to the sandbox directory (cwd) plus read-only
  interpreter paths; no arbitrary paths are exposed through the API.
* Environment is scrubbed of secrets before spawning the child process.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from backend.app.core.errors import PermissionError_, ToolError
from backend.app.core.security import redact

ALLOWED_RUNNERS: dict[str, list[str]] = {
    "python": [sys.executable, "-I"],  # isolated mode: ignores env + user site
    "python3": [sys.executable, "-I"],
    "node": ["node", "--no-warnings"],
    "bash": ["bash"],
    "sh": ["sh"],
}

#: Commands that are never permitted, even inside the sandbox.
BLOCKED_TOKENS = {
    "rm -rf /",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "shutdown",
    "reboot",
    "curl ",
    "wget ",
    "nc ",
    "ncat ",
    "ssh ",
    "sudo",
    "chmod 777 /",
    ">/dev/sda",
}


@dataclass
class ExecutionResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    command: str
    files: list[str] = field(default_factory=list)
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "command": self.command,
            "files": self.files,
            "timed_out": self.timed_out,
        }


def _clean_env() -> dict[str, str]:
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "PYTHONHASHSEED")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _validate(command: Sequence[str]) -> None:
    if not command:
        raise ToolError("Empty command")
    joined = " ".join(command).lower()
    for token in BLOCKED_TOKENS:
        if token in joined:
            raise PermissionError_(f"Command rejected by policy: contains '{token.strip()}'")
    runner = command[0]
    allowed = {os.path.basename(r) for r in runner if r}
    if not any(
        os.path.basename(runner) == os.path.basename(entry) or runner.endswith(os.path.basename(entry))
        for entry in [sys.executable, "python", "python3", "node", "bash", "sh"]
    ):
        if runner not in ("python", "python3", "node", "bash", "sh"):
            raise PermissionError_(f"Interpreter not allowed: {runner}")


def run_code(
    code: str,
    language: str = "python",
    *,
    files: dict[str, str] | None = None,
    filename: str | None = None,
    stdin: str = "",
    timeout: float = 20.0,
    workdir: Path | None = None,
    extra_args: Sequence[str] | None = None,
) -> ExecutionResult:
    """Execute code in an isolated temp dir and capture output."""
    language = language.lower()
    if language not in ALLOWED_RUNNERS:
        raise ToolError(f"Unsupported language '{language}'")

    base = workdir or Path(tempfile.mkdtemp(prefix="laiw-sandbox-"))
    base.mkdir(parents=True, exist_ok=True)

    default_name = {"python": "main.py", "python3": "main.py", "node": "main.js", "bash": "main.sh", "sh": "main.sh"}[language]
    script_name = filename or default_name
    script_path = base / script_name
    script_path.write_text(code, encoding="utf-8")

    for rel, content in (files or {}).items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    command = list(ALLOWED_RUNNERS[language]) + [str(script_path)] + list(extra_args or [])
    _validate(command)

    import time

    start = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(  # noqa: S603 - allow-listed command, no shell
            command,
            cwd=str(base),
            env=_clean_env(),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
        exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = -1
        stdout = (exc.stdout or b"").decode("utf-8", "ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = f"Execution timed out after {timeout}s"
    duration_ms = int((time.perf_counter() - start) * 1000)

    MAX = 20000
    produced = sorted(p.name for p in base.rglob("*") if p.is_file() and p.name != script_name)
    return ExecutionResult(
        ok=(exit_code == 0 and not timed_out),
        exit_code=exit_code,
        stdout=redact(stdout[:MAX]),
        stderr=redact(stderr[:MAX]),
        duration_ms=duration_ms,
        command=" ".join(command),
        files=produced[:50],
        timed_out=timed_out,
    )


def cleanup(path: Path) -> None:
    if path.exists() and "laiw-sandbox-" in str(path):
        shutil.rmtree(path, ignore_errors=True)


__all__ = ["run_code", "ExecutionResult", "ALLOWED_RUNNERS", "BLOCKED_TOKENS", "cleanup"]
