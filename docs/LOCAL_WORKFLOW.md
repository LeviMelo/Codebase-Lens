# CBL Local Workflow

This document defines the local workflow for developing and using Local Codebase Lens.

## Environment

Expected development environment:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path
~~~

Check the command surface:

~~~powershell
python -m codebase_lens --help
~~~

## Working on CBL itself

Use CBL against its own repository when planning or reviewing implementation work:

~~~powershell
python -m codebase_lens pack --issue "current CBL development task" --budget 24000 --no-archive
~~~

Then inspect:

~~~text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/handoff_projection.json
.codecontext/latest/evidence_graph.json
.codecontext/latest/graph_summary.md
~~~

## Working on another repository

Use `--repo` rather than changing directories when you want CBL to inspect another local project:

~~~powershell
python -m codebase_lens pack --repo C:\path\to\target\repo --issue "target repo task" --budget 24000 --no-archive
~~~

CBL should write outputs inside the target repository:

~~~text
C:\path\to\target\repo\.codecontext\latest\
~~~

## Common commands

Repository health:

~~~powershell
python -m codebase_lens doctor --no-archive
~~~

Full snapshot:

~~~powershell
python -m codebase_lens snapshot --budget 24000 --no-archive
~~~

AI handoff pack:

~~~powershell
python -m codebase_lens pack --issue "describe the task" --budget 24000 --no-archive
~~~

Changed-scope AI handoff pack:

~~~powershell
python -m codebase_lens pack --changed --issue "review current changes" --budget 24000 --no-archive
~~~

Specific file excerpt:

~~~powershell
python -m codebase_lens file src/codebase_lens/cli.py --lines 1:120 --no-archive
~~~

Symbol excerpt:

~~~powershell
python -m codebase_lens symbol write_handoff_pack --first --no-archive
~~~

Static callers:

~~~powershell
python -m codebase_lens callers write_handoff_pack --no-archive
~~~

Evidence graph query:

~~~powershell
python -m codebase_lens graph --symbol write_handoff_pack --depth 1 --limit 60 --no-archive
~~~

Architecture contract:

~~~powershell
python -m codebase_lens contract --no-archive
~~~

## Output behavior

`.codecontext/latest/` is intentionally transient. Each command may replace it.

`.codecontext/audits/` is stable for release audit reports. These reports are sanitized and are safer to paste into chats than raw temp-path-bearing diagnostics.

## Before committing

Run the relevant new audit first, then the release gate subset:

~~~powershell
python .\scripts\dev\audits\audit_phase24_documentation_workflow.py
python .\scripts\dev\audits\audit_phase23_audit_report_sanitization.py
python .\scripts\dev\audits\audit_phase22_release_safety.py
python .\scripts\dev\audits\audit_phase21_release_fixture_matrix.py
python .\scripts\dev\audits\audit_phase20_public_command_stability.py
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
~~~
