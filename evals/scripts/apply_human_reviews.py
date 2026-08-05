#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from annotation_pipeline.io_utils import read_json, read_jsonl, write_json_atomic
from annotation_pipeline.models import AnnotationEnvelope
from annotation_pipeline.agents import validate_annotation_against_packet
from annotation_pipeline.review_queue import validate_completed_reviews


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply completed human risk reviews to adjudicated annotations.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--reviews", default="", help="Optional JSON file with completed human_review records keyed by sample_id.")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    queue = read_json(run_dir / "human_review_queue.json")
    if args.reviews:
        review_rows = read_json(args.reviews)
        if isinstance(review_rows, dict) and "reviews" in review_rows:
            review_rows = review_rows["reviews"]
        if not isinstance(review_rows, list):
            raise SystemExit("--reviews must be a JSON array or an object containing a reviews array")
        reviews_by_id = {row["sample_id"]: row.get("human_review", row) for row in review_rows}
        for row in queue:
            if row["sample_id"] in reviews_by_id:
                row["human_review"] = reviews_by_id[row["sample_id"]]
    errors = validate_completed_reviews(queue)
    if errors:
        raise SystemExit("human review queue is incomplete:\n- " + "\n- ".join(errors[:100]))
    adjudicated = read_jsonl(run_dir / "adjudicated.jsonl")
    by_id = {row["sample_id"]: row for row in adjudicated}
    rejected = []
    modified = 0
    approved = 0
    for row in queue:
        review = row["human_review"]
        target = by_id[row["sample_id"]]
        if review["status"] == "approved":
            target["human_review"] = {
                "reviewer_id": review["reviewer_id"],
                "status": "approved",
                "notes": review.get("notes", ""),
            }
            approved += 1
        elif review["status"] == "modified":
            annotation = AnnotationEnvelope.model_validate({"annotation": review["final_annotation"]}).annotation
            if annotation.sample_id != row["sample_id"] or annotation.layer != row["layer"]:
                raise ValueError(f"reviewed annotation identity mismatch for {row['sample_id']}")
            validate_annotation_against_packet(annotation, row["source_packet"])
            target["final_annotation"] = annotation.model_dump(mode="json")
            target["human_review"] = {
                "reviewer_id": review["reviewer_id"],
                "status": "modified",
                "notes": review.get("notes", ""),
            }
            modified += 1
        else:
            target["human_review"] = {
                "reviewer_id": review["reviewer_id"],
                "status": "rejected",
                "notes": review.get("notes", ""),
            }
            rejected.append(row["sample_id"])
    output = Path(args.output) if args.output else run_dir / "final_annotations_after_human_review.json"
    payload = {
        "summary": {
            "total": len(adjudicated),
            "reviewed": len(queue),
            "approved": approved,
            "modified": modified,
            "rejected": len(rejected),
            "rejected_sample_ids": rejected,
        },
        "annotations": adjudicated,
    }
    write_json_atomic(output, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
