# Liorin Production Governance

This package contains controls that are orthogonal to retrieval quality:

- `degradation.py` / `degradation_matrix.json`: explicit dependency failure matrix.
- `feedback.py`: privacy-safe feedback ingestion, triage, human review and regression-candidate export.
- `health.py`: dependency circuit, read-only database and index consistency health snapshot.
- `release_gate.py` / `release_gate_config.json`: executable fail-closed release policy.

Quality and latency thresholds in `release_gate_config.json` intentionally remain
`null` until a reviewed, reproducible production-like baseline is approved. Required
null thresholds produce `blocked_unconfigured`; they are not silently treated as a
pass.
