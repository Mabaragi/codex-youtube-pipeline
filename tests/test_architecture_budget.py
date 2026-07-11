from __future__ import annotations

from codex_sdk_cli.architecture.budget import find_violations


def test_production_modules_stay_within_architecture_size_budgets() -> None:
    violations = find_violations()
    assert not violations, "\n".join(violation.render() for violation in violations)
