"""Phase D0 dataset-construction audit contracts.

These types describe source capacity and candidate fact space only.  They are
not runtime Gold and are never exposed to ProductionEvaluationAdapter.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CapacityConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ExpansionPriority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


@dataclass(frozen=True)
class AtomicFact:
    fact_id: str
    source_id: str
    document_id: str
    section_id: str
    subject: str
    predicate: str
    normalized_value: str
    value_type: str = "STRING"
    region: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    authority: str | None = None
    fact_scope: str = "DOCUMENT"
    ambiguity: str = "LOW"
    benchmark_usable: bool = True
    notes: str | None = None
    fact_type: str = "GENERAL"

    def to_state(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StructuredFactCandidate:
    fact_type: str
    record_type: str
    field_path: str
    exposed_by_templates: tuple[str, ...]
    record_count: int
    non_null_count: int
    distinct_value_count: int
    benchmark_usable: bool
    privacy_class: str
    example_value_redacted: str | None = None

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["exposed_by_templates"] = list(self.exposed_by_templates)
        return state


@dataclass(frozen=True)
class RelationRecord:
    relation_id: str
    left_type: str
    right_type: str
    join_key: str
    source: str
    production_resolvable: bool
    gold_resolvable: bool
    candidate_task_types: tuple[str, ...] = ()
    relation_count: int | None = None
    notes: str | None = None

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["candidate_task_types"] = list(self.candidate_task_types)
        return state


@dataclass(frozen=True)
class CapacityEstimate:
    category: str
    minimum: int
    recommended: int
    upper_reasonable_bound: int
    confidence: CapacityConfidence
    evidence: tuple[str, ...]

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["confidence"] = self.confidence.value
        state["evidence"] = list(self.evidence)
        return state
