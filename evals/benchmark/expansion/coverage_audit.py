"""Existing benchmark coverage, semantic families, and duplication audit."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def semantic_family(sample: dict[str, Any]) -> str:
    category=str(sample.get("category") or "UNKNOWN")
    sub=str(sample.get("subcategory") or "UNKNOWN")
    query=str((sample.get("input") or {}).get("query") or "")
    behavior=sample.get("expected_behavior") or {}
    evidence=sample.get("gold_evidence") or []
    facts=" ".join(str(f.get("description") or f.get("normalized_value") or "") for f in sample.get("gold_facts") or [])
    hay=f"{query} {facts}"
    if category == "TROUBLESHOOTING":
        return "TROUBLESHOOT_MISSING_CONTEXT" if behavior.get("clarification_required") else "TROUBLESHOOT_DIRECT"
    if category == "PRIVATE_BUSINESS_QUERY":
        return f"PRIVATE_{sub}"
    if category == "MIXED_KNOWLEDGE_STRUCTURED":
        if "退" in hay or "退款" in hay: return "RETURN_ELIGIBILITY_FROM_PRIVATE_FACT"
        if "保修" in hay or "质保" in hay: return "WARRANTY_WITH_PRODUCT_KNOWLEDGE"
        return f"MIXED_{sub}"
    if category == "SAFETY_GOVERNANCE":
        return f"SAFETY_{sub}"
    if any(k in hay for k in ("规格","参数","尺寸","重量","电压","电流","容量","续航","充电")):
        return "PRODUCT_SPEC_LOOKUP"
    if any((e.get("authority") or "").lower()=="policy" for e in evidence) or any(k in hay for k in ("政策","退货","退款","保修","质保")):
        return "POLICY_LOOKUP"
    return "KNOWLEDGE_DOCUMENT_LOOKUP"


def coverage_fingerprint(sample: dict[str, Any]) -> dict[str, Any]:
    evidence=sample.get("gold_evidence") or []
    facts=sample.get("gold_facts") or []
    contract=sample.get("task_success_contract") or {}
    behavior=sample.get("expected_behavior") or {}
    family=semantic_family(sample)
    source_facts=sorted(f.get("fact_id") for f in facts if f.get("fact_id"))
    evid_ids=sorted(e.get("evidence_id") for e in evidence if e.get("evidence_id"))
    raw="|".join([family,*source_facts,*evid_ids,*sorted(contract.get("required_criteria") or [])])
    return {
        "case_id": sample.get("case_id"), "category": sample.get("category"), "subcategory": sample.get("subcategory"),
        "semantic_family_id": family, "source_fact_ids": source_facts, "evidence_ids": evid_ids,
        "product_model": None, "region": None,
        "structured_entity_type": sorted({e.get("record_type") for e in evidence if e.get("record_type")}),
        "response_type": behavior.get("response_type"), "required_criteria": sorted(contract.get("required_criteria") or []),
        "difficulty": sample.get("difficulty"), "requires_clarification": bool(behavior.get("clarification_required")),
        "requires_recovery": bool(behavior.get("allowed_recovery_actions")), "requires_multi_source": len({e.get("source_type") for e in evidence}) > 1,
        "safety_attack_surface": sample.get("subcategory") if sample.get("category")=="SAFETY_GOVERNANCE" else None,
        "effective_fingerprint": hashlib.sha256(raw.encode()).hexdigest()[:20],
    }


def build_existing_dataset_inventory(root: Path) -> list[dict[str, Any]]:
    data_root=root/'evals/benchmark/data'
    rows=[]
    for path in sorted(data_root.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in {'.json','.jsonl','.csv'}: continue
        try:
            if path.suffix=='.json':
                raw=json.loads(path.read_text(encoding='utf-8'))
                if isinstance(raw,list): records=raw
                elif isinstance(raw,dict) and isinstance(raw.get('samples'),list): records=raw['samples']
                else: records=[]
            elif path.suffix=='.jsonl':
                records=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
            else:
                with path.open(encoding='utf-8-sig',newline='') as f: records=list(csv.DictReader(f))
        except Exception:
            continue
        rel=str(path.relative_to(root)); count=len(records)
        # Only dataset-like payloads get distributions; reports/manifests remain inventory assets with case_count 0.
        sample_like=[r for r in records if isinstance(r,dict) and (r.get('case_id') or r.get('sample_id') or r.get('question') or r.get('query'))]
        categories=Counter(str(r.get('category')) for r in sample_like if r.get('category'))
        subcats=Counter(str(r.get('subcategory')) for r in sample_like if r.get('subcategory'))
        difficulty=Counter(str(r.get('difficulty')) for r in sample_like if r.get('difficulty'))
        response=Counter(str((r.get('expected_behavior') or {}).get('response_type')) for r in sample_like if isinstance(r.get('expected_behavior'),dict) and (r.get('expected_behavior') or {}).get('response_type'))
        source_types=Counter(e.get('source_type') for r in sample_like for e in (r.get('gold_evidence') or []) if isinstance(e,dict) and e.get('source_type'))
        criteria=Counter(c for r in sample_like for c in ((r.get('task_success_contract') or {}).get('required_criteria') or []) if isinstance(r.get('task_success_contract'),dict))
        if '/canonical/dev_v7_3_canonical' in '/'+rel: trust='DEVELOPMENT'; formal=count
        elif '/canonical/validation_v7_3_canonical' in '/'+rel: trust='VALIDATION'; formal=count
        elif 'blind_test_inputs' in rel: trust='HISTORICAL_UNVERIFIED'; formal=0
        elif 'representative_seed' in rel or '/security/' in '/'+rel or '/calibration/' in '/'+rel or 'multi_turn_candidates' in rel: trust='FIXTURE_OR_UNREVIEWED'; formal=0
        else: trust='LEGACY_OR_DIAGNOSTIC'; formal=0
        annotation=Counter(str((r.get('annotation_metadata') or {}).get('annotation_status')) for r in sample_like if isinstance(r.get('annotation_metadata'),dict) and (r.get('annotation_metadata') or {}).get('annotation_status'))
        rows.append({"dataset_id":path.stem,"path":rel,"schema_version":None,"trust_level":trust,"annotation_status":dict(annotation),"case_count":count if sample_like else 0,"asset_record_count":count,"formal_eligible_count":formal,"category_distribution":dict(categories),"subcategory_distribution":dict(subcats),"difficulty_distribution":dict(difficulty),"source_type_distribution":dict(source_types),"response_type_distribution":dict(response),"success_criterion_distribution":dict(criteria),"gold_evidence_coverage":sum(bool(r.get('gold_evidence')) for r in sample_like),"gold_fact_coverage":sum(bool(r.get('gold_facts')) for r in sample_like),"safety_constraint_coverage":sum(bool(r.get('safety_constraints')) for r in sample_like),"identity_coverage":sum(bool((r.get('input') or {}).get('identity')) for r in sample_like if isinstance(r.get('input'),dict)),"review_status":dict(annotation)})
    return rows


def audit_canonical_coverage(samples: list[dict[str, Any]]) -> dict[str, Any]:
    fps=[coverage_fingerprint(s) for s in samples]
    exact=Counter(_norm((s.get('input') or {}).get('query')) for s in samples)
    eff=Counter(x['effective_fingerprint'] for x in fps)
    families=Counter(x['semantic_family_id'] for x in fps)
    goldsets=Counter(tuple(sorted(x['source_fact_ids'])) for x in fps)
    evidsets=Counter(tuple(sorted(x['evidence_ids'])) for x in fps)
    sections=Counter(e for x in fps for e in x['evidence_ids'])
    return {
        "raw_case_count":len(samples), "effective_case_count":len(eff), "surface_variations":sum(v-1 for v in eff.values() if v>1),
        "semantic_family_count":len(families), "semantic_family_distribution":dict(families),
        "exact_or_normalized_query_duplicates":sum(v-1 for v in exact.values() if v>1),
        "same_gold_fact_set_duplicates":sum(v-1 for v in goldsets.values() if v>1),
        "same_gold_evidence_set_duplicates":sum(v-1 for v in evidsets.values() if v>1),
        "cases_per_evidence":dict(sections.most_common()), "fingerprints":fps,
    }
