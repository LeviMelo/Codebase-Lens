from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def patch_public_commands() -> None:
    path = ROOT / "src" / "codebase_lens" / "core" / "constants.py"
    text = path.read_text(encoding="utf-8")

    if '"graph"' in text or "'graph'" in text:
        return

    marker = '    "clean",\n)'
    replacement = '    "clean",\n    "graph",\n)'

    if marker not in text:
        raise RuntimeError("Could not find PUBLIC_COMMANDS closing marker in constants.py.")

    text = text.replace(marker, replacement, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_contract_cli_required_symbol() -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = path.read_text(encoding="utf-8")

    if '"_run_graph"' in text or "'_run_graph'" in text:
        return

    marker = '                    "_run_clean",\n'
    replacement = '                    "_run_clean",\n                    "_run_graph",\n'

    if marker not in text:
        raise RuntimeError("Could not find _run_clean required-symbol marker in architecture.py.")

    text = text.replace(marker, replacement, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_phase12_audit_constant_check() -> None:
    path = ROOT / "scripts" / "dev" / "audits" / "audit_phase12_graph_query.py"
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8")

    if "PUBLIC_COMMANDS does not include graph" in text:
        return

    marker = '''    help_result = run_cbl("--help")
    if help_result.returncode != 0:
        fail("cbl --help failed.")
    if "graph" not in help_result.stdout:
        fail("cbl --help does not expose graph command.")

'''

    replacement = '''    constants_text = (ROOT / "src" / "codebase_lens" / "core" / "constants.py").read_text(encoding="utf-8")
    if "\\"graph\\"" not in constants_text and "'graph'" not in constants_text:
        fail("PUBLIC_COMMANDS does not include graph.")

    cli_text = (ROOT / "src" / "codebase_lens" / "cli.py").read_text(encoding="utf-8")
    if "def _run_graph(" not in cli_text:
        fail("cli.py does not define _run_graph().")
    if "graph.set_defaults(handler=_run_graph)" not in cli_text:
        fail("graph parser does not bind handler=_run_graph.")

    help_result = run_cbl("--help")
    if help_result.returncode != 0:
        fail("cbl --help failed.")
    if "graph" not in help_result.stdout:
        fail("cbl --help does not expose graph command.")

'''

    if marker not in text:
        raise RuntimeError("Could not patch audit_phase12_graph_query.py command registration check.")

    text = text.replace(marker, replacement, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    patch_public_commands()
    patch_contract_cli_required_symbol()
    patch_phase12_audit_constant_check()

    print("Repair applied: graph added to PUBLIC_COMMANDS and contract/audit checks tightened.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())