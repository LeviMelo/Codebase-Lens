from __future__ import annotations

import json

from codebase_lens.contracts.fixture_matrix import (
    release_fixture_matrix_payload,
    run_release_fixture_matrix,
)


def test_release_fixture_matrix_passes_core_external_repositories() -> None:
    result = run_release_fixture_matrix(include_git_fixture=False)
    payload = release_fixture_matrix_payload(result)

    assert result.ok, json.dumps(payload["issues"], indent=2, sort_keys=True)
    assert payload["schema"]["name"] == "cbl.release_fixture_matrix"
    assert payload["counts"]["cases"] == 5
    assert payload["counts"]["failed"] == 0
    assert payload["counts"]["errors"] == 0

    cases = {case["name"]: case for case in payload["cases"]}

    assert "src/basic_pkg/" in cases["basic_package"]["source_prefixes"]
    assert cases["basic_package"]["counts"]["symbols"] >= 4
    assert cases["basic_package"]["counts"]["test_functions"] >= 1

    assert "src/cli_pkg/" in cases["argparse_cli_package"]["source_prefixes"]
    assert cases["argparse_cli_package"]["counts"]["commands"] >= 2

    assert "src/web_pkg/" in cases["route_static_package"]["source_prefixes"]
    assert cases["route_static_package"]["counts"]["routes"] >= 2

    assert "src/safety_pkg/" in cases["safety_redaction_package"]["source_prefixes"]
    assert "src/recursion_pkg/" in cases["codecontext_recursion_package"]["source_prefixes"]


def test_fixture_matrix_contract_module_does_not_import_cli_layer() -> None:
    import inspect
    import codebase_lens.contracts.fixture_matrix as fixture_matrix

    source = inspect.getsource(fixture_matrix)

    assert "from codebase_lens import cli" not in source
    assert "import codebase_lens.cli" not in source
    assert "codebase_lens.cli" not in source
