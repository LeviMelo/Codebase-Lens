# AI Handoff Workflow

CBL exists to make chatbot-assisted coding less dependent on memory and more dependent on current local repository evidence.

## Recommended handoff flow

Run:

~~~powershell
python -m codebase_lens pack --issue "precise coding task or review question" --budget 24000 --no-archive
~~~

Then give the chatbot the relevant files from:

~~~text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/handoff_projection.json
.codecontext/latest/graph_summary.md
~~~

Use `ai_handoff.md` for broad project state.

Use `handoff_projection.md` when the chatbot needs a compact dependency-oriented reading plan.

Use `handoff_projection.json` when the chatbot should reason over machine-readable graph edges, roles, source prefixes, unresolved calls, and representative dependencies.

Use `graph_summary.md` when the chatbot needs a repository-level evidence graph overview.

## Changed-scope handoff

For uncommitted work:

~~~powershell
python -m codebase_lens pack --changed --issue "review current uncommitted changes" --budget 24000 --no-archive
~~~

Changed-scope packs are useful for:

- reviewing a patch;
- explaining what changed;
- asking whether a slice respects the architecture;
- generating the next updater script from current repository state.

## Focused graph handoff

For a specific symbol:

~~~powershell
python -m codebase_lens graph --symbol SYMBOL_NAME --depth 1 --limit 60 --no-archive
~~~

For a specific file:

~~~powershell
python -m codebase_lens graph --path src/codebase_lens/path/to/file.py --depth 1 --limit 60 --no-archive
~~~

For changed work:

~~~powershell
python -m codebase_lens graph --changed --depth 1 --limit 80 --no-archive
~~~

## What to tell the chatbot

A good prompt should say:

~~~text
Use the attached CBL output as current repository evidence. Treat path and line evidence as more reliable than memory. Do not assume files or symbols exist unless they appear in the CBL reports. Preserve the architecture contract. Provide changes as updater scripts where possible.
~~~

For implementation slices, prefer:

~~~text
Write a repo-root updater script under scripts/dev/updaters/. The updater must modify production code under src/codebase_lens/ where appropriate, add or update audits/tests, parse every modified Python file before exiting, and provide exact validation commands.
~~~

## What not to do

Do not paste raw source trees when CBL reports are sufficient.

Do not ask a chatbot to infer the current codebase from memory.

Do not treat `.codecontext/latest/` as stable storage. It is overwritten by later commands.

Do not ask the chatbot to weaken the architecture contract to pass tests unless the contract itself is demonstrably wrong.

## Audit reports

Stable release audit reports are written to:

~~~text
.codecontext/audits/
~~~

These are sanitized before persistence. They are intended to be pasteable diagnostics for command-surface, fixture-matrix, and release-safety gates.
