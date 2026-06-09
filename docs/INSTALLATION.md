# CBL Installation and PowerShell Setup

CBL should be installed as a Python console script. The durable implementation remains in `src/codebase_lens`; PowerShell is only a launcher environment.

## Editable development install

Run this once from the CBL repository root:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
python -m pip install -e .
~~~

Verify:

~~~powershell
Get-Command cbl
cbl --help
cbl doctor --no-archive
~~~

`pip install -e .` creates a `cbl` console command inside the active environment. On Windows/Conda this means an executable shim is created under the environment's `Scripts` directory. When `conda activate cbl-dev` runs, that directory is added to `PATH`, so `cbl` works from any current directory.

## Use from any repository

~~~powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl doctor --no-archive
cbl pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

CBL detects the repository root from the current directory. Use `--repo` when you want to run from elsewhere:

~~~powershell
cbl pack --repo C:\path\to\target\repo --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

## Use without activating the environment

~~~powershell
conda run -n cbl-dev cbl doctor --no-archive
conda run -n cbl-dev cbl dump --repo C:\path\to\target\repo --no-archive
~~~

This is slower than an activated shell but useful for ad hoc calls.

## Optional PowerShell profile helper

A profile function can route calls through the Conda environment:

~~~powershell
function cblx {
    conda run -n cbl-dev cbl @args
}
~~~

Then:

~~~powershell
cblx doctor --repo C:\path\to\target\repo --no-archive
~~~

Use a different name such as `cblx` to avoid hiding the real `cbl` console command.

## Do not copy source files into PATH

Do not copy `src/codebase_lens` or repository-root scripts into a PATH directory. That creates stale launchers and bypasses the package contract. The supported command is the package entry point:

~~~toml
[project.scripts]
cbl = "codebase_lens.cli:main"
~~~

## Reinstall after environment rebuilds

If the Conda environment is recreated, run:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
python -m pip install -e .
~~~

## Module invocation compatibility

Even when `cbl` is installed as a console command, the module invocation remains valid:

~~~powershell
python -m codebase_lens pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

This form is useful in tests, audits, and environments where console-script shims are not on PATH.
