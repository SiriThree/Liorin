"""Agreement / disagreement analysis for Phase D3 private Gold annotation."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping

DIMENSIONS = (
    "query_quality", "answerability", "response_type_correct", "gold_fact_correct",
    "gold_fact_complete", "gold_fact_minimal", "gold_evidence_correct",
    "task_contract_correct", "source_support", "ambiguity", "privacy_safe",
)
HIGH_DIMENSIONS = {"answerability", "response_type_correct", "source_support"}


def _rate(n: int, d: int) -> float | None:
    return n / d if d else None


def _edit_signature(rows: Iterable[Mapping[str, Any]]) -> tuple:
    return tuple(sorted(
        (str(x.get("target")), str(x.get("operation")), repr(x.get("old_value")), repr(x.get("proposed_value")))
        for x in rows
    ))


def _fact_index(decision: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(x["fact_id"]): x for x in decision.get("gold_fact_reviews", [])}


def _evidence_index(decision: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(x["evidence_id"]): x for x in decision.get("gold_evidence_reviews", [])}


def classify_pair(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    dim_disagreements = [d for d in DIMENSIONS if a.get(d) != b.get(d)]
    fact_a, fact_b = _fact_index(a), _fact_index(b)
    evidence_a, evidence_b = _evidence_index(a), _evidence_index(b)
    fact_disagreements = []
    for fid in sorted(set(fact_a) | set(fact_b)):
        if fact_a.get(fid) != fact_b.get(fid):
            fact_disagreements.append(fid)
    evidence_disagreements = []
    for eid in sorted(set(evidence_a) | set(evidence_b)):
        if evidence_a.get(eid) != evidence_b.get(eid):
            evidence_disagreements.append(eid)
    contract_disagree = a.get("task_contract_review") != b.get("task_contract_review")
    edits_identical = _edit_signature(a.get("suggested_edits", [])) == _edit_signature(b.get("suggested_edits", []))
    overall_same = a.get("overall_decision") == b.get("overall_decision")
    exact = overall_same and not dim_disagreements and not fact_disagreements and not evidence_disagreements and not contract_disagree and edits_identical

    if exact:
        decision = a.get("overall_decision")
        category = {
            "ACCEPT": "AGREED_ACCEPT",
            "ACCEPT_WITH_EDITS": "AGREED_ACCEPT_WITH_IDENTICAL_EDITS",
            "REJECT": "AGREED_REJECT",
            "NEEDS_HUMAN_REVIEW": "AGREED_HUMAN_REVIEW",
        }.get(decision, "EXACT_AGREEMENT")
        severity = "NONE"
    else:
        category = "PARTIAL_DISAGREEMENT"
        severity = "LOW"
        high = False
        if {a.get("overall_decision"), b.get("overall_decision")} == {"ACCEPT", "REJECT"}:
            high = True
        if any(d in HIGH_DIMENSIONS for d in dim_disagreements) or fact_disagreements or evidence_disagreements:
            high = True
        if high:
            category = "MAJOR_DISAGREEMENT"
            severity = "HIGH"
        elif contract_disagree or "task_contract_correct" in dim_disagreements or "gold_fact_minimal" in dim_disagreements:
            severity = "MEDIUM"
        elif not overall_same:
            severity = "MEDIUM"
    return {
        "category": category,
        "severity": severity,
        "overall_same": overall_same,
        "exact_case_agreement": exact,
        "dimension_disagreements": dim_disagreements,
        "gold_fact_disagreements": fact_disagreements,
        "gold_evidence_disagreements": evidence_disagreements,
        "task_contract_disagreement": contract_disagree,
        "suggested_edits_identical": edits_identical,
    }


def _categorical_kappa(a_values: list[str], b_values: list[str]) -> dict[str, Any]:
    n = len(a_values)
    if n == 0:
        return {"sample_size": 0, "raw_agreement": None, "kappa": None, "class_distribution_a": {}, "class_distribution_b": {}}
    observed = sum(x == y for x, y in zip(a_values, b_values)) / n
    ca, cb = Counter(a_values), Counter(b_values)
    classes = set(ca) | set(cb)
    expected = sum((ca[c] / n) * (cb[c] / n) for c in classes)
    kappa = None if expected == 1 else (observed - expected) / (1 - expected)
    return {"sample_size": n, "raw_agreement": observed, "kappa": kappa, "class_distribution_a": dict(ca), "class_distribution_b": dict(cb)}


def analyze_agreement(packets: list[Mapping[str, Any]], a_rows: list[Mapping[str, Any]], b_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    packet_by_id = {p["candidate_id"]: p for p in packets}
    a_by = {r["candidate_id"]: r for r in a_rows if r.get("status") == "VALID" and r.get("decision")}
    b_by = {r["candidate_id"]: r for r in b_rows if r.get("status") == "VALID" and r.get("decision")}
    valid_ids = [cid for cid in packet_by_id if cid in a_by and cid in b_by and a_by[cid]["packet_hash"] == b_by[cid]["packet_hash"] == packet_by_id[cid]["annotation_packet_hash"]]

    dimension_counts = {d: {"numerator": 0, "denominator": 0, "rate": None} for d in DIMENSIONS}
    domain = defaultdict(lambda: {"numerator": 0, "denominator": 0})
    family = defaultdict(lambda: {"numerator": 0, "denominator": 0})
    fact_num = fact_den = evidence_num = evidence_den = contract_num = contract_den = 0
    pair_rows = []
    disagreements = []
    decision_a, decision_b = [], []
    categories = Counter()

    for cid in valid_ids:
        packet = packet_by_id[cid]
        a, b = a_by[cid]["decision"], b_by[cid]["decision"]
        comp = classify_pair(a, b)
        decision_a.append(a["overall_decision"]); decision_b.append(b["overall_decision"])
        categories[comp["category"]] += 1
        for d in DIMENSIONS:
            dimension_counts[d]["denominator"] += 1
            dimension_counts[d]["numerator"] += int(a.get(d) == b.get(d))
        fa, fb = _fact_index(a), _fact_index(b)
        for fid in sorted(set(fa) | set(fb)):
            fact_den += 1; fact_num += int(fa.get(fid) == fb.get(fid))
        ea, eb = _evidence_index(a), _evidence_index(b)
        for eid in sorted(set(ea) | set(eb)):
            evidence_den += 1; evidence_num += int(ea.get(eid) == eb.get(eid))
        contract_den += 1; contract_num += int(a.get("task_contract_review") == b.get("task_contract_review"))
        rec = packet["source_snapshot"]["record_type"].upper()
        fam = packet["semantic_family_id"]
        domain[rec]["denominator"] += 1; domain[rec]["numerator"] += int(comp["exact_case_agreement"])
        family[fam]["denominator"] += 1; family[fam]["numerator"] += int(comp["exact_case_agreement"])
        pair_rows.append({"candidate_id": cid, "packet_hash": packet["annotation_packet_hash"], **comp})
        if not comp["exact_case_agreement"]:
            priority = "P0" if comp["severity"] == "HIGH" else ("P1" if comp["severity"] == "MEDIUM" else "P2")
            disagreements.append({
                "candidate_id": cid, "packet_hash": packet["annotation_packet_hash"],
                "annotator_a_overall": a["overall_decision"], "annotator_b_overall": b["overall_decision"],
                "disagreement_dimensions": comp["dimension_disagreements"], "gold_fact_disagreements": comp["gold_fact_disagreements"],
                "gold_evidence_disagreements": comp["gold_evidence_disagreements"], "task_contract_disagreement": comp["task_contract_disagreement"],
                "severity": comp["severity"], "annotator_a_suggested_edits": a.get("suggested_edits", []),
                "annotator_b_suggested_edits": b.get("suggested_edits", []),
                "source_refs": [x["evidence_id"] for x in packet["gold_draft"]["gold_evidence_draft"]],
                "semantic_family": fam, "record_type": rec, "review_risk": packet.get("review_requirements", []),
                "adjudication_priority": priority,
            })

    for d, row in dimension_counts.items():
        row["rate"] = _rate(row["numerator"], row["denominator"])
    for grouping in (domain, family):
        for row in grouping.values():
            row["rate"] = _rate(row["numerator"], row["denominator"])
    overall_num = sum(a_by[c]["decision"]["overall_decision"] == b_by[c]["decision"]["overall_decision"] for c in valid_ids)
    exact_num = sum(r["exact_case_agreement"] for r in pair_rows)
    return {
        "valid_pair_ids": valid_ids,
        "pair_rows": pair_rows,
        "disagreements": disagreements,
        "summary": {
            "valid_pairs": len(valid_ids),
            "overall_decision_agreement": {"numerator": overall_num, "denominator": len(valid_ids), "rate": _rate(overall_num, len(valid_ids))},
            "exact_case_agreement": {"numerator": exact_num, "denominator": len(valid_ids), "rate": _rate(exact_num, len(valid_ids))},
            "agreement_categories": dict(categories),
            "cohens_kappa_diagnostic": _categorical_kappa(decision_a, decision_b),
        },
        "dimension": dimension_counts,
        "gold_fact": {"numerator": fact_num, "denominator": fact_den, "rate": _rate(fact_num, fact_den)},
        "gold_evidence": {"numerator": evidence_num, "denominator": evidence_den, "rate": _rate(evidence_num, evidence_den)},
        "task_contract": {"numerator": contract_num, "denominator": contract_den, "rate": _rate(contract_num, contract_den)},
        "domain": dict(domain),
        "family": dict(family),
    }
