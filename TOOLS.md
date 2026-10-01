# TOOLS

Single central registry: `tools/registry.py` (`ToolRegistry`). Every tool declares
`name, description, category, input_schema, output_schema, permissions,
cost_estimate, availability(), execute(), validate()`.

| Tool | Category | Permissions | Availability | Output |
|---|---|---|---|---|
| `chat` | chat | READ, MODEL | needs usable LLM | text + tokens |
| `search` | search | READ, NETWORK, WEB, MODEL | needs egress+search backend | sources, evidence, summary, citations |
| `research` | research | READ, NETWORK, WEB, MODEL | needs egress | cited Markdown report (artifact) |
| `docs` | documents | READ, WRITE, FILES, MODEL | always | `.md`/`.txt`/`.docx`/`.pdf` artifacts |
| `sheets` | spreadsheets | READ, WRITE, FILES | always | `.csv` + `.xlsx` (+ stats/charts) |
| `slides` | presentations | READ, WRITE, FILES, MODEL | always | `.pptx` (8–12) + outline `.md` |
| `developer` | developer | READ, WRITE, EXECUTE, FILES, CODE, MODEL | always (needs LLM only to *generate* code) | source files, `developer-report.md` |
| `website` | website | READ, WRITE, FILES, MODEL | always | site files + `.zip` bundle |
| `image` | design | READ, WRITE, FILES, NETWORK, MODEL | brief: always · generate: needs provider | brief JSON / image artifacts |
| `files` | files | READ, WRITE, FILES | always | project-scoped file ops |

## Ground rules
1. **No fabrication.** If a dependency (model, network, image provider) is
   missing or refusing requests, the tool returns `status: "UNAVAILABLE"` with a
   reason. It never returns canned content.
2. **Real artifacts.** `docs/sheets/slides/website` write real files to disk;
   validation re-opens them (OOXML zip check, `%PDF` header, CSV row count, PPTX
   slide count, HTML accessibility scan).
3. **Real execution.** `developer` runs tests in a sandboxed subprocess. It only
   reports "tests passed" when the process genuinely exited 0 with tests collected.
4. **Deterministic fallback (labelled).** When no LLM is usable, `docs`, `slides`
   and `website` compose output from the user's own brief via `tools/composition.py`
   and mark `synthesis: "deterministic"` + a note. No external facts are invented.

## Adding a tool
```python
from tools.base import BaseTool, Permission
from tools.registry import register

@register
class MyTool(BaseTool):
    name = "mytool"
    description = "Does X."
    category = "custom"
    permissions = [Permission.READ]
    input_schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    def availability(self, ctx=None): return "AVAILABLE"
    def execute(self, ctx, payload):
        ...  # return ToolResult(status="SUCCESS", summary=..., data=..., artifacts=[...])
```
Registering is automatic via the `@register` decorator; discovery metadata is
persisted to the `tools` table.
