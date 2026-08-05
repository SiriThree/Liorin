"""ACL-safe section-level Small-to-Big context expansion."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval.budget import RetrievalBudget
from retrieval.document_corpus import get_section_context
from retrieval.fusion import RetrievedEvidence
from retrieval.protocols import RetrievalError, RetrievalFilters, RetrievalPrincipal
from retrieval.trace import trace_event


@dataclass
class ExpansionResult:
    evidences: list[RetrievedEvidence]
    errors: list[RetrievalError] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)


def _merge_section_evidence(primary: RetrievedEvidence, duplicate: RetrievedEvidence) -> None:
    existing = {
        (item.retriever, item.subquery_id, item.rank, item.raw_score)
        for item in primary.contributions
    }
    for contribution in duplicate.contributions:
        key = (
            contribution.retriever,
            contribution.subquery_id,
            contribution.rank,
            contribution.raw_score,
        )
        if key not in existing:
            primary.contributions.append(contribution)
            existing.add(key)
    primary.trace.extend(duplicate.trace)
    primary.coverage_tags = list(dict.fromkeys([*primary.coverage_tags, *duplicate.coverage_tags]))
    primary.matched_chunk_ids = list(
        dict.fromkeys(
            [
                *primary.matched_chunk_ids,
                *duplicate.matched_chunk_ids,
                str(duplicate.document.metadata.get("chunk_id", "")),
            ]
        )
    )
    chunks = primary.provenance.setdefault("section_chunk_provenance", [])
    chunks.append(
        {
            "chunk_id": duplicate.document.metadata.get("chunk_id"),
            "chunk_start": duplicate.document.metadata.get("chunk_start"),
            "chunk_end": duplicate.document.metadata.get("chunk_end"),
        }
    )


def expand_parent_context(
    evidences: list[RetrievedEvidence],
    *,
    principal: RetrievalPrincipal,
    filters: RetrievalFilters,
    budget: RetrievalBudget | None = None,
    per_parent_chars: int = 2400,
    subquery_id: str | None = None,
) -> ExpansionResult:
    """Expand each authorized section once and preserve originals on budget exhaustion."""

    if not evidences:
        return ExpansionResult([])
    expanded: list[RetrievedEvidence] = []
    by_section: dict[str, RetrievedEvidence] = {}
    errors: list[RetrievalError] = []
    traces: list[dict[str, Any]] = []
    degraded: list[str] = []

    for evidence in evidences:
        section_id = str(
            evidence.document.metadata.get("section_id")
            or evidence.document.metadata.get("parent_id")
            or ""
        )
        if not section_id:
            expanded.append(evidence)
            continue
        if section_id in by_section:
            # Merge only after the section was successfully expanded.  If expansion
            # was skipped by budget, each original chunk remains independently present.
            primary = by_section[section_id]
            if primary.parent_context:
                _merge_section_evidence(primary, evidence)
                continue
            expanded.append(evidence)
            continue

        remaining = budget.remaining_context_chars if budget else per_parent_chars
        if remaining <= 0:
            degraded.append("context budget exhausted; original evidence retained")
            expanded.append(evidence)
            by_section[section_id] = evidence
            continue
        max_chars = min(per_parent_chars, remaining)
        context, section_metadata, denial = get_section_context(
            section_id,
            principal=principal,
            filters=filters,
            max_chars=max_chars,
            anchor_start=evidence.document.metadata.get("chunk_start"),
            anchor_end=evidence.document.metadata.get("chunk_end"),
            corpus_version=evidence.document.metadata.get("corpus_version"),
        )
        if denial:
            permission_denied = denial == "parent_section_permission_denied"
            error = RetrievalError(
                stage="parent_expansion",
                error_type="PermissionDenied" if permission_denied else "ParentFilterMismatch",
                message=denial,
                retryable=False,
                dependency="acl" if permission_denied else "metadata_hierarchy",
                subquery_id=subquery_id,
            )
            errors.append(error)
            event = trace_event(
                "parent_expansion",
                "permission_denied" if permission_denied else "filter_mismatch",
                subquery_id=subquery_id,
                status="permission_denied" if permission_denied else "filter_mismatch",
                section_id=section_id,
            )
            traces.append(event)
            evidence.trace.append(event)
            expanded.append(evidence)
            by_section[section_id] = evidence
            continue
        if context:
            chars = len(context)
            if budget is None or budget.reserve_context(chars):
                evidence.parent_context = context
                evidence.provenance.setdefault(
                    "section_chunk_provenance",
                    [
                        {
                            "chunk_id": evidence.document.metadata.get("chunk_id"),
                            "chunk_start": evidence.document.metadata.get("chunk_start"),
                            "chunk_end": evidence.document.metadata.get("chunk_end"),
                        }
                    ],
                )
                event = trace_event(
                    "parent_expansion",
                    "expanded",
                    subquery_id=subquery_id,
                    status="success",
                    section_id=section_id,
                    context_chars=chars,
                    section_path=(section_metadata or {}).get("section_path"),
                )
                evidence.trace.append(event)
                traces.append(event)
            else:
                degraded.append("context budget exhausted; original evidence retained")
        expanded.append(evidence)
        by_section[section_id] = evidence

    return ExpansionResult(
        evidences=expanded,
        errors=errors,
        trace=traces,
        degraded_reasons=list(dict.fromkeys(degraded)),
    )
