"""Controlled rendering for H0 Safety candidates."""
from __future__ import annotations
import hashlib, json
from typing import Any
VERSION="safety-candidate-h0-v1"

def render_candidate(plan: dict[str,Any]) -> dict[str,Any]:
    query=str(plan["user_request_semantics"]).strip()
    cid="SAFECAND-"+hashlib.sha256((plan["scenario_id"]+"|"+VERSION+"|"+query).encode()).hexdigest()[:16].upper()
    return {
      "candidate_id":cid,"scenario_id":plan["scenario_id"],"render_version":VERSION,"candidate_query":query,"language":"zh-CN",
      "surface_id":plan["surface_id"],"scenario_type":plan["scenario_type"],"ownership_relation":plan["ownership_relation"],"permission_relation":plan["permission_relation"],
      "protected_asset":plan["target_resource"]["asset_type"],"attack_vector":plan["attack_vector"],"expected_security_action":plan["required_security_action"],
      "forbidden_behaviors":list(plan["forbidden_behaviors"]),"required_audit_behavior":plan["required_audit_behavior"],"runtime_materialization":plan["runtime_materialization"],
      "policy_refs":list(plan["source_policy_refs"]),"difficulty":plan["difficulty"],"scenario_family_id":plan["scenario_family_id"],"future_split_keys":plan["future_split_keys"],
      "production_run":False,"observed_block":False,"observed_violation":False,"observed_security_outcome":"NOT_RUN",
      "dedup_signature":plan["effective_signature"],"query_sha256":hashlib.sha256(query.encode()).hexdigest(),"status":"CANDIDATE","quality_flags":[],"rejection_reasons":[]
    }
