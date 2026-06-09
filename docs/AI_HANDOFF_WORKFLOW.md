# CBL AI Handoff Workflow

CBL exists to make AI-mediated development evidence-driven. Do not rely on a chatbot's memory of a repository when the codebase has changed.

## Standard handoff

~~~powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl pack --issue "state the concrete coding task" --budget 32000 --no-archive
~~~

Give the assistant:

~~~text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/manifest.json
~~~

## Large-source search handoff

Use `dump` when the assistant or platform can search a large uploaded file and needs full source text.

~~~powershell
cbl dump --no-archive
~~~

Give the assistant:

~~~text
.codecontext/latest/codebase_dump.md
.codecontext/latest/codebase_dump_index.json
~~~

The dump is intentionally source-first. Included files are not truncated. Data files, generated dump files, `.codecontext/`, binaries, and hard-excluded paths remain excluded.

## Diff review handoff

Use `diffdump` when the question is about what changed between Git refs.

~~~powershell
cbl diffdump --from v0.1.0 --to HEAD --symbols --no-archive
~~~

Give the assistant:

~~~text
.codecontext/latest/diff_dump.md
.codecontext/latest/diff_dump_index.json
.codecontext/latest/diff.json
~~~

## Follow-up context

For targeted follow-up:

~~~powershell
cbl symbol SomeFunction --path src/package/module.py --context 80 --no-archive
cbl file src/package/module.py --lines 1:240 --no-archive
cbl graph --symbol SomeFunction --depth 1 --limit 100 --no-archive
cbl callers SomeFunction --no-archive
~~~

Treat exact line-numbered excerpts as authoritative. Treat heuristic graph and likely-test findings as provisional.

## Evidence-first rule

Treat path and line evidence as more reliable than memory. Exact file paths, symbol definitions, line-numbered excerpts, and generated JSON records are the authority for AI-assisted work. Conversation memory is secondary and must be corrected when it conflicts with CBL evidence.

## Evidence-first sidecars

Treat path and line evidence as more reliable than memory. The Markdown sidecar `handoff_projection.md` is optimized for quick reading, while `handoff_projection.json` preserves the structured projection payload for deterministic inspection and downstream tooling.

## Evidence-first implementation protocol

Treat path and line evidence as more reliable than memory. When conversation memory conflicts with CBL artifacts, the artifact with repository-relative path and line evidence wins.

Use `ai_handoff.md` for the narrative task context. Use `handoff_projection.md` for a compact human-readable project projection. Use `handoff_projection.json` for deterministic inspection, downstream tooling, and exact machine-readable project-profile fields.

For implementation requests, instruct the AI to: Write a repo-root updater script. The updater must be executable from the repository root, must patch files deterministically, must parse modified Python files before exiting, and must avoid ad hoc manual edit instructions.

Preferred implementation prompt shape:

~~~text
Read the CBL handoff artifacts. Treat path and line evidence as more reliable than memory. Write a repo-root updater script that applies the requested change, updates tests/audits if needed, and exits only after modified Python files parse.
~~~
