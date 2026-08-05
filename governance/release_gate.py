"""Executable, fail-closed release gate driven by measured test/evaluation artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _nested(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def evaluate_gate(config: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for name, spec in config.get("checks", {}).items():
        actual = _nested(report, spec["path"])
        required = bool(spec.get("required", True))
        operator = spec.get("operator", "eq")
        expected = spec.get("value")
        if expected is None:
            status = "blocked_unconfigured" if required else "not_configured"
            passed = not required
        elif actual is None:
            status = "missing"
            passed = False
        elif operator == "eq":
            passed = actual == expected
            status = "pass" if passed else "fail"
        elif operator == "lte":
            passed = float(actual) <= float(expected)
            status = "pass" if passed else "fail"
        elif operator == "gte":
            passed = float(actual) >= float(expected)
            status = "pass" if passed else "fail"
        else:
            passed = False
            status = "invalid_operator"
        checks.append({
            "name": name,
            "path": spec["path"],
            "operator": operator,
            "expected": expected,
            "actual": actual,
            "required": required,
            "status": status,
            "passed": passed,
        })
    passed = all(item["passed"] for item in checks if item["required"])
    return {"passed": passed, "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="governance/release_gate_config.json")
    parser.add_argument("--report", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    result = evaluate_gate(config, report)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
