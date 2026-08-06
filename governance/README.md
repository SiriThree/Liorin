# Liorin Production Governance

This package contains controls orthogonal to retrieval quality:

- `acl.py`: fail-closed tenant/user ownership checks for Memory READ/WRITE/UPDATE/DELETE and explicitly configured tenant administration.
- `policy.py`: stable-fact promotion plus sensitive-content, prompt-injection and content-format validation.
- `audit.py`: queryable lifecycle audit sink and non-blocking audit failure wrapper.
- `lifecycle.py`: user/fact/tenant deletion and fact correction through the real Long-term Memory Runtime.
- `degradation.py` / `degradation_matrix.json`: explicit dependency failure matrix.
- `feedback.py`: privacy-safe feedback ingestion, triage, human review and regression-candidate export.
- `health.py`: dependency circuit, read-only database and index consistency health snapshot.
- `release_gate.py` / `release_gate_config.json`: executable fail-closed release policy.

Memory governance is applied inside `LongTermMemoryRuntime`; ContextBuilder continues to use the same runtime and cannot bypass ACL, expiry or policy checks. The Phase 6 in-memory backends are reference adapters, not claims of durable production storage.
