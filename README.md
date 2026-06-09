# Local Codebase Lens (CBL)

Local Codebase Lens is a local static repository-evidence tool for AI-assisted coding. It scans a repository from the current working directory, builds source-grounded reports, and writes them under `.codecontext/` so a chatbot can inspect the project with less guessing and less stale-memory drift.

CBL is local-only and does not upload your code. Review generated AI handoff reports before sharing them.

## What CBL does

CBL builds an evidence package from local files and Git state. It can produce repository snapshots, source trees, Python symbol indexes, import indexes, static CLI and route inventories, test inventories, changed-file reports, changed-symbol reports, graph neighborhoods, AI handoff packs, full source dumps, and Git diff dumps.

CBL does not import or execute the target repository. It reads text, parses Python with `ast`, runs Git commands, applies hard exclusions, redacts secret-like values before report persistence, and reports omitted files explicitly.

The main commands are:

~~~text
cbl doctor
cbl snapshot
cbl tree
cbl symbols
cbl imports
cbl cli
cbl routes
cbl tests
cbl diff
cbl changed
cbl file
cbl symbol
cbl callers
cbl contract
cbl pack
cbl clean
cbl graph
cbl dump
cbl diffdump
~~~

## Installation for PowerShell

The preferred installation is an editable Python package inside the dedicated Conda environment.

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
python -m pip install -e .
cbl --help
cbl doctor --no-archive
~~~

After this, `cbl` is available from any directory while `cbl-dev` is active. This is the correct meaning of "global" for this project: the command is installed into the environment's `Scripts` directory, and that directory is placed on `PATH` when the environment is activated.

Use it from another repository like this:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\SomeOtherRepo
conda activate cbl-dev
cbl doctor --no-archive
cbl pack --issue "review this codebase for architecture and implementation risks" --budget 32000 --no-archive
~~~

Without activating the environment, use:

~~~powershell
conda run -n cbl-dev cbl doctor --no-archive
conda run -n cbl-dev cbl pack --repo C:\path\to\repo --issue "handoff" --budget 32000 --no-archive
~~~

Do not solve this by copying CBL source files into random PATH folders. The package entry point is the canonical launcher.

## Normal AI handoff workflow

Generate a fresh pack before asking a chatbot to modify or review a project:

~~~powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl pack --issue "implement the requested change without violating the architecture" --budget 32000 --no-archive
~~~

Then provide these files to the chatbot:

~~~text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/manifest.json
~~~

For larger or retrieval-oriented workflows, also generate a full source dump:

~~~powershell
cbl dump --no-archive
~~~

Main output:

~~~text
.codecontext/latest/codebase_dump.md
.codecontext/latest/codebase_dump_index.json
~~~

For changes between Git refs:

~~~powershell
cbl diffdump --from HEAD~1 --to HEAD --symbols --no-archive
~~~

Main output:

~~~text
.codecontext/latest/diff_dump.md
.codecontext/latest/diff_dump_index.json
~~~

## Important commands

`cbl snapshot` writes a broad repository state bundle.

~~~powershell
cbl snapshot --budget 32000 --no-archive
~~~

`cbl pack` writes the primary AI handoff pack.

~~~powershell
cbl pack --issue "describe the intended coding task" --budget 32000 --no-archive
~~~

`cbl graph` writes a scoped graph neighborhood around a symbol, path, module, or changed files.

~~~powershell
cbl graph --symbol write_snapshot_bundle --depth 1 --limit 100 --unresolved seed --no-archive
~~~

`cbl dump` writes a Markdown source corpus. It is source-first and untruncated for included files.

~~~powershell
cbl dump --no-archive
cbl dump --include-untracked --out-file codebase_dump.md --no-archive
~~~

`cbl diffdump` writes a Markdown patch corpus for a Git comparison.

~~~powershell
cbl diffdump --from v0.1.0 --to HEAD --symbols --unified 5 --no-archive
~~~

`cbl contract` checks CBL against its built-in architecture contract.

~~~powershell
cbl contract --no-archive
~~~

## Output layout

CBL writes the current command output to:

~~~text
.codecontext/latest/
~~~

Unless `--no-archive` is used, CBL also copies the latest output to:

~~~text
.codecontext/runs/<timestamp>/
~~~

During active development, prefer `--no-archive` to avoid noisy local artifacts.

## Safety model

CBL is designed for local personal use. It enforces these rules:

~~~text
- no target repository import or execution
- no upload behavior
- no recursive scanning of .codecontext/
- hard exclusion of secrets, environments, caches, data, build outputs, and generated artifacts
- binary and unsafe text detection
- redaction before report persistence
- repository-relative paths in AI-facing reports by default
- explicit omitted-file accounting
~~~

`dump` and `diffdump` intentionally emit more source text than `pack`. Review their outputs before sharing them.

## Development validation

For the CBL repository itself:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path

python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
~~~

Run slice audits when changing release-gated behavior:

~~~powershell
python .\scripts\dev\audits\audit_phase30_installation_docs.py
python .\scripts\dev\audits\audit_phase29_dump_diffdump.py
python .\scripts\dev\audits\audit_phase28_manifest_consistency.py
~~~

## Troubleshooting

If PowerShell says `cbl` is not recognized, the package is not installed into the active environment or the environment is not active. Run:

~~~powershell
conda activate cbl-dev
python -m pip install -e .
Get-Command cbl
cbl --help
~~~

If you want to run it without activation:

~~~powershell
conda run -n cbl-dev cbl --help
~~~

If CBL detects the wrong repository, pass an explicit root:

~~~powershell
cbl pack --repo C:\path\to\repo --issue "handoff" --budget 32000 --no-archive
~~~

## Output directories

CBL writes transient command outputs under `.codecontext/latest/`. Stable audit reports are written under `.codecontext/audits/`. The audits directory is intentionally separate from `latest` so release and safety checks remain available after later commands overwrite the latest output bundle.

## Release gates

CBL release validation is intentionally explicit. The built-in command surface is represented by `PUBLIC_COMMANDS`, and every public command registered by argparse must remain synchronized with that constant.

The canonical module invocation remains available even after installing the editable `cbl` console command. Use `python -m codebase_lens pack --issue "handoff" --budget 32000 --no-archive` when validating module execution directly, and use `cbl pack --issue "handoff" --budget 32000 --no-archive` during normal installed use.

Stable audit artifacts are written under `.codecontext/audits/`. They are separate from `.codecontext/latest/` so release, safety, fixture, command-surface, and documentation checks remain inspectable after later commands overwrite the latest output bundle.

## Documentation contract compatibility

This section intentionally preserves exact documentation-contract markers used by the release audits.

Local Codebase Lens remains a local static repository-evidence tool. The primary output directory is `.codecontext/latest/`. Stable audit reports are preserved under `.codecontext/audits/` so safety, release, and command-surface checks remain inspectable after `.codecontext/latest/` is overwritten by later commands.

The canonical module invocation remains available for automation and documentation compatibility:

~~~powershell
python -m codebase_lens pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

The installed console command is equivalent for normal use:

~~~powershell
cbl pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

### PUBLIC_COMMANDS

`PUBLIC_COMMANDS` is the public command-surface contract. The current command surface is:

- doctor
- dump
- snapshot
- tree
- symbols
- imports
- cli
- routes
- tests
- diff
- diffdump
- changed
- file
- symbol
- callers
- contract
- pack
- clean
- graph

### Release gates

Release gates must be run from the CBL repository root. They include the command-surface audit, fixture-matrix audit, release-safety audit, documentation-workflow audit, report-contract parity audit, release-closure audit, reliability-corrections audit, manifest-consistency audit, dump/diffdump audit, installation-docs audit, the built-in architecture contract, the pytest suite, and `git diff --check`.

The release gates protect the local-only model, static-analysis-only behavior, `.codecontext/` recursion exclusion, report contract parity, public command stability, and AI-facing documentation compatibility.
## CBL dump scoping

`cbl dump --no-archive` intentionally dumps from the detected repository root. Changing the shell directory into `src` does not narrow the dump. Use `cbl dump --path src --no-archive` to dump only `src/`. Use `cbl dump --cwd-scope --no-archive` when the current working directory should define the dump scope. Scope paths are filters over the safe file universe; they do not bypass hard exclusions, redaction, or `.codecontext/` exclusion.
