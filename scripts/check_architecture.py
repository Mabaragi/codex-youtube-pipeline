from __future__ import annotations

from codex_sdk_cli.architecture.budget import find_violations


def main() -> int:
    violations = find_violations()
    if not violations:
        print("Architecture size budgets passed.")
        return 0
    print("Architecture size budget violations:")
    for violation in violations:
        print(f"- {violation.render()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
