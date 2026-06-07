from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


BAD_LINES = {
    '            "symbol_graph_nodes": graph_result.counts.get("nodes", 0),\n',
    '            "symbol_graph_call_edges": graph_result.counts.get("call_edges", 0),\n',
    '            "symbol_graph_caller_edges": graph_result.counts.get("caller_edges", 0),\n',
    '        "symbol_graph_nodes": graph_result.counts.get("nodes", 0),\n',
    '        "symbol_graph_call_edges": graph_result.counts.get("call_edges", 0),\n',
    '        "symbol_graph_caller_edges": graph_result.counts.get("caller_edges", 0),\n',
}


GRAPH_COUNT_LINES = '''        "symbol_graph_nodes": graph_result.counts.get("nodes", 0),
        "symbol_graph_call_edges": graph_result.counts.get("call_edges", 0),
        "symbol_graph_caller_edges": graph_result.counts.get("caller_edges", 0),
'''


def remove_bad_graph_counts_from_omissions_report(text: str) -> str:
    start_marker = "def _write_omissions_report("
    end_marker = "\ndef _write_budget_report("

    start = text.find(start_marker)
    end = text.find(end_marker)

    if start == -1:
        raise RuntimeError("_write_omissions_report() not found in snapshot.py.")
    if end == -1 or end <= start:
        raise RuntimeError("_write_budget_report() marker not found after _write_omissions_report().")

    before = text[:start]
    block = text[start:end]
    after = text[end:]

    cleaned_lines = [line for line in block.splitlines(keepends=True) if line not in BAD_LINES]

    return before + "".join(cleaned_lines) + after


def ensure_graph_counts_in_snapshot_counts(text: str) -> str:
    graph_marker = "    graph_result = collect_symbol_graph(\n"
    counts_marker = "    counts = {\n"

    graph_pos = text.find(graph_marker)
    if graph_pos == -1:
        raise RuntimeError("collect_symbol_graph() call not found in write_snapshot_bundle().")

    counts_pos = text.find(counts_marker, graph_pos)
    if counts_pos == -1:
        raise RuntimeError("Final snapshot counts dict not found after collect_symbol_graph().")

    return_pos = text.find("\n    _write_snapshot_index(", counts_pos)
    if return_pos == -1:
        raise RuntimeError("_write_snapshot_index() marker not found after final counts dict.")

    before = text[:counts_pos]
    counts_block = text[counts_pos:return_pos]
    after = text[return_pos:]

    if "symbol_graph_nodes" in counts_block:
        return text

    omissions_line = '        "omissions": len(getattr(universe, "omissions", ())),\n'
    if omissions_line not in counts_block:
        raise RuntimeError("Final counts dict does not contain expected omissions line.")

    counts_block = counts_block.replace(omissions_line, omissions_line + GRAPH_COUNT_LINES, 1)

    return before + counts_block + after


def assert_no_graph_result_in_omissions_report(text: str) -> None:
    start = text.find("def _write_omissions_report(")
    end = text.find("\ndef _write_budget_report(", start)
    block = text[start:end]
    if "graph_result" in block:
        raise RuntimeError("graph_result still appears inside _write_omissions_report().")


def assert_graph_result_in_final_counts(text: str) -> None:
    graph_pos = text.find("    graph_result = collect_symbol_graph(\n")
    counts_pos = text.find("    counts = {\n", graph_pos)
    index_pos = text.find("\n    _write_snapshot_index(", counts_pos)
    block = text[counts_pos:index_pos]

    required = [
        '"symbol_graph_nodes": graph_result.counts.get("nodes", 0)',
        '"symbol_graph_call_edges": graph_result.counts.get("call_edges", 0)',
        '"symbol_graph_caller_edges": graph_result.counts.get("caller_edges", 0)',
    ]

    missing = [item for item in required if item not in block]
    if missing:
        raise RuntimeError(f"Final snapshot counts dict missing graph count fields: {missing}")


def main() -> int:
    path = ROOT / "src" / "codebase_lens" / "reports" / "snapshot.py"
    text = path.read_text(encoding="utf-8")

    text = remove_bad_graph_counts_from_omissions_report(text)
    text = ensure_graph_counts_in_snapshot_counts(text)

    assert_no_graph_result_in_omissions_report(text)
    assert_graph_result_in_final_counts(text)

    path.write_text(text, encoding="utf-8", newline="\n")

    print("Repair applied: graph_result counts moved out of _write_omissions_report and enforced in final snapshot counts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())