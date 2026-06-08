# CBL Release Checklist

This checklist defines the current v0.1 release gate.

Run from repository root:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path
~~~

## Phase audits

Run:

~~~powershell
python .\scripts\dev\audits\audit_phase24_documentation_workflow.py
python .\scripts\dev\audits\audit_phase23_audit_report_sanitization.py
python .\scripts\dev\audits\audit_phase22_release_safety.py
python .\scripts\dev\audits\audit_phase21_release_fixture_matrix.py
python .\scripts\dev\audits\audit_phase20_public_command_stability.py
python .\scripts\dev\audits\audit_phase19_projection_roles_imports.py
python .\scripts\dev\audits\audit_phase18_projection_dedup.py
python .\scripts\dev\audits\audit_phase17_projection_noise.py
python .\scripts\dev\audits\audit_phase16_projection_generality.py
python .\scripts\dev\audits\audit_phase15_projection_semantics.py
python .\scripts\dev\audits\audit_phase14_projection_relevance.py
python .\scripts\dev\audits\audit_phase13_handoff_projection_sidecar.py
python .\scripts\dev\audits\audit_phase12_graph_query.py
python .\scripts\dev\audits\audit_phase11_evidence_graph.py
python .\scripts\dev\audits\audit_phase10_symbol_graph.py
python .\scripts\dev\audits\audit_v01_readiness.py
python .\scripts\dev\audits\audit_phase8_snapshot_pack.py
~~~

## Contract

Run:

~~~powershell
python -m codebase_lens contract --no-archive
~~~

Expected:

~~~text
CBL contract: OK
Violations: 0
Errors: 0
~~~

## Tests

Run:

~~~powershell
python -m pytest
~~~

Expected: all tests pass.

## Whitespace

Run:

~~~powershell
git diff --check
~~~

Expected: no output.

## Stable release audit reports

Run:

~~~powershell
python .\scripts\dev\audits\audit_phase20_public_command_stability.py
python .\scripts\dev\audits\audit_phase21_release_fixture_matrix.py
python .\scripts\dev\audits\audit_phase22_release_safety.py
python .\scripts\dev\audits\audit_phase23_audit_report_sanitization.py
~~~

Expected stable reports:

~~~text
.codecontext/audits/command_surface_audit.json
.codecontext/audits/fixture_matrix_audit.json
.codecontext/audits/release_safety_audit.json
~~~

These reports must not contain raw local temp or user-home path fragments.

## Functional smoke test

Run:

~~~powershell
python -m codebase_lens pack --issue "v0.1 release smoke" --budget 24000 --no-archive
python -m codebase_lens graph --symbol write_handoff_pack --depth 1 --limit 60 --no-archive
python -m codebase_lens file src/codebase_lens/cli.py --lines 1:80 --no-archive
~~~

Expected:

~~~text
CBL pack: OK
CBL graph: OK
CBL file excerpt emitted with redaction enabled
~~~

## Commit rule

Only commit after:

~~~text
- relevant new audit passes;
- command-surface gate passes;
- fixture matrix passes;
- release safety audit passes;
- audit report sanitization passes;
- architecture contract passes;
- full pytest passes;
- git diff --check is clean.
~~~
