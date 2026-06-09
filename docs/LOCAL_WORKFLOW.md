# CBL Local Workflow

CBL is local-only and does not upload your code. Review generated AI handoff reports before sharing them.

## Start a shell

```powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
python -m pip install -e .
cbl --help
```

For CBL development, keep `PYTHONPATH` explicit when running tests directly from the checkout:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

## Use CBL on another repository

```powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl doctor --no-archive
cbl pack --issue "explain the requested implementation task" --budget 32000 --no-archive
```

Upload or paste:

```text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/manifest.json
```

When the assistant needs exact searchable source, add:

```powershell
cbl dump --no-archive
```

When the assistant needs a change review between Git refs, add:

```powershell
cbl diffdump --from HEAD~1 --to HEAD --symbols --no-archive
```

## Development validation chain

```powershell
python .\scripts\dev\audits\audit_phase30_installation_docs.py
python .\scripts\dev\audits\audit_phase29_dump_diffdump.py
python .\scripts\dev\audits\audit_phase28_manifest_consistency.py
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
```

## Commit discipline

Do not commit until the relevant slice audit, the contract audit, pytest, and `git diff --check` pass.
