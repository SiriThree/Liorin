"""Deterministic routing and entity scope for production retrieval."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from retrieval.filters import InvalidRetrievalFilter
from retrieval.protocols import QueryUnderstanding, RetrievalFilters, RetrievalPrincipal, RetrievalSubquery


class RetrievalRoute(StrEnum):
    DOCUMENT_HYBRID = "document_hybrid"
    STRUCTURED_DATABASE = "structured_database"
    METADATA_EXACT = "metadata_exact"
    DENSE_ONLY = "dense_only"
    SPARSE_ONLY = "sparse_only"


@dataclass(frozen=True)
class RouteResolution:
    route: RetrievalRoute
    reason: str


@dataclass(frozen=True)
class SearchScope:
    filters: RetrievalFilters
    scope_fields: tuple[str, ...]
    scope_source: str
    scope_values_count: int


def resolve_retrieval_route(subquery: RetrievalSubquery) -> RouteResolution:
    """Resolve a subquery into one explicit retriever lane.

    The resolver honors planner source/mode first.  Entities in the broader query
    understanding never open another route by themselves.
    """

    source = str(subquery.source or "all")
    mode = str(subquery.retrieval_mode or "hybrid")
    if source in {"database", "structured_db"} or mode == "database":
        return RouteResolution(RetrievalRoute.STRUCTURED_DATABASE, "source_or_mode_database")
    if source == "metadata" or mode == "metadata":
        return RouteResolution(RetrievalRoute.METADATA_EXACT, "source_or_mode_metadata")
    if mode == "dense":
        return RouteResolution(RetrievalRoute.DENSE_ONLY, "mode_dense")
    if mode == "sparse":
        return RouteResolution(RetrievalRoute.SPARSE_ONLY, "mode_sparse")
    return RouteResolution(RetrievalRoute.DOCUMENT_HYBRID, "document_source_default")


def _as_values(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _merge_field(data: dict[str, Any], field: str, deterministic: Any) -> bool:
    incoming = _as_values(deterministic)
    if not incoming:
        return False
    existing = _as_values(data.get(field))
    if not existing:
        data[field] = incoming if len(incoming) > 1 else incoming[0]
        return True
    existing_folded = {item.casefold(): item for item in existing}
    incoming_folded = {item.casefold(): item for item in incoming}
    overlap_keys = sorted(set(existing_folded) & set(incoming_folded))
    if not overlap_keys:
        raise InvalidRetrievalFilter(
            f"planner filter {field} conflicts with deterministic entity scope"
        )
    overlap = [existing_folded[key] for key in overlap_keys]
    data[field] = overlap if len(overlap) > 1 else overlap[0]
    return True


def derive_search_scope(
    understanding: QueryUnderstanding,
    subquery: RetrievalSubquery,
    principal: RetrievalPrincipal,
) -> SearchScope:
    """Merge planner filters with safe hard entity scope.

    Error codes intentionally remain query/reranker signals in this first pass;
    they are not mandatory metadata filters because many useful troubleshooting
    chunks do not carry precise error-code metadata.
    """

    data = dict(subquery.filters or {})
    scope_fields: list[str] = []

    if understanding.product_id:
        if _merge_field(data, "product_id", understanding.product_id):
            scope_fields.append("product_id")
        data.pop("product_name", None)
        data.pop("product_model", None)
    elif understanding.product_models:
        if _merge_field(data, "product_model", understanding.product_models):
            scope_fields.append("product_model")
        data.pop("product_name", None)
    elif understanding.product_name:
        if _merge_field(data, "product_name", understanding.product_name):
            scope_fields.append("product_name")

    for field in ("document_id", "policy_id"):
        value = getattr(understanding, field)
        if value and _merge_field(data, field, value):
            scope_fields.append(field)

    filters = RetrievalFilters.from_legacy(
        data,
        tenant_id=principal.tenant_id if principal.can_retrieve else None,
        source=subquery.source,
    )
    value_count = sum(len(_as_values(getattr(filters, field))) for field in scope_fields)
    return SearchScope(
        filters=filters,
        scope_fields=tuple(scope_fields),
        scope_source="query_understanding+planner_filters" if scope_fields else "planner_filters",
        scope_values_count=value_count,
    )
