# CBL Release Checklist

Run from the CBL repository root:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m pip install -e .
~~~

## Required gates

~~~powershell
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
~~~

## Manual smoke checks

From outside the CBL repository:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects
cbl doctor --repo C:\Users\Galaxy\LEVI\projects\CBL --no-archive
cbl dump --repo C:\Users\Galaxy\LEVI\projects\CBL --no-archive
cbl diffdump --repo C:\Users\Galaxy\LEVI\projects\CBL --from HEAD~1 --to HEAD --symbols --no-archive
~~~

## Safety reminders

CBL is local-only and does not upload your code. Review generated AI handoff reports before sharing them. `dump` and `diffdump` intentionally contain more source text than `pack`.

## Current release audit chain

Run or preserve coverage for the current release audit chain:

- `scripts/dev/audits/audit_phase30_installation_docs.py`
- `scripts/dev/audits/audit_phase29_dump_diffdump.py`
- `scripts/dev/audits/audit_phase28_manifest_consistency.py`
- `scripts/dev/audits/audit_phase27_reliability_corrections.py`
- `scripts/dev/audits/audit_phase26_v01_release_closure.py`
- `scripts/dev/audits/audit_phase25_report_contract_parity.py`
- `scripts/dev/audits/audit_phase24_documentation_workflow.py`
- `scripts/dev/audits/audit_phase23_audit_report_sanitization.py`
- `scripts/dev/audits/audit_phase22_release_safety.py`
- `scripts/dev/audits/audit_phase21_release_fixture_matrix.py`
- `scripts/dev/audits/audit_phase20_public_command_stability.py`

## Current release audit inventory

The release checklist must mention the current audit chain explicitly:

- `scripts/dev/audits/audit_phase30_installation_docs.py`
- `scripts/dev/audits/audit_phase29_dump_diffdump.py`
- `scripts/dev/audits/audit_phase28_manifest_consistency.py`
- `scripts/dev/audits/audit_phase27_reliability_corrections.py`
- `scripts/dev/audits/audit_phase26_v01_release_closure.py`
- `scripts/dev/audits/audit_phase25_report_contract_parity.py`
- `scripts/dev/audits/audit_phase24_documentation_workflow.py`
- `scripts/dev/audits/audit_phase23_audit_report_sanitization.py`
- `scripts/dev/audits/audit_phase22_release_safety.py`
- `scripts/dev/audits/audit_phase21_release_fixture_matrix.py`
- `scripts/dev/audits/audit_phase20_public_command_stability.py`

Run release gates from the repository root. The phase-26 release-closure audit delegates to older release gates and can be run with `--skip-pytest` for recursive-audit use.

~~~powershell
python .\scripts\dev\audits\audit_phase30_installation_docs.py
python .\scripts\dev\audits\audit_phase29_dump_diffdump.py
python .\scripts\dev\audits\audit_phase28_manifest_consistency.py
python .\scripts\dev\audits\audit_phase27_reliability_corrections.py
python .\scripts\dev\audits\audit_phase25_report_contract_parity.py
python .\scripts\dev\audits\audit_phase24_documentation_workflow.py
python .\scripts\dev\audits\audit_phase23_audit_report_sanitization.py
python .\scripts\dev\audits\audit_phase22_release_safety.py
python .\scripts\dev\audits\audit_phase21_release_fixture_matrix.py
python .\scripts\dev\audits\audit_phase20_public_command_stability.py
python .\scripts\dev\audits\audit_phase26_v01_release_closure.py --skip-pytest
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
~~~
