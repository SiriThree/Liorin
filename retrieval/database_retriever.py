"""Parameterized structured database retrieval with tenant/ACL enforcement."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from langchain_core.documents import Document

from config import DEFAULT_DB_PATH
from retrieval.budget import RetrievalBudget
from retrieval.filters import (
    InvalidRetrievalFilter,
    document_matches_filters,
    validate_filters,
)
from retrieval.fusion import RetrievedEvidence, RetrieverExecutionResult
from retrieval.metadata import extract_business_entities, utc_now_iso
from retrieval.protocols import (
    RetrievalContribution,
    RetrievalError,
    RetrievalFilters,
    RetrievalPrincipal,
    RetrieverStatus,
    ScoreSemantics,
)
from retrieval.trace import trace_event
from retrieval.security import redact_text
from retrieval.resilience import call_with_resilience, RetryPolicy

MAX_DATABASE_ROWS = 50


@dataclass(frozen=True)
class SQLTemplate:
    template_id: str
    sql: str
    entity_field: str
    authority: str


SQL_TEMPLATES: dict[str, tuple[SQLTemplate, ...]] = {
    "order_id": (
        SQLTemplate(
            "order_lookup_v2",
            """
            SELECT o.order_id, o.status, o.order_date, o.total_amount,
                   o.tracking_number, o.cancel_reason, o.channel,
                   p.product_id, p.name AS product_name,
                   oi.quantity, oi.price_per_unit
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            JOIN order_items oi ON oi.order_id = o.order_id
            JOIN products p ON p.product_id = oi.product_id
            WHERE o.order_id = ? AND c.tenant_id = ?
            ORDER BY oi.order_item_id
            LIMIT ?
            """,
            "order_id",
            "transactional_database",
        ),
        SQLTemplate(
            "order_events_v2",
            """
            SELECT ose.status, ose.happened_at, ose.actor, ose.note
            FROM order_status_events ose
            JOIN orders o ON o.order_id = ose.order_id
            JOIN customers c ON c.customer_id = o.customer_id
            WHERE ose.order_id = ? AND c.tenant_id = ?
            ORDER BY ose.happened_at
            LIMIT ?
            """,
            "order_id",
            "transactional_database",
        ),
    ),
    "ticket_id": (
        SQLTemplate(
            "ticket_lookup_v2",
            """
            SELECT t.ticket_id, t.status, t.issue_type, t.priority, t.summary,
                   t.order_id, t.product_id, p.name AS product_name,
                   t.created_at, t.assigned_team
            FROM tickets t
            JOIN customers c ON c.customer_id = t.customer_id
            LEFT JOIN products p ON p.product_id = t.product_id
            WHERE t.ticket_id = ? AND c.tenant_id = ?
            LIMIT ?
            """,
            "ticket_id",
            "support_case_database",
        ),
        SQLTemplate(
            "ticket_events_v2",
            """
            SELECT te.event_type, te.happened_at, te.actor, te.note
            FROM ticket_events te
            JOIN tickets t ON t.ticket_id = te.ticket_id
            JOIN customers c ON c.customer_id = t.customer_id
            WHERE te.ticket_id = ? AND c.tenant_id = ?
            ORDER BY te.happened_at
            LIMIT ?
            """,
            "ticket_id",
            "support_case_database",
        ),
    ),
    "customer_id": (
        SQLTemplate(
            "customer_recent_orders_v2",
            """
            SELECT o.order_id, o.status, o.order_date, o.total_amount,
                   o.tracking_number, o.channel
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            WHERE o.customer_id = ? AND c.tenant_id = ?
            ORDER BY o.order_date DESC
            LIMIT ?
            """,
            "customer_id",
            "transactional_database",
        ),
        SQLTemplate(
            "customer_open_tickets_v2",
            """
            SELECT t.ticket_id, t.status, t.issue_type, t.summary,
                   t.product_id, p.name AS product_name, t.created_at
            FROM tickets t
            JOIN customers c ON c.customer_id = t.customer_id
            LEFT JOIN products p ON p.product_id = t.product_id
            WHERE t.customer_id = ? AND c.tenant_id = ? AND t.status != 'resolved'
            ORDER BY t.created_at DESC
            LIMIT ?
            """,
            "customer_id",
            "support_case_database",
        ),
    ),
}


def _can_query_database(principal: RetrievalPrincipal, entities: dict[str, list[str]]) -> bool:
    """Apply least-privilege tool access before opening a database connection."""

    if not principal.can_retrieve:
        return False
    if principal.is_privileged:
        return True
    permissions = set(principal.permissions)
    if "classification:confidential:read" not in permissions:
        return False
    if "database:read" in permissions:
        return True
    if set(entities) == {"ticket_id"} and "ticket:read" in permissions:
        return True
    customer_ids = set(entities.get("customer_id", []))
    return "customer" in principal.roles and principal.user_id in customer_ids


def _open_readonly_connection(timeout_ms: int) -> sqlite3.Connection:
    db_uri = DEFAULT_DB_PATH.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=max(0.001, timeout_ms / 1000))
    conn.row_factory = sqlite3.Row
    deadline = perf_counter() + max(0.001, timeout_ms / 1000)
    conn.set_progress_handler(lambda: 1 if perf_counter() >= deadline else 0, 5_000)
    return conn


def _execute_template(
    template: SQLTemplate,
    *,
    entity: str,
    tenant_id: str,
    timeout_ms: int,
) -> list[dict[str, Any]]:
    """Execute a fixed SQL template with bound parameters only."""

    with closing(_open_readonly_connection(timeout_ms)) as conn:
        cursor = conn.execute(template.sql, (entity, tenant_id, MAX_DATABASE_ROWS))
        return [dict(row) for row in cursor.fetchmany(MAX_DATABASE_ROWS)]


_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


def _redact_free_text(value: Any, *, limit: int = 600) -> str:
    return redact_text(value, keep_business_ids=False, limit=limit)


def _sanitize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Redact free-text PII and mask operational identifiers before LLM use."""

    safe_rows: list[dict[str, Any]] = []
    for row in rows:
        safe: dict[str, Any] = {}
        for field, value in row.items():
            if field == "tracking_number" and value:
                text = str(value)
                safe[field] = "*" * max(0, len(text) - 4) + text[-4:]
            elif field in {"summary", "note", "actor", "cancel_reason"}:
                safe[field] = _redact_free_text(value)
            else:
                safe[field] = value
        safe_rows.append(safe)
    return safe_rows


def _safe_content(template_id: str, entity_field: str, entity: str, rows: list[dict[str, Any]]) -> str:
    # Fixed templates select allow-listed columns; this second layer masks operational
    # identifiers and redacts likely PII in free-text fields. SQL and tenant IDs are
    # never exposed in the model context.
    payload = {
        "query_type": template_id,
        "entity": {entity_field: entity},
        "row_count": len(rows),
        "records": _sanitize_rows(rows),
    }
    return "结构化业务数据：\n" + json.dumps(payload, ensure_ascii=False, default=str)


def _database_access_permissions(
    principal: RetrievalPrincipal,
    entity_field: str,
) -> list[str]:
    if principal.is_privileged:
        return []
    base = "ticket:read" if entity_field == "ticket_id" and "database:read" not in principal.permissions else "database:read"
    return [base, "classification:confidential:read"]


def _row_metadata(rows: list[dict[str, Any]]) -> dict[str, Any]:
    product_ids = list(dict.fromkeys(
        str(row["product_id"]) for row in rows if row.get("product_id") not in (None, "")
    ))
    product_names = list(dict.fromkeys(
        str(row["product_name"]) for row in rows if row.get("product_name") not in (None, "")
    ))
    metadata: dict[str, Any] = {
        "product_ids": product_ids,
        "product_names": product_names,
    }
    if product_ids:
        metadata["product_id"] = product_ids[0]
    if product_names:
        metadata["product_name"] = product_names[0]
    return metadata



def _entity_owned_by_principal(
    entity_field: str,
    entity: str,
    principal: RetrievalPrincipal,
    *,
    timeout_ms: int,
) -> bool:
    """Enforce row ownership for customer identities before returning any rows."""
    if "customer" not in principal.roles or principal.is_privileged:
        return True
    if entity_field == "customer_id":
        return entity == principal.user_id
    sql_by_field = {
        "order_id": """
            SELECT 1 FROM orders o JOIN customers c ON c.customer_id=o.customer_id
            WHERE o.order_id=? AND c.tenant_id=? AND c.customer_id=? LIMIT 1
        """,
        "ticket_id": """
            SELECT 1 FROM tickets t JOIN customers c ON c.customer_id=t.customer_id
            WHERE t.ticket_id=? AND c.tenant_id=? AND c.customer_id=? LIMIT 1
        """,
    }
    sql = sql_by_field.get(entity_field)
    if not sql:
        return False
    with closing(_open_readonly_connection(timeout_ms)) as conn:
        return conn.execute(sql, (entity, principal.tenant_id, principal.user_id)).fetchone() is not None

def database_search(
    query: str,
    *,
    principal: RetrievalPrincipal,
    entities: dict[str, list[str]] | None = None,
    filters: RetrievalFilters | dict | None = None,
    subquery_id: str | None = None,
    k: int = 5,
    budget: RetrievalBudget | None = None,
) -> RetrieverExecutionResult:
    retriever = "structured_database"
    started = perf_counter()
    entities = entities or extract_business_entities(query)
    business_entities = {
        field: values for field, values in entities.items() if field in SQL_TEMPLATES and values
    }
    if not business_entities:
        return RetrieverExecutionResult(
            retriever,
            RetrieverStatus.SKIPPED_BY_PLAN,
        )
    if not _can_query_database(principal, business_entities):
        error = RetrievalError(
            stage=retriever,
            error_type="PermissionDenied",
            message="principal lacks structured database access",
            dependency="acl",
            subquery_id=subquery_id,
        )
        return RetrieverExecutionResult(retriever, RetrieverStatus.PERMISSION_DENIED, errors=[error])
    try:
        unified = validate_filters(filters, principal=principal, source="structured_db")
    except InvalidRetrievalFilter as exc:
        error = RetrievalError(
            stage=retriever,
            error_type="InvalidFilter",
            message=str(exc),
            dependency="filters",
            subquery_id=subquery_id,
        )
        return RetrieverExecutionResult(retriever, RetrieverStatus.INVALID_FILTER, errors=[error])
    if unified.tenant_id and unified.tenant_id != principal.tenant_id:
        error = RetrievalError(
            stage=retriever,
            error_type="PermissionDenied",
            message="tenant filter does not match principal",
            dependency="acl",
            subquery_id=subquery_id,
        )
        return RetrieverExecutionResult(retriever, RetrieverStatus.PERMISSION_DENIED, errors=[error])
    if budget and not budget.reserve_database():
        status = RetrieverStatus.TIMEOUT if budget.latency_exceeded else RetrieverStatus.SKIPPED_BY_BUDGET
        return RetrieverExecutionResult(retriever, status, degraded_reasons=["database budget unavailable"])

    evidences: list[RetrievedEvidence] = []
    errors: list[RetrievalError] = []
    trace: list[dict[str, Any]] = []
    for entity_field, values in business_entities.items():
        for entity in values[:1]:
            for template in SQL_TEMPLATES[entity_field]:
                timeout_ms = budget.remaining_timeout_ms if budget else 25_000
                if timeout_ms <= 0:
                    errors.append(RetrievalError(
                        stage=retriever,
                        error_type="TimeoutError",
                        message="database retrieval budget exhausted",
                        retryable=True,
                        dependency="sqlite",
                        subquery_id=subquery_id,
                    ))
                    break
                try:
                    if not _entity_owned_by_principal(
                        entity_field, entity, principal, timeout_ms=timeout_ms
                    ):
                        errors.append(RetrievalError(
                            stage=retriever,
                            error_type="PermissionDenied",
                            message="principal does not own requested business record",
                            retryable=False,
                            dependency="acl_owner",
                            subquery_id=subquery_id,
                        ))
                        continue
                    rows = call_with_resilience(
                        "sqlite",
                        lambda: _execute_template(
                            template,
                            entity=entity,
                            tenant_id=principal.tenant_id,
                            timeout_ms=timeout_ms,
                        ),
                        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.005, max_delay_seconds=0.02),
                        retry_if=lambda exc: isinstance(exc, sqlite3.OperationalError),
                        max_concurrency=8,
                    )
                except sqlite3.OperationalError as exc:
                    error_type = "TimeoutError" if "interrupt" in str(exc).lower() else type(exc).__name__
                    errors.append(RetrievalError(
                        stage=retriever,
                        error_type=error_type,
                        message=str(exc),
                        retryable=True,
                        dependency="sqlite",
                        subquery_id=subquery_id,
                    ))
                    continue
                except Exception as exc:
                    errors.append(RetrievalError(
                        stage=retriever,
                        error_type=type(exc).__name__,
                        message=str(exc),
                        retryable=True,
                        dependency="sqlite",
                        subquery_id=subquery_id,
                    ))
                    continue
                event = trace_event(
                    retriever,
                    "template_complete",
                    subquery_id=subquery_id,
                    status="success" if rows else "no_results",
                    sql_template_id=template.template_id,
                    entity_field=entity_field,
                    entity_identifier=entity,
                    row_count=len(rows),
                    authority=template.authority,
                )
                trace.append(event)
                if not rows:
                    continue
                document_id = f"db:{template.template_id}:{entity}"
                doc = Document(
                    page_content=_safe_content(template.template_id, entity_field, entity, rows),
                    metadata={
                        "document_id": document_id,
                        "doc_id": document_id,
                        "section_id": document_id,
                        "chunk_id": document_id,
                        "parent_id": document_id,
                        "section": "结构化数据库结果",
                        "section_path": f"database / {template.template_id}",
                        "section_start": 0,
                        "section_end": 0,
                        "chunk_start": 0,
                        "chunk_end": 0,
                        "doc_type": "structured_db",
                        "source": "structured_db",
                        "source_file": "liorin.db",
                        "version": "runtime",
                        "effective_from": None,
                        "effective_to": None,
                        "tenant_id": principal.tenant_id,
                        "allowed_user_ids": [principal.user_id] if "customer" in principal.roles else [],
                        "allowed_groups": list(principal.groups),
                        "required_permissions": _database_access_permissions(principal, entity_field),
                        "classification": "confidential",
                        "visibility": "private",
                        "owner": principal.user_id if "customer" in principal.roles else None,
                        "source_trust": "internal_database",
                        "security_status": "safe",
                        "acl_identity_public": False,
                        "active": True,
                        **_row_metadata(rows),
                        "sql_template_id": template.template_id,
                        "entity_identifier": entity,
                        "entity_field": entity_field,
                        "row_count": len(rows),
                        "authority": template.authority,
                        "retrieved_at": utc_now_iso(),
                        "language": "zh-CN",
                    },
                )
                if not document_matches_filters(doc.metadata, unified, principal):
                    continue
                contribution = RetrievalContribution(
                    retriever=retriever,
                    subquery_id=subquery_id,
                    rank=len(evidences) + 1,
                    raw_score=1.0,
                    normalized_score=1.0,
                    fusion_weight=1.4,
                    score_semantics=ScoreSemantics.EXACT_HIGHER_BETTER,
                    matched_fields=[entity_field],
                    matched_entities={entity_field: [entity]},
                )
                evidences.append(RetrievedEvidence(
                    document=doc,
                    source=retriever,
                    retrieval_score=1.0,
                    rerank_score=None,
                    query=query,
                    source_type="structured_db",
                    citation_id=str(doc.metadata.get("chunk_id")),
                    score_semantics=ScoreSemantics.EXACT_HIGHER_BETTER,
                    contributions=[contribution],
                    authority=template.authority,
                    provenance={
                        "query_source": "structured_database",
                        "sql_template_id": template.template_id,
                        "entity_identifier": entity,
                        "row_count": len(rows),
                        "authority": template.authority,
                        "timestamp": doc.metadata["retrieved_at"],
                    },
                    matched_chunk_ids=[document_id],
                    trace=[event],
                ))
                if len(evidences) >= k:
                    break
            if len(evidences) >= k:
                break
        if len(evidences) >= k:
            break

    if budget:
        evidences = evidences[:budget.record_candidates(len(evidences))]
    elapsed = (perf_counter() - started) * 1000
    if evidences and errors:
        status = RetrieverStatus.SUCCESS
    elif evidences:
        status = RetrieverStatus.SUCCESS
    elif any(error.error_type == "TimeoutError" for error in errors):
        status = RetrieverStatus.TIMEOUT
    elif errors:
        status = RetrieverStatus.DEPENDENCY_ERROR
    else:
        status = RetrieverStatus.NO_RESULTS
    complete = trace_event(
        retriever,
        "complete",
        subquery_id=subquery_id,
        status=str(status),
        returned_count=len(evidences),
        error_count=len(errors),
        elapsed_ms=round(elapsed, 2),
    )
    trace.append(complete)
    return RetrieverExecutionResult(
        retriever=retriever,
        status=status,
        evidences=evidences,
        errors=errors,
        trace=trace,
        degraded_reasons=[error.message for error in errors],
        soft_timeout=status == RetrieverStatus.TIMEOUT,
        candidate_count=len(evidences),
    )
