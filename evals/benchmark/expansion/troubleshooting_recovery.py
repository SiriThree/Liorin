"""Phase F0 recovery-oriented candidate policy, grounded in current verifier actions."""
from __future__ import annotations

RECOVERY_ACTIONS=("CLARIFY","REWRITE","SUPPLEMENT","DECOMPOSE","RELAX_FILTERS","HANDOFF")


def recovery_action_matrix() -> dict:
    # Grounded in retrieval.protocols.VerificationAction and evidence_verifier decision branches.
    rows={
        "MISSING_REQUIRED_CONTEXT": {"CLARIFY":"ALLOWED","REWRITE":"FORBIDDEN","SUPPLEMENT":"FORBIDDEN","DECOMPOSE":"NOT_SUPPORTED","RELAX_FILTERS":"NOT_SUPPORTED","HANDOFF":"CONDITIONAL"},
        "AMBIGUOUS_QUERY": {"CLARIFY":"CONDITIONAL","REWRITE":"ALLOWED","SUPPLEMENT":"FORBIDDEN","DECOMPOSE":"CONDITIONAL","RELAX_FILTERS":"NOT_SUPPORTED","HANDOFF":"CONDITIONAL"},
        "INSUFFICIENT_EVIDENCE": {"CLARIFY":"CONDITIONAL","REWRITE":"CONDITIONAL","SUPPLEMENT":"ALLOWED","DECOMPOSE":"CONDITIONAL","RELAX_FILTERS":"CONDITIONAL","HANDOFF":"CONDITIONAL"},
        "WRONG_SCOPE_RETRIEVAL": {"CLARIFY":"FORBIDDEN","REWRITE":"ALLOWED","SUPPLEMENT":"CONDITIONAL","DECOMPOSE":"CONDITIONAL","RELAX_FILTERS":"CONDITIONAL","HANDOFF":"CONDITIONAL"},
        "PARTIAL_PROCEDURE": {"CLARIFY":"FORBIDDEN","REWRITE":"CONDITIONAL","SUPPLEMENT":"ALLOWED","DECOMPOSE":"CONDITIONAL","RELAX_FILTERS":"NOT_SUPPORTED","HANDOFF":"CONDITIONAL"},
        "CONFLICTING_EVIDENCE": {"CLARIFY":"FORBIDDEN","REWRITE":"FORBIDDEN","SUPPLEMENT":"FORBIDDEN","DECOMPOSE":"NOT_SUPPORTED","RELAX_FILTERS":"NOT_SUPPORTED","HANDOFF":"ALLOWED"},
    }
    return {
        "schema_version":"f0-recovery-matrix-1",
        "source_code_refs":["retrieval/protocols.py:VerificationAction","retrieval/evidence_verifier.py:verify_evidence"],
        "actions":list(RECOVERY_ACTIONS),"triggers":rows,
        "observed_first_pass_failure":0,"real_recovery_runs":0,"recovered_cases":0,
    }
