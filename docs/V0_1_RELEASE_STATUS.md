# CBL v0.1 Release Status

Local Codebase Lens is now at v0.1 release-candidate closure.

This release is a local-only repository evidence engine for AI-assisted coding. It inspects a local repository, builds static evidence artifacts, and emits AI handoff reports under `.codecontext/`.

## Release Identity

- Tool name: Local Codebase Lens
- Abbreviation: CBL
- Version target: v0.1
- Execution model: local-only
- Primary entrypoint: `python -m codebase_lens`
- Output root: `.codecontext/`
- Stable audit report root: `.codecontext/audits/`

## Implemented Public Command Surface

The v0.1 public command surface contains 17 commands:

- `doctor`
- `snapshot`
- `tree`
- `symbols`
- `imports`
- `cli`
- `routes`
- `tests`
- `diff`
- `changed`
- `file`
- `symbol`
- `callers`
- `contract`
- `pack`
- `clean`
- `graph`

The command-surface gate enforces exact parity between `PUBLIC_COMMANDS` and argparse subcommands.

## Implemented Evidence Capabilities

CBL v0.1 implements:

- safe repository-root detection;
- explicit `--repo` support for external local repositories;
- hard-excluded path handling;
- binary and oversized-file exclusion;
- redaction of secret-like assignments and private-key blocks;
- static Python symbol extraction;
- static import extraction and project import resolution;
- static CLI command discovery;
- static route discovery;
- test inventory and fixture discovery;
- Git changed-file and changed-symbol mapping;
- file and symbol excerpts;
- static caller search;
- symbol graph generation;
- evidence graph generation;
- scoped graph query;
- AI handoff pack generation;
- handoff projection sidecar reports;
- architecture contract validation;
- stable sanitized release audit reports.

## Canonical v0.1 Report Outputs

The current report contract includes:

- `.codecontext/latest/repo_snapshot.md`
- `.codecontext/latest/git_state.json`
- `.codecontext/latest/snapshot_index.json`
- `.codecontext/latest/file_inventory.json`
- `.codecontext/latest/repo_tree.txt`
- `.codecontext/latest/symbol_index.json`
- `.codecontext/latest/import_graph.json`
- `.codecontext/latest/cli_inventory.json`
- `.codecontext/latest/route_inventory.json`
- `.codecontext/latest/test_inventory.json`
- `.codecontext/latest/omissions.json`
- `.codecontext/latest/budget_report.json`
- `.codecontext/latest/diff.json`
- `.codecontext/latest/diff_summary.md`
- `.codecontext/latest/contract_audit.json`
- `.codecontext/latest/contract_audit.md`
- `.codecontext/latest/contract_report.json`
- `.codecontext/latest/ai_handoff.md`
- `.codecontext/latest/handoff_projection.md`
- `.codecontext/latest/handoff_projection.json`
- `.codecontext/latest/evidence_graph.json`
- `.codecontext/latest/graph_summary.md`
- `.codecontext/latest/symbol_graph.json`
- `.codecontext/latest/symbol_graph.md`
- `.codecontext/latest/graph_query.json`
- `.codecontext/latest/graph_query.md`
- `.codecontext/latest/manifest.json`

`contract_audit.json` is the canonical TDD-aligned contract output. `contract_report.json` is retained as a compatibility alias.

## Safety Invariants

CBL v0.1 must preserve these invariants:

- it must not import or execute the target repository package;
- it must reject paths that resolve outside the repository root;
- it must not recursively scan `.codecontext`;
- it must not scan `.env` files;
- it must not scan common data, output, cache, virtual-environment, or dependency folders;
- it must not leak raw secret markers into AI-facing artifacts;
- it must not write raw local temp or user-home paths into stable audit reports;
- it must keep production behavior under `src/codebase_lens/`;
- it must keep developer scripts as orchestration, not product implementation.

## Release Gates

The v0.1 release closure gate is:

~~~powershell
python .\scripts\dev\audits\audit_phase26_v01_release_closure.py
~~~

For a faster non-recursive test-mode gate:

~~~powershell
python .\scripts\dev\audits\audit_phase26_v01_release_closure.py --skip-pytest
~~~

The release gate validates:

- report contract parity;
- documentation workflow;
- audit report path sanitization;
- release safety hostile fixture;
- external fixture matrix;
- public command stability;
- architecture contract;
- functional snapshot, pack, graph, diff, and contract smoke checks;
- full pytest run unless `--skip-pytest` is supplied;
- `git diff --check`.

## Known v0.1 Boundaries

CBL v0.1 is intentionally static. It does not dynamically import the target project to discover runtime behavior.

The graph is evidence-oriented, not a full program-analysis graph. Dynamic dispatch, reflection, dependency injection, metaprogramming, generated code, and framework-specific runtime registration may be represented as unresolved or heuristic evidence.

Token budgeting is heuristic. The v0.1 estimator uses `max(1, file_size_bytes // 4)` and is intentionally simple.

CBL does not generate code patches. It generates repository evidence and handoff artifacts.

## Release Decision

CBL v0.1 is ready when `audit_phase26_v01_release_closure.py` passes, the architecture contract passes, all pytest tests pass, and `git diff --check` is clean.
