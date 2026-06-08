# Local Codebase Lens

Local Codebase Lens, abbreviated CBL, is a local-only repository inspection tool for AI-assisted coding work.

CBL does not patch code, generate application changes, upload repository contents, or execute the target application package. Its job is to inspect a local repository and emit structured, evidence-backed reports under `.codecontext/` so a developer can hand current repository context to a chatbot without relying on stale memory.

## Current status

This repository is at the v0.1 release-candidate stage.

The current implementation includes:

- repository root detection with explicit `--repo` support;
- hard-exclusion of `.git`, `.codecontext`, virtual environments, data/output/cache folders, binary artifacts, and sensitive file classes;
- static Python symbol extraction;
- static import extraction with project import resolution;
- static CLI, route, test, caller, changed-file, changed-symbol, symbol-graph, evidence-graph, and graph-query reports;
- AI handoff pack generation;
- handoff projection sidecar reports;
- architecture contract validation;
- command-surface release gate;
- external fixture-matrix release gate;
- hostile safety-fixture release gate;
- stable sanitized audit reports under `.codecontext/audits/`.

## Installation for local development

From the repository root:

~~~powershell
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m codebase_lens --help
~~~

CBL is currently intended to be run from source during development. The canonical module entrypoint is:

~~~powershell
python -m codebase_lens <command> [options]
~~~

## Basic usage

Create a full AI handoff pack for the current repository:

~~~powershell
python -m codebase_lens pack --issue "describe the coding task here" --budget 24000 --no-archive
~~~

Create a changed-scope pack:

~~~powershell
python -m codebase_lens pack --changed --issue "review current uncommitted changes" --budget 24000 --no-archive
~~~

Run the architecture contract:

~~~powershell
python -m codebase_lens contract --no-archive
~~~

Query the evidence graph:

~~~powershell
python -m codebase_lens graph --symbol write_handoff_pack --depth 1 --limit 60 --no-archive
~~~

Run against another local repository:

~~~powershell
python -m codebase_lens pack --repo C:\path\to\other\repo --issue "handoff for external repo" --budget 24000 --no-archive
~~~

## Main outputs

The latest command writes to:

~~~text
.codecontext/latest/
~~~

Important pack outputs include:

~~~text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/handoff_projection.json
.codecontext/latest/pack_index.json
.codecontext/latest/evidence_graph.json
.codecontext/latest/graph_summary.md
.codecontext/latest/symbol_graph.json
.codecontext/latest/symbol_graph.md
.codecontext/latest/file_inventory.json
.codecontext/latest/manifest.json
~~~

Release audit reports are also persisted under:

~~~text
.codecontext/audits/
~~~

These stable audit reports are sanitized before persistence and should not contain raw local user-home or temp-directory paths.

## Public commands

The current public command surface is:

~~~text
doctor
snapshot
tree
symbols
imports
cli
routes
tests
diff
changed
file
symbol
callers
contract
pack
clean
graph
~~~

The public command stability audit enforces parity between `PUBLIC_COMMANDS` and argparse subcommands.

## Safety model

CBL is intentionally conservative.

By default it rejects paths outside the repository root, refuses hard-excluded paths, avoids scanning `.codecontext`, avoids common data/output/cache directories, skips binary files, skips oversized files, and redacts secret-like assignments in emitted text.

CBL analyzes Python source statically. It must not import or execute the target repository package to discover symbols, CLI handlers, routes, tests, or imports.

## Development doctrine

Production behavior belongs under `src/codebase_lens/`.

Developer scripts under `scripts/dev/` may orchestrate updates and audits, but they must not become the product implementation. Audits should protect architecture and behavior; they should not replace production code.

## Release gates

The current release gate sequence is documented in `docs/RELEASE_CHECKLIST.md`.

For normal development, run:

~~~powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python .\scripts\dev\audits\audit_phase24_documentation_workflow.py
python .\scripts\dev\audits\audit_phase23_audit_report_sanitization.py
python .\scripts\dev\audits\audit_phase22_release_safety.py
python .\scripts\dev\audits\audit_phase21_release_fixture_matrix.py
python .\scripts\dev\audits\audit_phase20_public_command_stability.py
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
~~~
