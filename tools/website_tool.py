"""AI Website Builder tool.

Pipeline: Requirements → UI Architecture → Components → Styling → Assets →
Implementation → Build → Validation → Artifact. Produces a real, responsive,
accessible static site bundle (zip) plus source files.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from backend.app.core.errors import ToolError
from models.adapters import ChatMessage
from tools.base import BaseTool, Permission, ToolContext, ToolResult, ValidationReport
from tools.registry import register


class _AccessibilityParser(HTMLParser):
    """Collects basic accessibility signals from generated HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, str]] = []
        self.labels: int = 0
        self.inputs: int = 0
        self.headings: list[str] = []
        self.landmarks: set[str] = set()
        self.title_present = False
        self.lang_present = False
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        if tag == "html" and attr.get("lang"):
            self.lang_present = True
        if tag == "title":
            self.title_present = True
            self._in_title = True
        if tag == "img":
            self.images.append({"alt": attr.get("alt", ""), "src": attr.get("src", "")})
        if tag == "label":
            self.labels += 1
        if tag in ("input", "select", "textarea"):
            self.inputs += 1
        if tag in ("header", "nav", "main", "footer", "aside", "section"):
            self.landmarks.add(tag)
        if tag in ("h1", "h2", "h3"):
            self.headings.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False


@register
class WebsiteTool(BaseTool):
    name = "website"
    description = "Build a responsive, accessible static website from a brief, validate its structure and package it as a zip bundle."
    category = "website"
    permissions = [Permission.READ, Permission.WRITE, Permission.FILES, Permission.MODEL]
    cost_estimate = "model-tokens"
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Site requirements/brief"},
            "site_name": {"type": "string"},
            "pages": {"type": "array", "items": {"type": "string"}, "default": ["index"]},
            "style": {"type": "string", "description": "Visual style guidance"},
            "files": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Explicit files to use instead of generation"},
            "model": {"type": "string"},
        },
        "required": ["prompt"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "site_name": {"type": "string"},
            "files": {"type": "array"},
            "validation": {"type": "object"},
            "artifacts": {"type": "array"},
        },
    }

    def availability(self, ctx: ToolContext | None = None) -> str:
        return "AVAILABLE"

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        prompt = str(self.require(payload, "prompt")).strip()
        if not prompt:
            raise ToolError("prompt must not be empty")
        site_name = str(payload.get("site_name") or "site")

        # 1-6. requirements → architecture → components → styling → implementation
        files: dict[str, str] = dict(payload.get("files") or {})
        roadmap: list[str] = []
        synthesis = "explicit"
        note = ""
        if not files:
            registry = getattr(ctx, "model_registry", None)
            if registry is None:
                from models.registry import registry as global_registry

                registry = global_registry
            pages = payload.get("pages") or ["index"]
            generated = None
            if _chat_usable(registry):
                system = (
                    "You are a senior frontend engineer. Return ONLY JSON: "
                    '{"roadmap": [string], "files": {path: content}}. '
                    "Produce a complete static site: index.html (and any requested pages), styles.css, script.js. "
                    "Requirements: semantic HTML5, <html lang>, <meta name=viewport>, accessible landmarks, alt text on images, "
                    "visible focus styles, responsive layout with CSS grid/flex, no external build step, no inline secrets."
                )
                user = f"Site: {site_name}\nPages: {pages}\nStyle: {payload.get('style', 'modern, clean, accessible')}\nBrief: {prompt}"
                try:
                    completion = registry.complete([ChatMessage("system", system), ChatMessage("user", user)], model=payload.get("model"), max_tokens=6000)
                    parsed = _extract_json_object(completion.text)
                    if parsed and parsed.get("files"):
                        generated = {str(k): str(v) for k, v in parsed["files"].items()}
                        roadmap = [str(r) for r in (parsed.get("roadmap") or [])]
                        synthesis = "llm"
                except Exception:  # noqa: BLE001 - deterministic fallback intended
                    generated = None

            if generated is None:
                from tools.composition import build_static_site

                generated = build_static_site(site_name, prompt, str(payload.get("style", "")))
                synthesis = "deterministic"
                note = "Model output was unavailable; the site was composed deterministically from the brief."
                roadmap = ["requirements", "ui-architecture", "components", "styling", "implementation", "validation"]
            files = generated

        # Ensure a stylesheet exists (styling step) so validation is meaningful.
        if not any(f.endswith(".css") for f in files):
            files["styles.css"] = _default_css()
            for path, content in list(files.items()):
                if path.endswith(".html") and "styles.css" not in content:
                    files[path] = content.replace("</head>", '  <link rel="stylesheet" href="styles.css">\n</head>')

        # 7. build (write files to disk under the project)
        site_dir = ctx.category_dir("website") / _slug(site_name)
        site_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for rel, content in files.items():
            rel_safe = rel.lstrip("/").replace("..", "_")
            target = site_dir / rel_safe
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(rel_safe)

        # 8. validation
        validation = validate_site(files)

        # 9. artifact: zip bundle + individual files
        artifacts: list[dict[str, Any]] = []
        zip_bytes = _zip_files(files)
        artifacts.append(
            ctx.save_artifact(f"{_slug(site_name)}-site.zip", zip_bytes, "website", "application/zip", "generated", {"site_name": site_name, "files": written})
        )
        for rel, content in files.items():
            if rel.endswith((".html", ".css", ".js", ".json")):
                artifacts.append(ctx.save_artifact(rel, content, "website", _mime(rel), "website", {"site_name": site_name}))

        status = "SUCCESS"
        summary = f"Website '{site_name}' built with {len(files)} files (validation {'passed' if validation['valid'] else 'has warnings'})."
        return ToolResult(
            status=status,
            summary=summary,
            data={
                "site_name": site_name,
                "files": files,
                "written": written,
                "roadmap": roadmap,
                "validation": validation,
                "site_dir": str(site_dir),
                "synthesis": synthesis,
                "synthesis_note": note,
            },
            artifacts=artifacts,
        )

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        if result.status == "SUCCESS":
            validation = result.data.get("validation", {})
            for check in validation.get("checks", []):
                checks.append(check)
            checks.append({"name": "zip_present", "ok": any(a["name"].endswith(".zip") for a in result.artifacts), "detail": "bundle"})
        return ValidationReport(valid=all(c["ok"] for c in checks), message="website validation")


def validate_site(files: dict[str, str]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    html_files = {p: c for p, c in files.items() if p.endswith(".html")}
    checks.append({"name": "has_html", "ok": bool(html_files), "detail": f"{len(html_files)} page(s)"})
    checks.append({"name": "has_css", "ok": any(p.endswith(".css") for p in files), "detail": ""})

    for path, content in html_files.items():
        parser = _AccessibilityParser()
        try:
            parser.feed(content)
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": f"parse:{path}", "ok": False, "detail": str(exc)})
            continue
        checks.append({"name": f"lang:{path}", "ok": parser.lang_present, "detail": "<html lang>"})
        checks.append({"name": f"title:{path}", "ok": parser.title_present, "detail": "<title>"})
        checks.append({"name": f"viewport:{path}", "ok": "viewport" in content, "detail": "meta viewport"})
        checks.append({"name": f"headings:{path}", "ok": "h1" in parser.headings, "detail": f"{len(parser.headings)} headings"})
        checks.append({"name": f"landmarks:{path}", "ok": bool(parser.landmarks), "detail": ",".join(sorted(parser.landmarks))})
        missing_alt = [img for img in parser.images if not img["alt"] and not img["src"].endswith(".svg")]
        checks.append({"name": f"img_alt:{path}", "ok": not missing_alt, "detail": f"{len(parser.images)} images"})
        if parser.inputs:
            checks.append({"name": f"form_labels:{path}", "ok": parser.labels >= parser.inputs or "aria-label" in content, "detail": f"{parser.inputs} inputs"})

    return {"valid": all(c["ok"] for c in checks), "checks": checks, "message": "static site accessibility & structure"}


def _zip_files(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, content in files.items():
            zf.writestr(rel.lstrip("/").replace("..", "_"), content)
    return buf.getvalue()


def _default_css() -> str:
    return """:root{--bg:#0f172a;--fg:#e2e8f0;--accent:#38bdf8;--muted:#94a3b8}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--fg);line-height:1.6}
header,main,footer,aside,nav{max-width:1080px;margin:0 auto;padding:1.5rem}
a{color:var(--accent)}
a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.grid{display:grid;gap:1.25rem;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.card{background:#1e293b;border-radius:14px;padding:1.25rem;border:1px solid #334155}
@media (max-width:640px){header,main,footer,aside,nav{padding:1rem}}
"""


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "site"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _mime(path: str) -> str:
    if path.endswith(".html"):
        return "text/html"
    if path.endswith(".css"):
        return "text/css"
    if path.endswith(".js"):
        return "text/javascript"
    if path.endswith(".json"):
        return "application/json"
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


__all__ = ["WebsiteTool", "validate_site"]
