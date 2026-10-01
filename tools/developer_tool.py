"""AI Developer tool.

Pipeline: Repository Analysis → Architecture → Implementation → Tests →
Error Analysis → Fix → Retest → Validation → Final Files.

Tests are ACTUALLY executed in the sandbox; the tool never reports "tests passed"
unless the process really exited 0 with at least one discovered test.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from backend.app.core.errors import ToolError
from models.adapters import ChatMessage
from tools.base import BaseTool, Permission, ToolContext, ToolResult, ValidationReport
from tools.registry import register
from workers.sandbox import run_code


@register
class DeveloperTool(BaseTool):
    name = "developer"
    description = "Analyse a repository, design architecture, implement code, run real tests, analyse failures, fix, retest and validate."
    category = "developer"
    permissions = [Permission.READ, Permission.WRITE, Permission.EXECUTE, Permission.FILES, Permission.CODE, Permission.MODEL]
    cost_estimate = "model-tokens+compute"
    input_schema = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "What to build or analyse"},
            "language": {"type": "string", "default": "python", "enum": ["python", "node", "bash"]},
            "files": {
                "type": "object",
                "description": "Initial files (path -> content). Optional; generated when absent.",
                "additionalProperties": {"type": "string"},
            },
            "tests": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Test files (path -> content)"},
            "run_tests": {"type": "boolean", "default": True},
            "generate_tests": {"type": "boolean", "default": True},
            "max_fix_attempts": {"type": "integer", "default": 2},
            "timeout": {"type": "number", "default": 30},
            "model": {"type": "string"},
        },
        "required": ["task"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "tests_executed": {"type": "boolean"},
            "tests_passed": {"type": "boolean"},
            "exit_code": {"type": "integer"},
            "files": {"type": "object"},
            "attempts": {"type": "integer"},
        },
    }

    def availability(self, ctx: ToolContext | None = None) -> str:
        return "AVAILABLE"

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        task = str(self.require(payload, "task")).strip()
        if not task:
            raise ToolError("task must not be empty")

        registry = getattr(ctx, "model_registry", None)
        if registry is None:
            from models.registry import registry as global_registry

            registry = global_registry

        language = str(payload.get("language", "python"))
        files: dict[str, str] = dict(payload.get("files") or {})
        tests: dict[str, str] = dict(payload.get("tests") or {})

        report: dict[str, Any] = {"task": task, "language": language, "attempts": 0, "log": []}

        # 1. repository / requirement analysis ---------------------------------
        if files:
            report["analysis"] = self._analyse_repo(files)
            report["log"].append("analysed supplied repository")
        else:
            if not _chat_usable(registry):
                return ToolResult(
                    status="UNAVAILABLE",
                    summary="No model provider is available to generate code. Supply 'files' to analyse and test existing code instead.",
                    error="No chat model available for code generation",
                    error_class="UNAVAILABLE",
                )
            report["analysis"] = {"note": "no repository supplied; generating implementation"}
            implementation = self._generate_implementation(task, language, registry, payload.get("model"))
            files = implementation.get("files", {})
            tests = implementation.get("tests", {})
            report["architecture"] = implementation.get("architecture", "")
            report["log"].append(f"generated {len(files)} implementation file(s)")

        # 2. ensure tests exist -------------------------------------------------
        if payload.get("generate_tests", True) and not tests and _chat_usable(registry):
            tests = self._generate_tests(task, files, language, registry, payload.get("model"))
            report["log"].append(f"generated {len(tests)} test file(s)")

        all_files = {**files, **tests}
        if not all_files:
            raise ToolError("No source files to work with")

        # 3-6. execute → analyse → fix → retest -------------------------------
        results: list[dict[str, Any]] = []
        max_attempts = int(payload.get("max_fix_attempts", 2))
        attempt = 0
        while attempt <= max_attempts:
            outcome = self._run_tests(all_files, language, timeout=float(payload.get("timeout", 30)))
            outcome["attempt"] = attempt
            results.append(outcome)
            report["log"].append(f"attempt {attempt}: exit={outcome['exit_code']} ok={outcome['ok']}")
            if outcome["ok"] or not outcome["tests_executed"]:
                break
            if attempt == max_attempts:
                break
            # error analysis + fix
            failed_file = self._pick_primary_file(all_files, language)
            fix = self._fix_code(all_files[failed_file], outcome, task, language, registry, payload.get("model"))
            if fix and fix != all_files[failed_file]:
                all_files[failed_file] = fix
                report["log"].append(f"applied fix to {failed_file}")
            else:
                report["log"].append("no fix produced; stopping retries")
                break
            attempt += 1

        final = results[-1]
        report["attempts"] = len(results)
        report["tests_executed"] = bool(final.get("tests_executed"))
        report["tests_passed"] = bool(final.get("ok") and final.get("tests_executed"))

        # 7. persist final files as artifacts ---------------------------------
        artifacts: list[dict[str, Any]] = []
        for path, content in all_files.items():
            artifacts.append(ctx.save_artifact(path, content, "code", _mime(path), "code", {"task": task}))
        report_md = self._render_report(report, final)
        artifacts.append(ctx.save_artifact("developer-report.md", report_md, "report", "text/markdown", "generated", {"task": task}))

        status = "SUCCESS"
        summary = (
            f"{'Tests passed' if report['tests_passed'] else 'Tests did not pass'} "
            f"(executed={report['tests_executed']}, attempts={report['attempts']}, exit={final['exit_code']})."
        )
        if not report["tests_executed"]:
            summary = "Code generated but no tests were executed (no runnable test suite)."

        return ToolResult(
            status=status,
            summary=summary,
            data={
                "tests_executed": report["tests_executed"],
                "tests_passed": report["tests_passed"],
                "exit_code": final["exit_code"],
                "attempts": report["attempts"],
                "files": all_files,
                "results": results,
                "stdout": final.get("stdout", "")[:4000],
                "stderr": final.get("stderr", "")[:4000],
                "analysis": report.get("analysis"),
                "architecture": report.get("architecture", ""),
                "log": report["log"],
            },
            artifacts=artifacts,
        )

    # -------------------------------------------------------------- analysis
    @staticmethod
    def _analyse_repo(files: dict[str, str]) -> dict[str, Any]:
        analysis: dict[str, Any] = {"file_count": len(files), "files": {}, "totals": {"lines": 0, "functions": 0, "classes": 0}}
        for path, content in files.items():
            info: dict[str, Any] = {"lines": content.count("\n") + 1, "language": _language_for(path)}
            if path.endswith(".py"):
                try:
                    tree = ast.parse(content)
                    info["functions"] = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
                    info["classes"] = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
                    analysis["totals"]["functions"] += len(info["functions"])
                    analysis["totals"]["classes"] += len(info["classes"])
                except SyntaxError as exc:
                    info["syntax_error"] = f"line {exc.lineno}: {exc.msg}"
            analysis["files"][path] = info
            analysis["totals"]["lines"] += info["lines"]
        return analysis

    # ------------------------------------------------------------ generation
    def _generate_implementation(self, task: str, language: str, registry: Any, model: str | None) -> dict[str, Any]:
        if language == "python":
            system = (
                "You are a senior Python engineer. Return ONLY JSON: "
                '{"architecture": string, "files": {path: content}, "tests": {path: content}}. '
                "Use pytest for tests. Code must be runnable with the stdlib unless a dependency is unavoidable."
            )
        elif language == "node":
            system = (
                "You are a senior Node.js engineer. Return ONLY JSON: "
                '{"architecture": string, "files": {path: content}, "tests": {path: content}}. '
                "Use only Node core modules; tests must run via `node <testfile>` and exit non-zero on failure."
            )
        else:
            system = "You are a senior engineer. Return ONLY JSON {\"architecture\": string, \"files\": {path: content}, \"tests\": {path: content}}."
        completion = registry.complete([ChatMessage("system", system), ChatMessage("user", task)], model=model, max_tokens=4000)
        parsed = _extract_json_object(completion.text)
        if not parsed or "files" not in parsed:
            raise ToolError("Model did not return a usable implementation", detail=completion.text[:400])
        return {
            "architecture": str(parsed.get("architecture", "")),
            "files": {str(k): str(v) for k, v in (parsed.get("files") or {}).items()},
            "tests": {str(k): str(v) for k, v in (parsed.get("tests") or {}).items()},
        }

    def _generate_tests(self, task: str, files: dict[str, str], language: str, registry: Any, model: str | None) -> dict[str, str]:
        if language == "python":
            instruction = "Write pytest tests. Return ONLY JSON {path: content}. Tests must fail loudly if behaviour is wrong."
        elif language == "node":
            instruction = "Write a Node test file using assert. Return ONLY JSON {path: content}. It must exit(1) on failure."
        else:
            instruction = "Write a shell test script. Return ONLY JSON {path: content}."
        prompt = f"{instruction}\n\nTask:\n{task}\n\nExisting files:\n{json.dumps(files)[:8000]}"
        completion = registry.complete([ChatMessage("user", prompt)], model=model, max_tokens=2500)
        parsed = _extract_json_object(completion.text)
        if not parsed:
            return {}
        return {str(k): str(v) for k, v in parsed.items() if isinstance(v, str)}

    def _fix_code(self, code: str, outcome: dict[str, Any], task: str, language: str, registry: Any, model: str | None) -> str | None:
        prompt = (
            f"Fix the {language} code so its tests pass. Return ONLY the corrected file content, no markdown fences.\n\n"
            f"Task: {task}\n\nFailing output:\nSTDOUT:\n{outcome.get('stdout', '')[:2500]}\nSTDERR:\n{outcome.get('stderr', '')[:2500]}\n\n"
            f"Current code:\n{code[:6000]}"
        )
        try:
            completion = registry.complete([ChatMessage("user", prompt)], model=model, max_tokens=3000)
            text = completion.text.strip()
            text = re.sub(r"^```[a-zA-Z]*\n", "", text)
            text = re.sub(r"\n```$", "", text)
            return text if text and text != code else None
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------ execution
    def _run_tests(self, files: dict[str, str], language: str, timeout: float) -> dict[str, Any]:
        test_file = self._pick_test_file(files, language)
        if not test_file:
            return {"ok": False, "tests_executed": False, "exit_code": -1, "stdout": "", "stderr": "no test file found"}
        if language == "python":
            uses_pytest = "def test_" in files[test_file] or "import pytest" in files[test_file]
            if uses_pytest:
                # Run pytest inside the sandboxed interpreter (real collection + assertions).
                runner = f"import sys, pytest\nsys.exit(pytest.main(['-q', {test_file!r}]))"
                result = run_code(runner, "python", files=dict(files), filename="_run_tests.py", timeout=timeout)
            else:
                result = run_code(files[test_file], "python", files=dict(files), filename=test_file, timeout=timeout)
            return {
                "ok": result.ok,
                "tests_executed": True,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_ms": result.duration_ms,
            }
        result = run_code(files[test_file], language, files=files, filename=test_file, timeout=timeout)
        return {"ok": result.ok, "tests_executed": True, "exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr, "duration_ms": result.duration_ms}

    @staticmethod
    def _pick_test_file(files: dict[str, str], language: str) -> str | None:
        for path in files:
            name = Path(path).name.lower()
            if language == "python" and (name.startswith("test_") or name.endswith("_test.py")):
                return path
        for path in files:
            if language == "node" and "test" in Path(path).name.lower():
                return path
        for path in files:
            if language in ("bash", "sh") and Path(path).name.lower().startswith("test"):
                return path
        return None

    @staticmethod
    def _pick_primary_file(files: dict[str, str], language: str) -> str:
        candidates = [p for p in files if not Path(p).name.lower().startswith("test")]
        if language == "python":
            for p in candidates:
                if p.endswith(".py"):
                    return p
        return candidates[0] if candidates else next(iter(files))

    def _render_report(self, report: dict[str, Any], final: dict[str, Any]) -> str:
        md = [f"# Developer Report", "", f"**Task:** {report['task']}", f"**Language:** {report['language']}"]
        md += [
            f"**Tests executed:** {report.get('tests_executed')}",
            f"**Tests passed:** {report.get('tests_passed')}",
            f"**Attempts:** {report.get('attempts')}",
            f"**Final exit code:** {final.get('exit_code')}",
            "",
            "## Log",
        ]
        md += [f"- {line}" for line in report.get("log", [])]
        if report.get("architecture"):
            md += ["", "## Architecture", report["architecture"]]
        md += ["", "## Final test output", "```", (final.get("stdout", "") + final.get("stderr", ""))[-3000:], "```"]
        return "\n".join(md)

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        if result.status == "SUCCESS":
            checks.append({"name": "no_false_pass", "ok": not (result.data.get("tests_passed") and not result.data.get("tests_executed")), "detail": "claims are backed by real execution"})
            checks.append({"name": "has_files", "ok": bool(result.data.get("files")), "detail": f"{len(result.data.get('files', {}))} files"})
            import os

            for art in result.artifacts:
                if art["name"].endswith(".py"):
                    checks.append({"name": f"exists:{art['name']}", "ok": os.path.exists(art["storage_path"]), "detail": ""})
                    break
        return ValidationReport(valid=all(c["ok"] for c in checks), message="developer validation")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _language_for(path: str) -> str:
    if path.endswith(".py"):
        return "python"
    if path.endswith((".js", ".mjs", ".ts")):
        return "javascript"
    if path.endswith((".sh", ".bash")):
        return "shell"
    return "text"


def _mime(path: str) -> str:
    if path.endswith(".py"):
        return "text/x-python"
    if path.endswith((".js", ".mjs")):
        return "text/javascript"
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".md"):
        return "text/markdown"
    return "text/plain"


def _chat_usable(registry: Any) -> bool:
    if registry is None:
        return False
    checker = getattr(registry, "chat_available", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:  # noqa: BLE001
            return False
    try:
        return bool(registry.chat_models())
    except Exception:  # noqa: BLE001
        return False


__all__ = ["DeveloperTool"]
