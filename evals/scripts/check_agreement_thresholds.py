#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_THRESHOLDS = {
    "query_understanding.task_type_kappa": 0.80,
    "query_understanding.clarification_kappa": 0.80,
    "query_understanding.requirement_jaccard": 0.85,
    "query_understanding.clarification_slot_jaccard": 0.85,
    "routing.required_sources_jaccard": 0.85,
    "routing.conditional_sources_jaccard": 0.80,
    "routing.forbidden_sources_jaccard": 0.90,
    "retrieval.weighted_kappa": 0.80,
    "retrieval.binary_relevance_f1": 0.90,
    "retrieval.fact_set_f1": 0.85,
    "retrieval.source_ref_jaccard": 0.90,
    "retrieval.numeric_exact_agreement": 0.98,
    "answer_generation.response_type_kappa": 0.85,
    "answer_generation.fact_set_f1": 0.85,
    "answer_generation.source_ref_jaccard": 0.90,
    "answer_generation.numeric_exact_agreement": 0.98,
    "answer_generation.forbidden_claim_jaccard": 0.90,
    "agent_behavior.action_kappa": 0.80,
    "agent_behavior.reason_codes_jaccard": 0.85,
    "agent_behavior.clarification_slots_jaccard": 0.85,
    "agent_behavior.supplemental_sources_jaccard": 0.85,
    "end_to_end.response_type_kappa": 0.85,
    "end_to_end.decision_kappa": 0.80,
    "end_to_end.required_sources_jaccard": 0.85,
    "end_to_end.required_actions_jaccard": 0.85,
    "end_to_end.fact_set_f1": 0.85,
    "end_to_end.source_ref_jaccard": 0.90,
    "end_to_end.numeric_exact_agreement": 0.98,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate A/B inter-agent agreement before accepting the annotation run.")
    parser.add_argument("agreement_report")
    parser.add_argument("--thresholds", default="", help="Optional JSON object overriding default thresholds")
    parser.add_argument("--output", default="")
    parser.add_argument("--manifest", default="", help="Run manifest; required to distinguish real models from mock flow tests")
    args = parser.parse_args()
    report = json.loads(Path(args.agreement_report).read_text(encoding="utf-8"))
    mock_run = False
    if args.manifest:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        mock_run = any(manifest.get("annotators", {}).get(role, {}).get("backend") == "mock" for role in ["A","B","C"])
    thresholds = dict(DEFAULT_THRESHOLDS)
    if args.thresholds:
        thresholds.update(json.loads(Path(args.thresholds).read_text(encoding="utf-8")))
    failures = []
    not_estimable = []
    measurements = {}
    for path, minimum in thresholds.items():
        layer, metric = path.split(".", 1)
        value = report.get("by_layer", {}).get(layer, {}).get(metric)
        measurements[path] = {"value": value, "minimum": minimum}
        if value is None:
            not_estimable.append(path)
        elif float(value) < minimum:
            failures.append({"metric": path, "value": value, "minimum": minimum})
    result = {
        "status": ("INVALID_MOCK_RUN" if mock_run else ("PASS" if not failures else "FAIL")),
        "semantic_results_valid": not mock_run,
        "failures": failures,
        "not_estimable": not_estimable,
        "measurements": measurements,
        "instruction": (
            "If FAIL, revise the annotation guide/prompts or ambiguous samples and rerun A/B independently. "
            "C adjudication alone does not repair low inter-annotator reliability."
        ),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    if mock_run:
        raise SystemExit(2)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
