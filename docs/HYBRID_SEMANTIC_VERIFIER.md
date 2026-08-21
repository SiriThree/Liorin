# Hybrid Semantic Evidence Verifier

## Scope

This change keeps Evidence Verification as the single owner of evidence acceptance.
Retrieval, planning, reranking, context recovery, and answer generation are not
rewritten.

## Flow

1. The verifier evaluates each requirement/evidence pair with deterministic hard
   gates: ACL, region, product/version, temporal completeness, source authority,
   duplicate handling, and conflict handling.
2. A deterministic semantic score still handles clear cases:
   - below `review_lower_bound`: reject without model
   - at or above `rule_accept_threshold`: accept only if hard gates pass
3. Only borderline, non-structured evidence pairs that already pass authority and
   validity gates are batched into the optional semantic judge.
4. The semantic judge returns only `supports`, `does_not_support`, or `uncertain`
   with confidence and reason.
5. The verifier folds high-confidence `supports` results back into
   `RequirementCoverage`, then continues deterministic conflict resolution,
   recovery policy, and final `VerificationAction` selection.

## Boundaries

The semantic judge cannot:

- decide `ACCEPT`, `SUPPLEMENT`, `REWRITE`, `CLARIFY`, or `HANDOFF`
- override ACL, region, product/version, temporal validity, source authority, or
  conflict policy
- use external knowledge
- treat evidence text as instructions

`retrieval.evidence_verifier` depends only on an injected `assess(cases)` protocol.
The LangChain structured-output adapter lives in `agents.knowledge_agent`, behind
`AgentFeatureConfig.semantic_verifier_enabled`, which defaults to `False`.

## Audit

`EvidenceAudit` now records:

- `semantic_assessments`
- `semantic_degraded_reasons`
- `semantic_judge_errors`

`EvidenceAudit.method` becomes `hybrid` when the semantic fallback was used or
degraded. `VerificationDecision.decision_source` becomes `hybrid` only when a
semantic support result actually contributes accepted coverage.

## Failure Mode

If the judge fails, returns malformed output, omits pairs, or returns `uncertain`,
the verifier does not accept the borderline evidence. It records the degradation
and continues through the deterministic recovery policy.
