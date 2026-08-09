"""G0.4 frozen source snapshots and future dual-annotation packets."""
from __future__ import annotations
from typing import Any, Mapping
from .gold_draft import canonical_hash
from .knowledge_gold import KNOWLEDGE_PACKET_VERSION, KNOWLEDGE_SOURCE_SNAPSHOT_VERSION


def annotation_decision_contract() -> dict[str, Any]:
    return {
        "schema_version":"knowledge-gold-review-decision-v1",
        "candidate_id":"<required>",
        "overall_decision":["ACCEPT","ACCEPT_WITH_EDITS","REJECT","NEEDS_HUMAN_REVIEW"],
        "query_quality":"PASS|FAIL|UNCERTAIN",
        "answerability":"PASS|FAIL|UNCERTAIN",
        "gold_fact_correct":"PASS|FAIL|UNCERTAIN",
        "gold_fact_complete":"PASS|FAIL|UNCERTAIN",
        "gold_minimality":"PASS|FAIL|UNCERTAIN",
        "gold_evidence_correct":"PASS|FAIL|UNCERTAIN",
        "comparison_contract_correct":"PASS|FAIL|UNCERTAIN",
        "reasoning_contract_correct":"PASS|FAIL|UNCERTAIN",
        "task_contract_correct":"PASS|FAIL|UNCERTAIN",
        "source_support":"PASS|FAIL|UNCERTAIN",
        "policy_qualification":"PASS|FAIL|UNCERTAIN|NOT_APPLICABLE",
        "suggested_edits":[],"risk_flags":[],"rationale":"<brief source-grounded rationale>",
    }


def build_source_snapshot(candidate: Mapping[str, Any], draft: Mapping[str, Any], sections: Mapping[str, Mapping[str, Any]], facts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    by_section: dict[str,list[str]]={}
    for f in draft["gold_facts"]:
        for sfid in f["source_fact_ids"]:
            row=facts[sfid]; by_section.setdefault(row["section_id"],[]).append(sfid)
    section_rows=[]
    for sid in sorted(by_section):
        sec=sections[sid]; ids=sorted(set(by_section[sid]))
        relevant=[{"fact_id":fid,"fact_text":facts[fid]["fact_text"],"fact_type":facts[fid]["fact_type"],"required_local_context":facts[fid].get("required_local_context",[])} for fid in ids]
        # Keep only local source semantics necessary for Gold review.  Do not expose the whole document.
        local_lines=[]
        txt=str(sec.get("section_text") or "")
        for f in relevant:
            ft=str(f["fact_text"]).strip()
            for line in txt.splitlines():
                if ft and (ft in line or line.strip() in ft) and line.strip(): local_lines.append(line.strip())
        if not local_lines:
            local_lines=[str(x["fact_text"]) for x in relevant]
        minimal_context="\n".join(dict.fromkeys(local_lines))[:1600]
        section_rows.append({
            "document_id":sec["document_id"],"section_id":sid,"heading":sec.get("heading"),"parent_heading":sec.get("parent_heading"),
            "relevant_facts":relevant,"minimal_local_context":minimal_context,
        })
    semantic={
        "source_snapshot_version":KNOWLEDGE_SOURCE_SNAPSHOT_VERSION,
        "candidate_id":candidate["candidate_id"],
        "sections":section_rows,
        "required_evidence_ids":[x["evidence_id"] for x in draft["gold_evidence"] if x["required"]],
    }
    return {**semantic,"snapshot_hash":canonical_hash(semantic)}


def build_annotation_packet(candidate: Mapping[str, Any], draft: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    semantic={
        "packet_version":KNOWLEDGE_PACKET_VERSION,
        "candidate_id":candidate["candidate_id"],"task_plan_id":candidate["task_plan_id"],
        "annotation_task_type":"KNOWLEDGE_GOLD_DRAFT_QUALITY_REVIEW",
        "candidate_query":candidate["candidate_query"],"primary_task_type":candidate["primary_task_type"],
        "answer_scope":candidate["answer_scope"],"source_snapshot":snapshot,
        "gold_draft_to_review":{
            "gold_facts":draft["gold_facts"],"optional_facts":draft["optional_facts"],"gold_evidence":draft["gold_evidence"],
            "comparison_contract":draft["comparison_contract"],"reasoning_contract":draft["reasoning_contract"],
            "task_success_contract_draft":draft["task_success_contract_draft"],"answerability":draft["answerability"],
        },
        "production_capability_summary":{"task_category":"KNOWLEDGE_QA","knowledge_retrieval":"SUPPORTED_BY_ARCHITECTURE_NOT_RUN_IN_G0_4"},
        "review_requirements":draft["review_requirements"],"annotation_decision_contract":annotation_decision_contract(),
        "excluded_information":["Production Prediction","Agent Answer","Agent Trace","Judge Result","Other Annotator Decision","Adjudication","Formal Split","Future Test Membership","G0.3 Review/Reject Decisions"],
    }
    return {**semantic,"packet_sha256":canonical_hash(semantic)}


def build_batch_manifest(packets: list[Mapping[str, Any]], *, candidate_set_hash: str, gold_set_hash: str, construction_hash: str) -> dict[str, Any]:
    semantic={
        "batch_version":"knowledge-annotation-batch-g0.4-v1","candidate_set_hash":candidate_set_hash,"gold_set_hash":gold_set_hash,
        "ready_candidate_count":len(packets),"packet_count":len(packets),"packet_hashes":[p["packet_sha256"] for p in packets],
        "source_snapshot_hashes":[p["source_snapshot"]["snapshot_hash"] for p in packets],"gold_draft_version":"knowledge-gold-draft-g0.4-v1",
        "source_snapshot_version":KNOWLEDGE_SOURCE_SNAPSHOT_VERSION,"packet_schema_version":KNOWLEDGE_PACKET_VERSION,"construction_hash":construction_hash,
        "annotation_runs":0,"human_review_runs":0,"formal_eligible_count":0,
    }
    h=canonical_hash(semantic)
    return {**semantic,"batch_id":f"KNOW-G0.4-{h[:12].upper()}","batch_hash":h}
