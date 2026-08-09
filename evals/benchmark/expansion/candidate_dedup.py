"""Deterministic semantic/entity deduplication for D1 candidate construction."""
from __future__ import annotations

import re
from collections import defaultdict
from .candidate_contracts import CandidateStatus, PrivateBusinessCandidate


def _normalized_query(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"<(?:order|ticket|warranty)_ref:[0-9a-f]+>", "<entity_ref>", text)
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[，。！？,.!?：:]", "", text)


def deduplicate_candidates(candidates: list[PrivateBusinessCandidate]) -> dict[str, int]:
    exact = {}; normalized = {}; semantic = {}; family_state = defaultdict(list)
    report = {"exact_query_duplicates":0,"normalized_query_duplicates":0,"normalized_surface_collisions_retained_due_distinct_source_entity":0,"semantic_entity_field_duplicates":0,"family_state_repetitions":0,"rejected_duplicates":0}
    for cand in candidates:
        if cand.status is CandidateStatus.REJECTED:
            continue
        exact_key = cand.candidate_query
        norm_key = _normalized_query(cand.candidate_query)
        semantic_key = cand.duplicate_keys["semantic_entity_field"]
        if semantic_key in semantic:
            cand.status = CandidateStatus.REJECTED
            cand.duplicate_of = semantic[semantic_key]
            cand.duplicate_type = "SAME_ENTITY_SAME_FIELD_SET"
            cand.rejection_reasons.append("SEMANTIC_DUPLICATE")
            report["semantic_entity_field_duplicates"] += 1
            report["rejected_duplicates"] += 1
            continue
        semantic[semantic_key] = cand.candidate_id
        if exact_key in exact:
            report["exact_query_duplicates"] += 1
        else:
            exact[exact_key] = cand.candidate_id
        if norm_key in normalized:
            report["normalized_query_duplicates"] += 1
            report["normalized_surface_collisions_retained_due_distinct_source_entity"] += 1
        else:
            normalized[norm_key] = cand.candidate_id
        family_state[cand.duplicate_keys["family_state"]].append(cand.candidate_id)
    report["family_state_repetitions"] = sum(max(0,len(v)-1) for v in family_state.values())
    return report
