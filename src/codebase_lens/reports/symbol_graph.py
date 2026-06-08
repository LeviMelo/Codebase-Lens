from __future__ import annotations

from pathlib import Path

from codebase_lens.analyzers.symbol_graph import (
    SymbolGraphResult,
    render_symbol_graph_markdown,
    symbol_graph_payload,
)
from codebase_lens.reports.json import write_json_report
from codebase_lens.reports.manifest import OutputLayout
from codebase_lens.core.redaction import redact_console_text


def write_symbol_graph_reports(layout: OutputLayout, result: SymbolGraphResult) -> dict[str, str]:
    json_path = layout.latest_dir / "symbol_graph.json"
    markdown_path = layout.latest_dir / "symbol_graph.md"

    write_json_report(json_path, symbol_graph_payload(result))
    markdown_path.write_text(
        redact_console_text(render_symbol_graph_markdown(result)),
        encoding="utf-8",
        newline="\n",
    )

    return {
        "symbol_graph_json": ".codecontext/latest/symbol_graph.json",
        "symbol_graph_md": ".codecontext/latest/symbol_graph.md",
    }
