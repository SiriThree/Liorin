"""Phase G0.1 Knowledge Source Space construction contracts.

These contracts are dataset-construction artifacts only. They never alter or
feed the Production runtime directly and do not represent Candidate/Gold data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class KnowledgeFactAudit:
    fact_id: str
    document_id: str
    section_id: str
    source_type: str
    product_id: str | None
    fact_type: str
    fact_text: str
    relationship: str
    task_usability: str
    independently_askable: bool
    required_local_context: tuple[str, ...]
    category_ownership: str
    ownership_overlaps: tuple[str, ...]
    quality_flags: tuple[str, ...]

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        for key in ("required_local_context", "ownership_overlaps", "quality_flags"):
            state[key] = list(state[key])
        return state


@dataclass(frozen=True)
class CoherentFactGroup:
    group_id: str
    document_id: str
    section_id: str
    fact_ids: tuple[str, ...]
    relationship: str
    group_semantics: str
    minimal: bool
    independently_askable_as_group: bool
    required_context: tuple[str, ...]
    reason: str

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["fact_ids"] = list(self.fact_ids)
        state["required_context"] = list(self.required_context)
        return state


@dataclass(frozen=True)
class KnowledgeSourceUnit:
    source_unit_id: str
    document_id: str
    section_ids: tuple[str, ...]
    source_type: str
    product_id: str | None
    product_family: str | None
    semantic_topic: str
    unit_type: str
    fact_ids: tuple[str, ...]
    primary_fact_ids: tuple[str, ...]
    supporting_fact_ids: tuple[str, ...]
    context_fact_ids: tuple[str, ...]
    fact_relationship: str
    independent_askable_fact_ids: tuple[str, ...]
    coherent_fact_group_ids: tuple[str, ...]
    required_local_context: tuple[str, ...]
    category_ownership: str
    knowledge_usability: str
    semantic_signature: str
    cross_product_signature: str
    quality_flags: tuple[str, ...]

    @property
    def benchmark_usable(self) -> bool:
        return self.knowledge_usability in {"BENCHMARK_USABLE", "BENCHMARK_USABLE_WITH_GROUPING"}

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["benchmark_usable"] = self.benchmark_usable
        for key in (
            "section_ids", "fact_ids", "primary_fact_ids", "supporting_fact_ids",
            "context_fact_ids", "independent_askable_fact_ids", "coherent_fact_group_ids",
            "required_local_context", "quality_flags",
        ):
            state[key] = list(state[key])
        return state
