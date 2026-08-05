"""CI regression gate for Liorin evaluations.

Default CI mode is offline and runs:
- production-adapter benchmark smoke
- legacy local Agentic RAG smoke fixture

The previous LangSmith dataset sync/evaluate flow is intentionally not the
default because ordinary PR CI should not recreate remote datasets.
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
    run([sys.executable, "-m", "evals.benchmark.cli", "smoke"])
    run([sys.executable, "evals/agentic_rag_eval.py"])


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
