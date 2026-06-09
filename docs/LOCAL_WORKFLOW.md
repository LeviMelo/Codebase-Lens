# CBL Local Workflow

CBL is local-only and does not upload your code. Review generated AI handoff reports before sharing them.

## Start a shell

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
python -m pip install -e .
cbl --help
~~~

For CBL development, keep `PYTHONPATH` explicit when running tests directly from the checkout:

~~~powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
~~~

## Use CBL on another repository

~~~powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl doctor --no-archive
cbl pack --issue "explain the requested implementation task" --budget 32000 --no-archive
~~~

Upload or paste:

~~~text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/manifest.json
~~~

When the assistant needs exact searchable source, add:

~~~powershell
cbl dump --no-archive
~~~

When the assistant needs a change review between Git refs, add:

~~~powershell
cbl diffdump --from HEAD~1 --to HEAD --symbols --no-archive
~~~

## Development validation chain

~~~powershell
python .\scripts\dev\audits\audit_phase30_installation_docs.py
python .\scripts\dev\audits\audit_phase29_dump_diffdump.py
python .\scripts\dev\audits\audit_phase28_manifest_consistency.py
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
~~~

## Commit discipline

Do not commit until the relevant slice audit, the contract audit, pytest, and `git diff --check` pass.

## Compatibility command forms

Use the installed console command for normal local work:

~~~powershell
cbl pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

The canonical module invocation remains documented and supported:

~~~powershell
python -m codebase_lens pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

Run these commands from the target repository root, or pass `--repo` explicitly. Do not run repo-local validation commands from a parent workspace unless that is intentional.
## CBL dump scoping

`cbl dump --no-archive` intentionally dumps from the detected repository root. Changing the shell directory into `src` does not narrow the dump. Use `cbl dump --path src --no-archive` to dump only `src/`. Use `cbl dump --cwd-scope --no-archive` when the current working directory should define the dump scope. Scope paths are filters over the safe file universe; they do not bypass hard exclusions, redaction, or `.codecontext/` exclusion.
