"""CI regression gate for Liorin evaluations.

Deprecated compatibility wrapper for the Phase-6 Evaluation Contract Gate.

Ordinary PR CI now uses the unified ``eval_platform`` contracts and
``tests/evaluation``.  The old LangSmith threshold flow remains available only
behind ``--legacy-langsmith`` and is not a formal Task Success gate.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def run_offline_ci() -> None:
    print("DEPRECATED: evals/run_ci_eval.py delegates to the unified Phase-6 contract gate.")
    run([sys.executable, "-m", "eval_platform.cli", "validate", "--dataset", "evals/benchmark/data/canonical/validation_v7_3_canonical_v1.json"])
    run([sys.executable, "-m", "pytest", "-q", "tests/evaluation"])


def run_legacy_langsmith(threshold: float) -> None:
    legacy = ROOT / "evals" / "legacy_langsmith_ci_eval.py"
    if not legacy.exists():
        raise SystemExit(
            "legacy LangSmith CI is not available in this checkout. "
            "Use the default offline CI gate or restore evals/legacy_langsmith_ci_eval.py."
        )
    run([sys.executable, str(legacy), "--threshold", str(threshold)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-langsmith", action="store_true", help="Run the old LangSmith-backed CI gate.")
    parser.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args()
    if args.legacy_langsmith:
        run_legacy_langsmith(args.threshold)
    else:
        run_offline_ci()


if __name__ == "__main__":
    main()
