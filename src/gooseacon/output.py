from __future__ import annotations

import csv
import io
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table


class Format(StrEnum):
    json = "json"
    csv = "csv"
    table = "table"


def render(data: Any, fmt: Format, rows: list[dict] | None = None) -> str:
    if fmt == Format.json:
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if rows is None:
        rows = data if isinstance(data, list) else [data]
    if not rows:
        return "" if fmt == Format.csv else "(no results)\n"
    columns = list(dict.fromkeys(key for row in rows for key in row))

    def cell(value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if fmt == Format.csv and isinstance(value, str):
            # GSC query/page text is untrusted. Stop spreadsheet formula execution;
            # numeric metrics (including negative values) remain unchanged.
            if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(
                ("\t", "\r", "\n")
            ):
                return "'" + value
        return "" if value is None else str(value)

    buffer = io.StringIO()
    if fmt == Format.csv:
        writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: cell(v) for k, v in row.items()} for row in rows)
    else:
        table = Table(*columns)
        for row in rows:
            table.add_row(*(cell(row.get(k)) for k in columns))
        Console(file=buffer, width=160, markup=False).print(table)
    return buffer.getvalue()


def emit(
    data: Any, fmt: Format, output: Path | None = None, rows: list[dict] | None = None
) -> None:
    text = render(data, fmt, rows)
    if output:
        output.write_text(text, encoding="utf-8")
    else:
        typer.echo(text, nl=False)
