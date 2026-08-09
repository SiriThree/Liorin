"""Build auditable Phase-4 multi-turn candidate assets.

The generated sessions remain MODEL_GENERATED_UNREVIEWED; this script never
upgrades them to formal benchmark Gold.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from eval_platform.context_memory import canonical_session_dataset_hash, session_dataset_inventory, write_canonical_sessions
from eval_platform.multi_turn_seed import build_phase4_candidate_sessions


def main() -> int:
    root=Path(__file__).resolve().parents[2]
    target=root/"evals/benchmark/data/canonical"
    target.mkdir(parents=True,exist_ok=True)
    sessions=build_phase4_candidate_sessions()
    write_canonical_sessions(target/"phase4_multi_turn_candidates_v1.json",sessions)
    inventory=session_dataset_inventory(sessions)
    (target/"phase4_multi_turn_inventory.json").write_text(json.dumps(inventory,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    manifest={
        "dataset_name":"phase4_multi_turn_candidates",
        "dataset_version":"1",
        "schema_version":"1.0",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "dataset_hash":canonical_session_dataset_hash(sessions),
        "annotation_status":"MODEL_GENERATED_UNREVIEWED",
        "formal_metric_eligible":False,
        "intended_usage":"SCHEMA_STRATEGY_PIPELINE_AND_REVIEW_QUEUE_ONLY",
        **inventory,
    }
    (target/"phase4_multi_turn_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
