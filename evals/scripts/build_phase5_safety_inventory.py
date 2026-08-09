from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "evals" / "benchmark" / "data" / "canonical"
SECURITY = ROOT / "evals" / "benchmark" / "data" / "security" / "phase5_safety_fixtures_v1.json"
OUT = CANON / "phase5_safety_inventory.json"


def rows(path: Path):
    value=json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value,list) else value.get("samples") or value.get("sessions") or []


def main():
    formal=[]; seeds=[]; multi=[]
    for name in ("dev_v7_3_canonical_v1.json","validation_v7_3_canonical_v1.json"):
        for row in rows(CANON/name):
            if row.get("category") == "SAFETY_GOVERNANCE": formal.append(row)
    for row in rows(CANON/"representative_seed_v1.json"):
        if row.get("category") == "SAFETY_GOVERNANCE": seeds.append(row)
    for row in rows(CANON/"phase4_multi_turn_candidates_v1.json"):
        if row.get("category") == "SAFETY_GOVERNANCE": multi.append(row)
    fixture=json.loads(SECURITY.read_text(encoding="utf-8"))["fixtures"]
    attack=Counter((x.get("subcategory") or "UNKNOWN") for x in formal+seeds)
    attack.update(x.get("attack_type") or "UNKNOWN" for x in fixture)
    payload={
        "formal_single_turn_candidate": len(formal),
        "formal_single_turn_gold_eligible": len(formal),
        "representative_seed_needs_review": len(seeds),
        "multi_turn_model_generated_unreviewed": len(multi),
        "unit_test_security_fixtures": len(fixture),
        "trusted_test_split_exists": False,
        "formal_production_safety_metrics_status": "NOT_RUN",
        "by_attack_type": dict(sorted(attack.items())),
        "notes": [
            "UNIT_TEST_FIXTURE rows are excluded from formal safety metrics.",
            "MODEL_GENERATED_UNREVIEWED multi-turn sessions are excluded from formal metrics.",
            "The three migrated legacy safety cases still require real Production/Judge execution for formal results."
        ]
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
