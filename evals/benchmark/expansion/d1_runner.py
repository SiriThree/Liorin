"""Phase D1 Private Business source-grounded candidate-pool runner."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .candidate_contracts import CandidateStatus
from .candidate_dedup import deduplicate_candidates
from .candidate_generator import GENERATION_VERSION, generate_private_business_candidates
from .candidate_reporting import build_distribution
from .candidate_validation import validate_candidate
from .legacy_evidence_alias import build_legacy_section_alias_map

D1_SCHEMA_VERSION="1.0"
RANDOM_SEED=0


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str,Any]]) -> None:
    path.write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n" for x in rows),encoding="utf-8")


def _sha256(path: Path) -> str:
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()


def _tool_registry_fingerprint(d0: Path) -> str:
    obj=json.loads((d0/'structured_source_inventory.json').read_text(encoding='utf-8'))
    payload=[{"template_id":x['template_id'],"sql":x['sql'],"parameter_order":x['parameter_order'],"output_fields":x.get('output_fields')} for x in obj['sql_templates']]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def run_private_business_expansion(root: str | Path, d0_dir: str | Path, output_dir: str | Path) -> dict[str,Any]:
    root=Path(root); d0=Path(d0_dir); out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    required=['structured_fact_inventory.json','structured_source_inventory.json','production_capability_inventory.json','source_reference_validation.json','phase_d0_summary.json']
    missing=[x for x in required if not (d0/x).exists()]
    if missing: raise FileNotFoundError(f"missing D0 artifacts: {missing}")

    alias=build_legacy_section_alias_map(root,d0); _write_json(out/'legacy_section_alias_map.json',alias)
    candidates=generate_private_business_candidates(root)
    for c in candidates: validate_candidate(root,d0,c)
    dedup=deduplicate_candidates(candidates)
    raw=[c.to_state() for c in candidates]
    validated=[c.to_state() for c in candidates if c.status is CandidateStatus.SOURCE_VALIDATED]
    rejected=[c.to_state() for c in candidates if c.status is CandidateStatus.REJECTED]
    _write_jsonl(out/'private_business_raw_candidates.jsonl',raw)
    _write_jsonl(out/'private_business_source_validated.jsonl',validated)
    _write_jsonl(out/'private_business_rejected.jsonl',rejected)

    dist=build_distribution(candidates)
    _write_json(out/'private_business_distribution.json',dist)
    _write_json(out/'private_business_state_coverage.json',dist['state_distribution'])
    structured_facts=json.loads((d0/'structured_fact_inventory.json').read_text(encoding='utf-8'))
    usable_fact_types=sorted(x['fact_type'] for x in structured_facts if x.get('benchmark_usable'))
    covered_fact_types=sorted(dist['field_distribution'])
    not_covered=sorted(set(usable_fact_types)-set(covered_fact_types))
    _write_json(out/'private_business_field_coverage.json',{
        "production_ordinary_gold_usable_types":len(usable_fact_types),
        "covered_types":len(covered_fact_types),
        "covered":covered_fact_types,
        "not_covered":not_covered,
        "not_covered_reason":{
            "customer.customer_id":"customer profile is outside D1 normal private-query scope",
            "customer.segment":"customer profile is outside D1 normal private-query scope",
            "order.order_id":"entity selector, not useful as the target fact",
            "ticket.ticket_id":"entity selector, not useful as the target fact",
            "warranty.case_id":"entity selector, not useful as the target fact",
        },
        "field_distribution":dist['field_distribution'],
        "field_combination_distribution":dist['field_combination_distribution'],
    })
    _write_json(out/'private_business_entity_concentration.json',{k:dist[k] for k in ['unique_customers','unique_entities','unique_products','unique_tenants','unique_customer_ratio','unique_entity_ratio','max_per_customer','max_per_entity','max_per_product','max_per_tenant','tenant_concentration_ratio','product_concentration_ratio']})
    fam=Counter(x['semantic_family_id'] for x in validated); rejected_fam=Counter(x['semantic_family_id'] for x in rejected)
    _write_json(out/'private_business_semantic_families.json',{"source_validated":dict(fam),"rejected":dict(rejected_fam),"family_count":len(fam)})
    _write_json(out/'private_business_dedup_report.json',dedup)

    d0_summary=json.loads((d0/'phase_d0_summary.json').read_text(encoding='utf-8'))
    db=root/'data/structured/liorin.db'
    manifest={
        "schema_version":D1_SCHEMA_VERSION,"generation_version":GENERATION_VERSION,
        "d0_inventory_hash":d0_summary.get('inventory_hash_sha256'),"source_inventory_hash":hashlib.sha256((d0/'structured_source_inventory.json').read_bytes()).hexdigest(),
        "db_sha256":_sha256(db),"tool_registry_fingerprint":_tool_registry_fingerprint(d0),
        "raw_candidate_count":len(raw),"source_validated_count":len(validated),"rejected_count":len(rejected),
        "construction_timestamp":datetime.now(timezone.utc).isoformat(),"random_seed":RANDOM_SEED,"generation_method":"DETERMINISTIC_SOURCE_PLAN + CONTROLLED_LANGUAGE_RENDERER",
        "raw_candidate_sha256":hashlib.sha256("".join(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")) for x in raw).encode()).hexdigest(),
        "source_validated_sha256":hashlib.sha256("".join(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")) for x in validated).encode()).hexdigest(),
        "formal_metric_eligible":False,"human_reviewed":False,"production_agent_executed":False,"judge_executed":False,
    }
    _write_json(out/'private_business_candidate_manifest.json',manifest)
    summary={
        "phase":"D1_PRIVATE_BUSINESS","status":"COMPLETE" if alias['all_deterministically_resolved'] and len(validated)>=60 else "PARTIAL",
        "legacy_alias_total":alias['total_legacy_document_refs'],"legacy_alias_resolved":alias['resolved'],"legacy_alias_ambiguous":alias['ambiguous'],"legacy_alias_missing":alias['missing'],
        "raw_candidates":len(raw),"source_validated":len(validated),"rejected":len(rejected),"surface_variations":0,"effective_candidates":len(validated),
        "semantic_families":len(fam),"domain_distribution":dist['domain_distribution'],"unique_entity_ratio":dist['unique_entity_ratio'],"unique_customer_ratio":dist['unique_customer_ratio'],
        "unique_products":dist['unique_products'],"unique_tenants":dist['unique_tenants'],"difficulty_distribution":dist['difficulty_distribution'],
        "source_validation_rate":(len(validated)/len(raw) if raw else None),
        "field_types_covered":len(covered_fact_types),"production_ordinary_gold_usable_types":len(usable_fact_types),
        "concentration_warnings":[
            *(["TENANT_OVER_10_PERCENT"] if (dist['tenant_concentration_ratio'] or 0)>0.10 else []),
            *(["PRODUCT_OVER_10_PERCENT"] if (dist['product_concentration_ratio'] or 0)>0.10 else []),
            *(["CUSTOMER_DIVERSITY_BELOW_80_PERCENT"] if (dist['unique_customer_ratio'] or 0)<0.80 else []),
            *(["ENTITY_REUSE_OVER_2"] if dist['max_per_entity']>2 else []),
        ],
        "dedup":dedup,
        "new_formal_cases":0,"new_human_reviewed_gold":0,"production_agent_execution":"NOT RUN","judge_execution":"NOT RUN",
        "existing_formal_canonical_cases":39,
    }
    _write_json(out/'phase_d1_summary.json',summary)
    return summary
