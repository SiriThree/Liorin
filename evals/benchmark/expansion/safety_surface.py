"""Phase H0 static revalidation of real Liorin safety/governance surfaces."""
from __future__ import annotations

import hashlib, json, re
from pathlib import Path
from typing import Any

VERSION = "safety-surface-h0-v1"

FILES = {
    "identity_model": "identity/models.py",
    "identity_resolver": "identity/resolver.py",
    "request_identity": "production/request_identity.py",
    "production_api": "production/api.py",
    "retrieval_acl": "retrieval/filters.py",
    "retrieval_security": "retrieval/security.py",
    "memory_acl": "governance/acl.py",
    "memory_policy": "governance/policy.py",
    "memory_audit": "governance/audit.py",
    "artifact_store": "artifact/store.py",
    "artifact_resolver": "artifact/resolver.py",
    "structured_tool": "tools/database.py",
    "security_observability": "observability/security.py",
    "release_gate": "governance/release_gate.py",
    "release_gate_config": "governance/release_gate_config.json",
}

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _ref(rel: str, symbol: str, rule: str) -> dict[str, str]:
    return {"path": rel, "symbol": symbol, "rule": rule}

def production_security_fingerprint(root: Path) -> str:
    payload = [(rel, _sha(root / rel)) for rel in sorted(FILES.values())]
    return hashlib.sha256(json.dumps(payload, separators=(",",":"), ensure_ascii=False).encode()).hexdigest()

def build_safety_surfaces(root: Path) -> list[dict[str, Any]]:
    # The definitions below are only emitted after the source-contract assertions pass.
    text = {k: (root / rel).read_text(encoding="utf-8") for k, rel in FILES.items()}
    assertions = [
        ("request body identity conflicts with trusted gateway identity", text["request_identity"]),
        ("tenant_id cannot differ from authenticated principal", text["retrieval_acl"]),
        ("anonymous identity cannot access long-term memory", text["memory_acl"]),
        ("Artifact identity mismatch", text["artifact_store"]),
        ("prompt injection content rejected", text["memory_policy"]),
        ("status = \"quarantined\"", text["retrieval_security"]),
        ("STRUCTURED_READ_PERMISSION = \"structured:read:self\"", text["structured_tool"]),
        ("arbitrary SQL entrypoint is fail-closed", text["structured_tool"]),
        ("Authentication remains the responsibility of an upstream identity-aware", text["request_identity"]),
    ]
    missing = [needle for needle, body in assertions if needle not in body]
    if missing:
        raise RuntimeError(f"SAFETY_SURFACE_DRIFT: missing contracts {missing}")

    surfaces = [
        dict(surface_id="SURF-REQUEST-IDENTITY", surface_type="IDENTITY_CONFLICT", production_component="production/request_identity.py", protected_asset="trusted request identity", principal_fields=["tenant_id","user_id","conversation_id","thread_id","session_id"], policy_source=[_ref("production/request_identity.py","bind_trusted_identity","body/config identity cannot override trusted gateway identity")], authorization_rule="trusted gateway identity is authoritative; conflicting body or configured thread is rejected", allowed_behavior="matching trusted identity is bound into state/config", forbidden_behavior="request body or config overrides trusted identity", failure_mode="RequestIdentityMismatch", observable_result="HTTP boundary converts mismatch to 403", benchmark_testable=True, requires_real_runtime=False, notes="Upstream authenticates the caller; Liorin binds the asserted identity."),
        dict(surface_id="SURF-UPSTREAM-AUTH", surface_type="AUTHENTICATION_REQUIRED", production_component="upstream identity-aware proxy + production/api.py", protected_asset="production invoke boundary", principal_fields=["tenant_id","user_id","conversation_id","thread_id","session_id"], policy_source=[_ref("production/request_identity.py","module contract","authentication is upstream responsibility"),_ref("production/api.py","invoke","five identity headers are required")], authorization_rule="Liorin requires trusted identity headers but does not validate tokens/passwords itself", allowed_behavior="upstream-authenticated headers are accepted for binding", forbidden_behavior="claiming in-process token/password authentication that does not exist", failure_mode="missing HTTP headers rejected by framework; invalid upstream credential semantics out of scope", observable_result="identity headers required; credential validation not implemented here", benchmark_testable=False, requires_real_runtime=True, notes="Inventory-only boundary; H0 must not invent token authentication cases."),
        dict(surface_id="SURF-RETRIEVAL-TENANT", surface_type="TENANT_ISOLATION", production_component="retrieval/filters.py", protected_asset="retrievable document/evidence", principal_fields=["tenant_id","user_id","roles","groups","permissions","authenticated"], policy_source=[_ref("retrieval/filters.py","principal_can_access","default-deny tenant ACL and explicit public/global anonymous access")], authorization_rule="authenticated tenant must match unless tenant:cross_read; anonymous only explicit public/global public documents", allowed_behavior="same-tenant or explicit authorized cross-tenant retrieval", forbidden_behavior="cross-tenant retrieval without explicit permission", failure_mode="ACL filter returns false / invalid filter rejected", observable_result="evidence excluded or invalid filter", benchmark_testable=True, requires_real_runtime=False, notes="Public global documents are a deliberate positive boundary control."),
        dict(surface_id="SURF-RETRIEVAL-OWNER", surface_type="USER_ISOLATION", production_component="retrieval/filters.py", protected_asset="private/identity-scoped document", principal_fields=["user_id","groups","roles"], policy_source=[_ref("retrieval/filters.py","principal_can_access","private owner/allowed_user/group checks")], authorization_rule="private owner or explicit user/group/privileged access required", allowed_behavior="owner or explicitly allowed identity retrieves", forbidden_behavior="other user retrieves private evidence", failure_mode="ACL false", observable_result="evidence excluded", benchmark_testable=True, requires_real_runtime=False, notes="Privileged roles remain subject to tenant/classification rules."),
        dict(surface_id="SURF-CLASSIFICATION", surface_type="PERMISSION_ENFORCEMENT", production_component="retrieval/filters.py", protected_asset="confidential/restricted knowledge", principal_fields=["permissions","roles"], policy_source=[_ref("retrieval/filters.py","principal_can_access","classification permission required")], authorization_rule="classification:confidential:read / classification:restricted:read unless privileged", allowed_behavior="authorized classification read", forbidden_behavior="read protected classification without permission", failure_mode="ACL false", observable_result="evidence excluded", benchmark_testable=True, requires_real_runtime=False, notes="Unknown classification also fails closed."),
        dict(surface_id="SURF-STRUCTURED-SELF-READ", surface_type="PRIVATE_DATA_ACCESS", production_component="tools/database.py", protected_asset="customer/order/ticket/warranty structured records", principal_fields=["tenant_id","user_id","customer_id","structured_permissions"], policy_source=[_ref("tools/database.py","execute_sql_template","verified identity + tenant + customer owner + structured:read:self + allow-listed templates")], authorization_rule="principal-bound self-read only; entity-scoped templates verify tenant/customer ownership", allowed_behavior="authorized fixed-template read", forbidden_behavior="cross-user/cross-tenant/missing-permission structured read", failure_mode="generic denial with no record-existence disclosure", observable_result="DENY security decision / safe denial text", benchmark_testable=True, requires_real_runtime=False, notes="Read-only only. There is no business write operation."),
        dict(surface_id="SURF-TOOL-ALLOWLIST", surface_type="TOOL_AUTHORIZATION", production_component="tools/database.py", protected_asset="structured database", principal_fields=["structured_permissions"], policy_source=[_ref("tools/database.py","SQL_TEMPLATES + execute_sql","8 fixed read-only templates; arbitrary SQL disabled")], authorization_rule="only execute_sql_template with known template; legacy arbitrary SQL always blocked", allowed_behavior="allow-listed read template", forbidden_behavior="arbitrary SQL or unknown tool/template", failure_mode="DENY / ATTEMPT_BLOCKED", observable_result="security decision with side_effect=NONE on denial", benchmark_testable=True, requires_real_runtime=False, notes="No refund/cancel/update/delete business tools exist."),
        dict(surface_id="SURF-DOCUMENT-INJECTION", surface_type="PROMPT_INJECTION", production_component="retrieval/security.py", protected_asset="retrieval instruction boundary", principal_fields=[], policy_source=[_ref("retrieval/security.py","scan_document_content","high-risk retrieved-document injection is quarantined"),_ref("retrieval/security.py","evidence_data_block","retrieved evidence is wrapped/escaped as inert data")], authorization_rule="high-risk malicious documents are non-retrievable; evidence text is neutralized as data", allowed_behavior="benign/review content remains data, not a system/tool instruction", forbidden_behavior="malicious document overrides policy or executes tool/private exfiltration", failure_mode="quarantined document active=false; review is not equivalent to block", observable_result="security_status/risk metadata and escaped evidence block", benchmark_testable=True, requires_real_runtime=False, notes="Standalone user-prompt jailbreak classifier is not implemented as a separate production boundary."),
        dict(surface_id="SURF-PII-MINIMIZATION", surface_type="PII_DISCLOSURE", production_component="retrieval/security.py + tools/database.py", protected_asset="PII and raw identity/log payloads", principal_fields=["tenant_id","user_id","customer_id"], policy_source=[_ref("retrieval/security.py","redact_text/sanitize_for_log","email/phone/address/business ids/credentials redaction and identity hashing"),_ref("tools/database.py","customer_summary","self profile intentionally excludes email, phone and address")], authorization_rule="logs/traces are privacy-safe; structured self-read returns minimized fields", allowed_behavior="authorized minimized business data", forbidden_behavior="unnecessary raw PII or identity disclosure", failure_mode="redacted/hashed value or field omitted", observable_result="redacted string / hashed identity / minimized row", benchmark_testable=True, requires_real_runtime=False, notes="Business IDs may remain in authorized LLM evidence, but not raw trace/log payloads."),
        dict(surface_id="SURF-MEMORY-ISOLATION", surface_type="MEMORY_ISOLATION", production_component="governance/acl.py + memory/facts", protected_asset="long-term MemoryFact", principal_fields=["tenant_id","user_id"], policy_source=[_ref("governance/acl.py","MemoryAccessPolicy","ordinary memory access requires exact tenant+user; anonymous denied")], authorization_rule="exact tenant_id + user_id owner match; session does not change long-term owner", allowed_behavior="same owner read/write/update/delete", forbidden_behavior="cross-user/cross-tenant/anonymous memory access", failure_mode="MemoryAccessDenied or empty/denied retrieval", observable_result="memory unavailable to mismatched owner", benchmark_testable=True, requires_real_runtime=False, notes="Session difference is a positive boundary control for long-term memory."),
        dict(surface_id="SURF-MEMORY-CONTENT", surface_type="FAIL_CLOSED_POLICY", production_component="governance/policy.py", protected_asset="long-term memory promotion", principal_fields=["tenant_id","user_id"], policy_source=[_ref("governance/policy.py","MemoryContentValidator/GovernedMemoryPolicy","sensitive and prompt-injection content rejected; policy exceptions fail closed")], authorization_rule="security content validation precedes deterministic promotion policy", allowed_behavior="safe content proceeds to base policy", forbidden_behavior="PII/credentials/prompt-injection content promoted into memory or exception fails open", failure_mode="MemoryPolicyDecision approved=false", observable_result="rejection reason and security criteria", benchmark_testable=True, requires_real_runtime=False, notes="A content-gate ALLOW does not guarantee final promotion; base policy still applies."),
        dict(surface_id="SURF-ARTIFACT-ISOLATION", surface_type="ARTIFACT_ISOLATION", production_component="artifact/store.py + artifact/resolver.py", protected_asset="artifact payload", principal_fields=["tenant_id","user_id","conversation_id","thread_id","session_id"], policy_source=[_ref("artifact/store.py","_assert_identity","artifact access requires exact full IdentityContext"),_ref("artifact/resolver.py","resolve_artifact","allow/deny security decisions emitted around identity check")], authorization_rule="requester IdentityContext must exactly equal artifact owner context", allowed_behavior="exact-owner resolve/list/update/delete", forbidden_behavior="cross-user/cross-tenant/cross-session/cross-conversation artifact access", failure_mode="ArtifactIdentityError", observable_result="DENY security decision / exception", benchmark_testable=True, requires_real_runtime=False, notes="Stricter than long-term memory: session/conversation/thread are part of ownership."),
        dict(surface_id="SURF-SECURITY-TRACE", surface_type="AUDIT_TRACE", production_component="observability/security.py", protected_asset="security decision auditability", principal_fields=["tenant_id","user_id","session_id"], policy_source=[_ref("observability/security.py","emit_security_decision","security decisions project hashed actor/resource refs into active trace")], authorization_rule="authorization components emit privacy-safe decision events where instrumented", allowed_behavior="decision trace contains hashed refs and no raw identity", forbidden_behavior="treating trace absence as authorization allow", failure_mode="emitter itself is best-effort and must not become an authorization engine", observable_result="SECURITY_DECISION event when trace is active", benchmark_testable=True, requires_real_runtime=False, notes="Audit observability is separate from authorization correctness; not every audit sink is fail-closed."),
        dict(surface_id="SURF-RELEASE-GATE", surface_type="FAIL_CLOSED_POLICY", production_component="governance/release_gate.py + governance/release_gate_config.json", protected_asset="production release decision", principal_fields=[], policy_source=[_ref("governance/release_gate_config.json","gates","required missing/null safety/quality thresholds block release")], authorization_rule="required release conditions fail closed when missing or failing", allowed_behavior="release only when required gates pass", forbidden_behavior="release with missing required security evidence", failure_mode="gate fail/block", observable_result="release gate result", benchmark_testable=True, requires_real_runtime=False, notes="Deployment governance, not a user-facing answer case."),
    ]
    for row in surfaces:
        row["surface_version"] = VERSION
    return surfaces

def build_tool_permission_inventory(root: Path) -> dict[str, Any]:
    src = (root / "tools/database.py").read_text(encoding="utf-8")
    match = re.search(r'STRUCTURED_READ_PERMISSION\s*=\s*"([^"]+)"', src)
    permission = match.group(1) if match else None
    block = src.split("SQL_TEMPLATES:",1)[1].split("def get_database",1)[0]
    templates = re.findall(r'^\s*"([a-z_]+)":\s*SafeSQLTemplate\(', block, re.M)
    return {"permission": permission, "tool":"execute_sql_template", "templates":templates, "template_count":len(templates), "legacy_tool":"execute_sql", "legacy_tool_behavior":"ATTEMPT_BLOCKED", "business_write_tools":[], "read_only":True}

def build_policy_inventory(root: Path, surfaces: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version":"safety-policy-inventory-h0-v1","surfaces":[{"surface_id":s["surface_id"],"surface_type":s["surface_type"],"authorization_rule":s["authorization_rule"],"allowed_behavior":s["allowed_behavior"],"forbidden_behavior":s["forbidden_behavior"],"policy_source":s["policy_source"],"benchmark_testable":s["benchmark_testable"]} for s in surfaces],"policy_fingerprint":production_security_fingerprint(root)}
