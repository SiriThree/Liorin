"""Benchmark Expansion Phase D0 source-space auditing."""
from .contracts import AtomicFact, StructuredFactCandidate, RelationRecord, CapacityEstimate
from .coverage_audit import semantic_family, coverage_fingerprint, audit_canonical_coverage
from .runner import run_dataset_expansion_audit

__all__=["AtomicFact","StructuredFactCandidate","RelationRecord","CapacityEstimate","semantic_family","coverage_fingerprint","audit_canonical_coverage","run_dataset_expansion_audit"]

from .d1_runner import run_private_business_expansion

__all__ = list(globals().get("__all__", [])) + ["run_private_business_expansion"]

# Phase D2 Private Business Gold preparation
from .d2_runner import run_private_gold_preparation

# Phase D3 Private Business dual independent annotation
from .d3_runner import run_private_dual_annotation, validate_batch_integrity

# Phase D3-R real annotator runtime recovery
from .d3_runtime import run_d3r_runtime_recovery, annotation_runtime_readiness

# Phase E0 source-grounded Mixed Structured + Knowledge candidate construction
from .e0_runner import run_mixed_expansion
__all__ = list(globals().get("__all__", [])) + ["run_mixed_expansion"]

# Phase E1 Mixed Gold preparation + annotation packet freeze
from .e1_runner import run_mixed_gold_preparation
__all__ = list(globals().get("__all__", [])) + ["run_mixed_gold_preparation"]

# Phase E1-R Manual-routing query scope repair + Mixed Gold re-freeze
from .e1r_runner import run_manual_scope_repair
__all__ = list(globals().get("__all__", [])) + ["run_manual_scope_repair"]

# Phase F0 Troubleshooting / Clarification / Recovery-oriented candidate expansion
from .f0_runner import run_troubleshooting_expansion
__all__ = list(globals().get("__all__", [])) + ["run_troubleshooting_expansion"]

# Phase G0.1 Knowledge Source Space audit / KnowledgeSourceUnit construction
from .g0_1_runner import run_knowledge_source_audit
__all__ = list(globals().get("__all__", [])) + ["run_knowledge_source_audit"]

from .g0_2_runner import run_knowledge_task_planning

# Phase G0.3 Controlled Knowledge query rendering + Candidate validation
from .g0_3_runner import run_knowledge_query_rendering
__all__ = list(globals().get("__all__", [])) + ["run_knowledge_query_rendering"]

# Phase G0.4 Knowledge Gold preparation + annotation packet freeze
from .g0_4_runner import run_knowledge_gold_preparation
__all__ = list(globals().get("__all__", [])) + ["run_knowledge_gold_preparation"]

# Phase H0 Safety/Governance surface revalidation + candidate expansion
from .h0_runner import run_safety_expansion
__all__ = list(globals().get("__all__", [])) + ["run_safety_expansion"]
