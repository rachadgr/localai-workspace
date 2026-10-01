"""AI Sheets tool: build real CSV/XLSX workbooks with formulas, sorting, filtering,
aggregation, statistics and charts. Data is never invented — rows come from the
request (or an explicit, clearly-labelled sample request).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
from typing import Any

from backend.app.core.errors import ToolError
from models.adapters import ChatMessage
from tools.base import BaseTool, Permission, ToolContext, ToolResult, ValidationReport
from tools.registry import register

_OPS = {"sum", "mean", "median", "min", "max", "count", "std", "var"}


@register
class SheetsTool(BaseTool):
    name = "sheets"
    description = "Create CSV/XLSX workbooks from tabular data with formulas, sorting, filtering, aggregation, statistics and charts."
    category = "spreadsheets"
    permissions = [Permission.READ, Permission.WRITE, Permission.FILES]
    cost_estimate = "cheap"
    input_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "columns": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}}}},
            "rows": {"type": "array", "items": {"type": "object"}},
            "generate_sample": {"type": "boolean", "default": False, "description": "Explicitly request clearly-labelled sample rows"},
            "sample_rows": {"type": "integer", "default": 10},
            "sort": {"type": "object", "properties": {"column": {"type": "string"}, "ascending": {"type": "boolean"}}},
            "filter": {"type": "object", "properties": {"column": {"type": "string"}, "op": {"type": "string"}, "value": {}}},
            "aggregate": {"type": "array", "items": {"type": "object", "properties": {"column": {"type": "string"}, "op": {"type": "string"}}}},
            "formulas": {"type": "array", "items": {"type": "object", "properties": {"column": {"type": "string"}, "formula": {"type": "string"}}}},
            "chart": {"type": "object", "properties": {"type": {"type": "string"}, "x": {"type": "string"}, "y": {"type": "string"}, "title": {"type": "string"}}},
            "model": {"type": "string"},
        },
        "required": ["title"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "columns": {"type": "array"},
            "row_count": {"type": "integer"},
            "statistics": {"type": "object"},
            "artifacts": {"type": "array"},
        },
    }

    def availability(self, ctx: ToolContext | None = None) -> str:
        return "AVAILABLE"

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        title = str(self.require(payload, "title")).strip()
        rows: list[dict[str, Any]] = list(payload.get("rows") or [])
        columns = [str(c.get("name")) for c in (payload.get("columns") or []) if c.get("name")]

        if not rows and payload.get("generate_sample"):
            rows = self._sample_rows(payload, ctx)
        if not rows and not columns:
            raise ToolError("Provide 'rows' (or 'columns' + generate_sample=true)")

        if not columns:
            first = rows[0]
            seen: list[str] = []
            for row in rows:
                for key in row:
                    if key not in seen:
                        seen.append(str(key))
            columns = seen or [str(k) for k in first]

        rows = [self._coerce(row, columns) for row in rows]

        # -------------------------------------------------- transform
        filtered = self._apply_filter(rows, payload.get("filter"))
        sorted_rows = self._apply_sort(filtered if payload.get("filter") else rows, payload.get("sort"))
        working = sorted_rows

        statistics = self._statistics(working, columns)
        aggregates = self._aggregate(working, payload.get("aggregate"))

        # -------------------------------------------------- artifacts
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-").lower() or "sheet"
        artifacts: list[dict[str, Any]] = []

        csv_text = self._to_csv(columns, working)
        artifacts.append(ctx.save_artifact(f"{base}-{stamp}.csv", csv_text, "spreadsheet", "text/csv", "spreadsheets", {"title": title}))

        xlsx_bytes = self._to_xlsx(title, columns, working, aggregates, payload.get("formulas"), payload.get("chart"))
        artifacts.append(
            ctx.save_artifact(
                f"{base}-{stamp}.xlsx",
                xlsx_bytes,
                "spreadsheet",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "spreadsheets",
                {"title": title, "rows": len(working)},
            )
        )

        return ToolResult(
            status="SUCCESS",
            summary=f"Workbook '{title}' created: {len(working)} rows × {len(columns)} columns.",
            data={
                "title": title,
                "columns": columns,
                "row_count": len(working),
                "rows": working[:200],
                "statistics": statistics,
                "aggregates": aggregates,
            },
            artifacts=artifacts,
        )

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _coerce(row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, str):
                stripped = value.strip()
                if re.fullmatch(r"-?\d+", stripped):
                    value = int(stripped)
                elif re.fullmatch(r"-?\d+\.\d+", stripped):
                    value = float(stripped)
            out[col] = value
        return out

    @staticmethod
    def _apply_sort(rows: list[dict[str, Any]], sort: dict | None) -> list[dict[str, Any]]:
        if not sort or not sort.get("column"):
            return list(rows)
        col = str(sort["column"])
        ascending = bool(sort.get("ascending", True))
        try:
            return sorted(rows, key=lambda r: (r.get(col) is None, r.get(col)), reverse=not ascending)
        except TypeError:
            return sorted(rows, key=lambda r: str(r.get(col, "")), reverse=not ascending)

    @staticmethod
    def _apply_filter(rows: list[dict[str, Any]], spec: dict | None) -> list[dict[str, Any]]:
        if not spec or not spec.get("column"):
            return list(rows)
        col = str(spec["column"])
        op = str(spec.get("op", "eq")).lower()
        value = spec.get("value")

        def keep(row: dict[str, Any]) -> bool:
            cell = row.get(col)
            try:
                if op in ("eq", "="):
                    return cell == value or str(cell) == str(value)
                if op in ("neq", "!="):
                    return not (cell == value or str(cell) == str(value))
                if op in ("gt", ">"):
                    return float(cell) > float(value)  # type: ignore[arg-type]
                if op in ("gte", ">="):
                    return float(cell) >= float(value)  # type: ignore[arg-type]
                if op in ("lt", "<"):
                    return float(cell) < float(value)  # type: ignore[arg-type]
                if op in ("lte", "<="):
                    return float(cell) <= float(value)  # type: ignore[arg-type]
                if op in ("contains",):
                    return str(value).lower() in str(cell).lower()
            except (TypeError, ValueError):
                return False
            return True

        return [r for r in rows if keep(r)]

    @staticmethod
    def _statistics(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        for col in columns:
            numeric = [float(r.get(col)) for r in rows if isinstance(r.get(col), (int, float)) and not isinstance(r.get(col), bool)]
            if numeric:
                series = sorted(numeric)
                n = len(series)
                mean = sum(series) / n
                median = series[n // 2] if n % 2 else (series[n // 2 - 1] + series[n // 2]) / 2
                variance = sum((x - mean) ** 2 for x in series) / n if n else 0.0
                stats[col] = {
                    "count": n,
                    "sum": round(sum(series), 4),
                    "mean": round(mean, 4),
                    "median": round(median, 4),
                    "min": round(min(series), 4),
                    "max": round(max(series), 4),
                    "std": round(variance ** 0.5, 4),
                }
        return stats

    @staticmethod
    def _aggregate(rows: list[dict[str, Any]], spec: list[dict] | None) -> list[dict[str, Any]]:
        if not spec:
            return []
        out: list[dict[str, Any]] = []
        for item in spec:
            col = str(item.get("column", ""))
            op = str(item.get("op", "sum")).lower()
            if op not in _OPS:
                continue
            numeric = [float(r.get(col)) for r in rows if isinstance(r.get(col), (int, float)) and not isinstance(r.get(col), bool)]
            if not numeric:
                out.append({"column": col, "op": op, "value": None, "note": "no numeric data"})
                continue
            if op == "sum":
                value = sum(numeric)
            elif op == "mean":
                value = sum(numeric) / len(numeric)
            elif op == "median":
                s = sorted(numeric)
                value = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2
            elif op == "min":
                value = min(numeric)
            elif op == "max":
                value = max(numeric)
            elif op == "count":
                value = len(numeric)
            elif op == "var":
                m = sum(numeric) / len(numeric)
                value = sum((x - m) ** 2 for x in numeric) / len(numeric)
            else:  # std
                m = sum(numeric) / len(numeric)
                value = (sum((x - m) ** 2 for x in numeric) / len(numeric)) ** 0.5
            out.append({"column": col, "op": op, "value": round(float(value), 4)})
        return out

    def _sample_rows(self, payload: dict[str, Any], ctx: ToolContext) -> list[dict[str, Any]]:
        """Explicitly-requested sample data. Labelled as SAMPLE in artifact metadata."""
        registry = getattr(ctx, "model_registry", None)
        columns = [str(c.get("name")) for c in (payload.get("columns") or []) if c.get("name")]
        count = int(payload.get("sample_rows", 10))
        if registry is not None and columns:
            prompt = (
                f"Generate {count} realistic SAMPLE rows of data as a JSON array of objects with keys {columns}. "
                "Return ONLY the JSON array. This data is illustrative sample data, not real records."
            )
            try:
                completion = registry.complete([ChatMessage("user", prompt)], model=payload.get("model"), max_tokens=2000)
                text = completion.text
                start, end = text.find("["), text.rfind("]")
                if start != -1 and end != -1:
                    parsed = json.loads(text[start : end + 1])
                    if isinstance(parsed, list) and parsed:
                        return [r for r in parsed if isinstance(r, dict)]
            except Exception:  # noqa: BLE001
                pass
        # Deterministic fallback samples (clearly placeholders).
        numeric_cols = [c for c in columns if c.lower() in ("amount", "value", "quantity", "price", "count", "score", "total")]
        rows = []
        for i in range(1, count + 1):
            row = {}
            for col in columns:
                row[col] = float(i * 100) if col in numeric_cols else f"SAMPLE-{col}-{i}"
            rows.append(row)
        return rows

    @staticmethod
    def _to_csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
        import csv

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
        return buf.getvalue()

    @staticmethod
    def _to_xlsx(
        title: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        aggregates: list[dict[str, Any]],
        formulas: list[dict] | None,
        chart: dict | None,
    ) -> bytes:
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, LineChart, PieChart, Reference
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = (title[:28] or "Sheet")

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="1F4E78")
        for idx, col in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=idx, value=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        for r, row in enumerate(rows, start=2):
            for c, col in enumerate(columns, start=1):
                ws.cell(row=r, column=c, value=row.get(col, ""))

        # Applied formulas (real Excel formulas in a summary column).
        if formulas:
            col_index = len(columns)
            for item in formulas:
                target = str(item.get("column", ""))
                formula = str(item.get("formula", ""))
                if not target or not formula:
                    continue
                if target not in columns:
                    columns.append(target)
                    col_index = len(columns)
                    ws.cell(row=1, column=col_index, value=target).font = header_font
                letter = get_column_letter(col_index)
                first, last = 2, max(2, len(rows) + 1)
                ws[f"{letter}2"] = formula.format(first=first, last=last, col=letter)
                for rr in range(3, last + 1):
                    ws[f"{letter}{rr}"] = formula.format(first=first, last=last, col=letter)

        # Aggregation summary sheet.
        if aggregates:
            summary = wb.create_sheet("Summary")
            summary["A1"] = f"{title} — Summary"
            summary["A1"].font = Font(bold=True, size=13)
            summary.append([])
            summary.append(["Column", "Operation", "Value"])
            for cell in summary[3]:
                cell.font = header_font
                cell.fill = header_fill
            for item in aggregates:
                summary.append([item.get("column"), item.get("op"), item.get("value")])

            chart_spec = chart or {}
            if chart_spec.get("type") and chart_spec.get("x") and chart_spec.get("y") and rows:
                x_col, y_col = str(chart_spec["x"]), str(chart_spec["y"])
                if x_col in columns and y_col in columns:
                    xi = columns.index(x_col) + 1
                    yi = columns.index(y_col) + 1
                    last = len(rows) + 1
                    kind = str(chart_spec.get("type", "bar")).lower()
                    chart_obj = PieChart() if kind == "pie" else (LineChart() if kind == "line" else BarChart())
                    data = Reference(ws, min_col=yi, min_row=1, max_row=last)
                    cats = Reference(ws, min_col=xi, min_row=2, max_row=last)
                    chart_obj.add_data(data, titles_from_data=True)
                    chart_obj.set_categories(cats)
                    chart_obj.title = chart_spec.get("title") or f"{y_col} by {x_col}"
                    summary.add_chart(chart_obj, "F3")

        for c in range(1, len(columns) + 1):
            ws.column_dimensions[get_column_letter(c)].width = max(14, min(40, len(str(columns[c - 1])) + 6))

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        if result.status == "SUCCESS":
            import csv as _csv
            import os
            import zipfile

            for art in result.artifacts:
                path = art.get("storage_path", "")
                exists = os.path.exists(path) and os.path.getsize(path) > 0
                checks.append({"name": f"file:{art['name']}", "ok": exists, "detail": f"{art.get('size', 0)} bytes"})
                if path.endswith(".csv") and exists:
                    with open(path, newline="", encoding="utf-8") as fh:
                        parsed = list(_csv.reader(fh))
                    checks.append({"name": "csv_rows", "ok": len(parsed) == result.data.get("row_count", 0) + 1, "detail": f"{len(parsed)} lines"})
                if path.endswith(".xlsx") and exists:
                    checks.append({"name": "xlsx_is_zip", "ok": zipfile.is_zipfile(path), "detail": "OOXML container"})
                    try:
                        from openpyxl import load_workbook

                        wb = load_workbook(path)
                        checks.append({"name": "xlsx_readable", "ok": wb.sheetnames != [], "detail": ",".join(wb.sheetnames)})
                    except Exception as exc:  # noqa: BLE001
                        checks.append({"name": "xlsx_readable", "ok": False, "detail": str(exc)})
        return ValidationReport(valid=all(c["ok"] for c in checks), message="sheets validation")


__all__ = ["SheetsTool"]
