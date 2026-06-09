# CBL AI Handoff Workflow

CBL exists to make AI-mediated development evidence-driven. Do not rely on a chatbot's memory of a repository when the codebase has changed.

## Standard handoff

```powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl pack --issue "state the concrete coding task" --budget 32000 --no-archive
```

Give the assistant:

```text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/manifest.json
```

## Large-source search handoff

Use `dump` when the assistant or platform can search a large uploaded file and needs full source text.

```powershell
cbl dump --no-archive
```

Give the assistant:

```text
.codecontext/latest/codebase_dump.md
.codecontext/latest/codebase_dump_index.json
```

The dump is intentionally source-first. Included files are not truncated. Data files, generated dump files, `.codecontext/`, binaries, and hard-excluded paths remain excluded.

## Diff review handoff

Use `diffdump` when the question is about what changed between Git refs.

```powershell
cbl diffdump --from v0.1.0 --to HEAD --symbols --no-archive
```

Give the assistant:

```text
.codecontext/latest/diff_dump.md
.codecontext/latest/diff_dump_index.json
.codecontext/latest/diff.json
```

## Follow-up context

For targeted follow-up:

```powershell
cbl symbol SomeFunction --path src/package/module.py --context 80 --no-archive
cbl file src/package/module.py --lines 1:240 --no-archive
cbl graph --symbol SomeFunction --depth 1 --limit 100 --no-archive
cbl callers SomeFunction --no-archive
```

Treat exact line-numbered excerpts as authoritative. Treat heuristic graph and likely-test findings as provisional.
