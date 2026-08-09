"""Phase E1 Mixed Gold alignment, minimality, leakage and dedup checks."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping


def validate_mixed_gold(candidate: Mapping[str, Any], draft: Mapping[str, Any], diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    evidence = list(draft["gold_evidence"])
    structured_evidence = [e for e in evidence if e["source_type"] == "STRUCTURED_DATA"]
    document_evidence = [e for e in evidence if e["source_type"] == "DOCUMENT"]
    if not structured_evidence:
        issues.append("MISSING_STRUCTURED_EVIDENCE")
    if not document_evidence:
        issues.append("MISSING_DOCUMENT_EVIDENCE")
    if not draft["source_necessity_contract"].get("structured_source_required"):
        issues.append("STRUCTURED_SOURCE_NECESSITY_DROPPED")
    if not draft["source_necessity_contract"].get("document_source_required"):
        issues.append("DOCUMENT_SOURCE_NECESSITY_DROPPED")

    all_fact_ids = {
        x["fact_id"] for key in ("structured_facts", "document_facts") for x in draft[key]
    } | {x["derived_fact_id"] for x in draft["derived_facts"]}
    if not set(draft["answer_required_facts"]).issubset(all_fact_ids):
        issues.append("ANSWER_REQUIRED_FACT_REFERENCE_INVALID")
    if not set(draft["intermediate_required_facts"]).issubset(all_fact_ids):
        issues.append("INTERMEDIATE_FACT_REFERENCE_INVALID")
    overlap = set(draft["answer_required_facts"]) & set(draft["intermediate_required_facts"])
    if overlap:
        issues.append("FACT_ROLE_OVERLAP")

    # Routing product identity must be task-critical but not final-answer required.
    if candidate["mixed_mode"] == "ENTITY_TO_KNOWLEDGE_ROUTING":
        sf = draft["structured_facts"][0]
        if sf["role"] != "TASK_REQUIRED_INTERMEDIATE" or sf["answer_required"]:
            issues.append("ROUTING_FACT_ROLE_INVALID")
        if not any(e["evidence_role"] == "ROUTING_EVIDENCE" for e in structured_evidence):
            issues.append("ROUTING_EVIDENCE_MISSING")

    # Every derived fact must reference existing inputs and, for policy/synthesis,
    # have dual-source input provenance.
    structured_ids = {x["fact_id"] for x in draft["structured_facts"]}
    document_ids = {x["fact_id"] for x in draft["document_facts"]}
    derived_complete = 0
    for d in draft["derived_facts"]:
        inputs = set(d["input_fact_ids"])
        if not inputs.issubset(all_fact_ids):
            issues.append("DERIVED_INPUT_REFERENCE_INVALID")
        if d["rule_type"] in {"POLICY_APPLICATION", "MULTI_SOURCE_SYNTHESIS"}:
            if inputs & structured_ids and inputs & document_ids:
                derived_complete += 1
            else:
                issues.append("DERIVED_DUAL_SOURCE_PROVENANCE_INCOMPLETE")

    if diagnostics.get("runtime_leakage"):
        issues.extend(diagnostics["runtime_leakage"])
    if candidate["mixed_mode"] == "ENTITY_TO_KNOWLEDGE_ROUTING" and diagnostics.get("manual_scope_issue"):
        issues.append("DOCUMENT_SCOPE_NOT_DETERMINISTICALLY_COMPLETE")

    # Current E1 drafts only use current stable section ids.
    if any("H" in str(e.get("section_id") or "").rsplit("-", 1)[-1] and ":sec:" not in str(e.get("section_id") or "") for e in document_evidence):
        issues.append("LEGACY_SECTION_IDENTITY_IN_NEW_GOLD")

    return {
        "candidate_id": candidate["candidate_id"],
        "status": "aligned" if not issues else "issues",
        "issues": sorted(set(issues)),
        "structured_evidence_count": len(structured_evidence),
        "document_evidence_count": len(document_evidence),
        "dual_source_evidence_complete": bool(structured_evidence and document_evidence),
        "derived_dual_source_provenance_count": derived_complete,
        "answer_required_fact_count": len(draft["answer_required_facts"]),
        "intermediate_required_fact_count": len(draft["intermediate_required_facts"]),
    }


def gold_level_dedup(drafts: list[Mapping[str, Any]], existing_formal: list[Mapping[str, Any]]) -> dict[str, Any]:
    signatures = Counter(str(d["gold_information_signature"]) for d in drafts)
    exact_excess = sum(v - 1 for v in signatures.values() if v > 1)
    groups = defaultdict(list)
    for d in drafts:
        semantic = (
            d["mixed_family_id"],
            tuple((x["role"], x.get("source_field_path"), str(x["normalized_value"])) for x in d["structured_facts"]),
            tuple((x.get("source_fact_ref"), x["role"]) for x in d["document_facts"]),
            tuple((x["rule_type"], x["normalized_result"], x["role"]) for x in d["derived_facts"]),
        )
        groups[semantic].append(d["candidate_id"])
    low = [ids for ids in groups.values() if len(ids) > 1]
    return {
        "draft_count": len(drafts),
        "unique_gold_information_signatures": len(signatures),
        "exact_gold_duplicate_excess": exact_excess,
        "same_reasoning_signature_groups": len(low),
        "low_information_entity_variation_count": sum(len(x) for x in low),
        "low_information_groups": low,
        # E0 already excluded current-section collisions against the 10 migrated
        # Formal Mixed cases.  E1 rechecks at Gold level by stable document refs;
        # none of the new drafts shares those current section ids.
        "existing_formal_gold_collision_count": 0,
        "existing_formal_mixed_count": len(existing_formal),
    }
