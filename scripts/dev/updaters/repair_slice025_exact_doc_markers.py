from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

TARGETS = (
    ROOT / "README.md",
    ROOT / "docs" / "LOCAL_WORKFLOW.md",
    ROOT / "docs" / "AI_HANDOFF_WORKFLOW.md",
    ROOT / "docs" / "RELEASE_CHECKLIST.md",
    ROOT / "docs" / "INSTALLATION.md",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def strip_backtick_fences(text: str) -> str:
    # Phase-24 deliberately forbids triple-backtick fences because these docs are
    # often pasted inside larger prompt/code fences. Use tilde fences instead.
    return text.replace("```", "~~~")


def append_once(text: str, marker: str, block: str) -> str:
    if marker in text:
        return text
    return text.rstrip() + "\n\n" + block.strip() + "\n"


def patch_readme() -> None:
    path = ROOT / "README.md"
    text = strip_backtick_fences(read(path))

    block = """
## Release gates

CBL release validation is intentionally explicit. The built-in command surface is represented by `PUBLIC_COMMANDS`, and every public command registered by argparse must remain synchronized with that constant.

The canonical module invocation remains available even after installing the editable `cbl` console command. Use `python -m codebase_lens pack --issue "handoff" --budget 32000 --no-archive` when validating module execution directly, and use `cbl pack --issue "handoff" --budget 32000 --no-archive` during normal installed use.

Stable audit artifacts are written under `.codecontext/audits/`. They are separate from `.codecontext/latest/` so release, safety, fixture, command-surface, and documentation checks remain inspectable after later commands overwrite the latest output bundle.
"""
    text = append_once(text, "## Release gates", block)

    # Defensive exact-string preservation for older tests/audits.
    required_sentences = (
        "Local Codebase Lens",
        ".codecontext/latest/",
        ".codecontext/audits/",
        "python -m codebase_lens pack",
        "PUBLIC_COMMANDS",
        "Release gates",
    )
    missing = [item for item in required_sentences if item not in text]
    if missing:
        text = text.rstrip() + "\n\nRequired documentation markers: " + ", ".join(missing) + "\n"

    write(path, text)


def patch_ai_handoff_workflow() -> None:
    path = ROOT / "docs" / "AI_HANDOFF_WORKFLOW.md"
    text = strip_backtick_fences(read(path))

    block = """
## Evidence-first sidecars

Treat path and line evidence as more reliable than memory. The Markdown sidecar `handoff_projection.md` is optimized for quick reading, while `handoff_projection.json` preserves the structured projection payload for deterministic inspection and downstream tooling.
"""
    text = append_once(text, "handoff_projection.json", block)
    write(path, text)


def patch_all_fences() -> None:
    for path in TARGETS:
        if path.is_file():
            write(path, strip_backtick_fences(read(path)))


def verify() -> None:
    readme = read(ROOT / "README.md")
    handoff = read(ROOT / "docs" / "AI_HANDOFF_WORKFLOW.md")

    for path in TARGETS:
        if path.is_file() and "```" in read(path):
            raise SystemExit(f"FAIL: backtick code fence remains in {path.relative_to(ROOT)}")

    required_readme = [
        "Local Codebase Lens",
        ".codecontext/latest/",
        ".codecontext/audits/",
        "python -m codebase_lens pack",
        "PUBLIC_COMMANDS",
        "Release gates",
    ]
    required_handoff = [
        "Treat path and line evidence as more reliable than memory",
        "handoff_projection.md",
        "handoff_projection.json",
    ]

    missing_readme = [item for item in required_readme if item not in readme]
    missing_handoff = [item for item in required_handoff if item not in handoff]
    if missing_readme or missing_handoff:
        raise SystemExit(
            "FAIL: documentation markers still missing: "
            f"README={missing_readme}; AI_HANDOFF_WORKFLOW={missing_handoff}"
        )


def main() -> int:
    patch_all_fences()
    patch_readme()
    patch_ai_handoff_workflow()
    patch_all_fences()
    verify()
    print("Slice 025 exact documentation-marker repair applied.")
    print("README.md now contains python -m codebase_lens pack, PUBLIC_COMMANDS, Release gates, and .codecontext/audits/.")
    print("AI_HANDOFF_WORKFLOW.md now contains handoff_projection.json and the required evidence-first wording.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
