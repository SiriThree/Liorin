#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from annotation_pipeline.gold_export import annotation_to_gold
from annotation_pipeline.io_utils import read_json, write_json_atomic


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a new dataset version from adjudicated + human-reviewed annotations.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--reviewed-annotations", required=True, help="Output of apply_human_reviews.py")
    parser.add_argument("--output", required=True)
    parser.add_argument("--replace-gold", action="store_true", help="Replace gold; otherwise preserve old gold and write reviewed_gold_v7_4")
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    reviewed = read_json(args.reviewed_annotations)
    rows = reviewed["annotations"]
    by_id = {row["sample_id"]: row for row in rows}
    output = []
    rejected = []
    for sample in dataset:
        record = by_id.get(sample["id"])
        clone = dict(sample)
        if not record:
            output.append(clone); continue
        if (record.get("human_review") or {}).get("status") == "rejected":
            rejected.append(sample["id"])
            clone["reviewed_gold_status"] = "rejected_requires_dataset_revision"
            output.append(clone); continue
        new_gold = annotation_to_gold(sample, record["final_annotation"])
        if args.replace_gold:
            clone["previous_gold_v7_3"] = clone.get("gold")
            clone["gold"] = new_gold
        else:
            clone["reviewed_gold_v7_4"] = new_gold
        clone["multi_agent_annotation"] = {
            "method": "two independent AI annotators + AI disagreement adjudicator + human risk review",
            "human_review": record.get("human_review"),
            "had_agent_disagreement": record.get("had_disagreement"),
            "conflict_paths": record.get("conflict_paths", []),
            "quality_status": record["final_annotation"].get("quality_status"),
        }
        output.append(clone)
    payload = {
        "metadata": {
            "source_dataset": str(args.dataset),
            "replace_gold": args.replace_gold,
            "sample_count": len(output),
            "rejected_count": len(rejected),
            "rejected_sample_ids": rejected,
        },
        "samples": output,
    }
    write_json_atomic(args.output, payload)
    print(json.dumps(payload["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
