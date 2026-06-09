# CBL Release Checklist

Run from the CBL repository root:

```powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m pip install -e .
```

## Required gates

```powershell
cbl --help
cbl doctor --no-archive
python .\scripts\dev\audits\audit_phase30_installation_docs.py
python .\scripts\dev\audits\audit_phase29_dump_diffdump.py
python .\scripts\dev\audits\audit_phase28_manifest_consistency.py
python .\scripts\dev\audits\audit_phase27_reliability_corrections.py
python .\scripts\dev\audits\audit_phase26_v01_release_closure.py --skip-pytest
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
```

## Manual smoke checks

From outside the CBL repository:

```powershell
cd C:\Users\Galaxy\LEVI\projects
cbl doctor --repo C:\Users\Galaxy\LEVI\projects\CBL --no-archive
cbl dump --repo C:\Users\Galaxy\LEVI\projects\CBL --no-archive
cbl diffdump --repo C:\Users\Galaxy\LEVI\projects\CBL --from HEAD~1 --to HEAD --symbols --no-archive
```

## Safety reminders

CBL is local-only and does not upload your code. Review generated AI handoff reports before sharing them. `dump` and `diffdump` intentionally contain more source text than `pack`.
