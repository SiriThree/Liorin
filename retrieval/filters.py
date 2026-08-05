"""Unified metadata and ACL filtering for all retrieval paths."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from pydantic import ValidationError

from config import DEFAULT_INDEX_REGISTRY_PATH

from retrieval.protocols import RetrievalFilters, RetrievalPrincipal
from retrieval.index_lifecycle import IndexLifecycleManager


ALLOWED_FILTER_FIELDS = frozenset(RetrievalFilters.model_fields)
MILVUS_FILTER_FIELDS = frozenset(
    {
        "tenant_id",
        "doc_type",
        "product_id",
        "product_name",
        "product_model",
        "error_code",
        "region",
        "language",
        "source",
        "classification",
        "visibility",
        "owner",
        "document_id",
        "policy_id",
        "active",
        "allowed_user_ids",
        "allowed_groups",
        "required_permissions",
        "acl_identity_public",
        "effective_from_ts",
        "effective_to_ts",
    }
)

KNOWN_RETRIEVAL_PERMISSIONS = frozenset(
    {
        "knowledge:read",
        "database:read",
        "ticket:read",
        "classification:confidential:read",
        "classification:restricted:read",
        "tenant:cross_read",
        "admin:audit",
    }
)


class InvalidRetrievalFilter(ValueError):
    """Raised when planner/user supplied filters violate the allow-list."""


def validate_filters(
    value: RetrievalFilters | dict[str, Any] | None,
    *,
    principal: RetrievalPrincipal,
    source: str | None = None,
) -> RetrievalFilters:
    """Normalize old dictionaries into the strict unified filter protocol."""

    explicit_tenant = isinstance(value, RetrievalFilters) and bool(value.tenant_id)
    if isinstance(value, dict):
        explicit_tenant = bool(value.get("tenant_id"))
    try:
        filters = RetrievalFilters.from_legacy(
            value,
            tenant_id=principal.tenant_id if principal.can_retrieve else None,
            source=source,
        )
    except ValidationError as exc:
        raise InvalidRetrievalFilter(str(exc)) from exc
    if principal.authenticated:
        if filters.tenant_id and filters.tenant_id != principal.tenant_id and "tenant:cross_read" not in principal.permissions:
            raise InvalidRetrievalFilter("tenant_id cannot differ from authenticated principal")
        source_values = set(_as_values(filters.source))
        if not explicit_tenant and source_values and source_values <= {"manual", "policy", "faq"}:
            filters.tenant_id = None
    else:
        if filters.tenant_id not in (None, "public", "global"):
            raise InvalidRetrievalFilter("anonymous retrieval is limited to public/global tenant data")
        filters.tenant_id = filters.tenant_id or "public"
        filters.classification = "public"
        filters.visibility = "public"
    return filters


def _as_values(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _metadata_values(metadata: dict[str, Any], field: str) -> list[str]:
    aliases = {
        "document_id": ("document_id", "doc_id"),
        "error_code": ("error_code", "error_codes"),
        "product_model": ("product_model", "product_models"),
        "source": ("source", "doc_type"),
        "product_id": ("product_id", "product_ids"),
        "product_name": ("product_name", "product_names"),
    }
    keys = aliases.get(field, (field,))
    values: list[str] = []
    for key in keys:
        raw = metadata.get(key)
        values.extend(_as_values(raw))
    return values


def _matches_value(actual: list[str], expected: Any) -> bool:
    wanted = {item.casefold() for item in _as_values(expected)}
    if not wanted:
        return True
    available = {item.casefold() for item in actual}
    return bool(wanted & available)


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def principal_can_access(metadata: dict[str, Any], principal: RetrievalPrincipal) -> bool:
    """Evaluate default-deny tenant, identity, ownership and classification rules."""

    if str(metadata.get("security_status") or "safe") == "quarantined":
        return False
    document_id = str(metadata.get("document_id") or metadata.get("doc_id") or "")
    if document_id and IndexLifecycleManager(DEFAULT_INDEX_REGISTRY_PATH).is_deleted(document_id):
        return False
    if metadata.get("active", True) is not True:
        return False

    tenant_raw = metadata.get("tenant_id")
    visibility = str(metadata.get("visibility") or "tenant").casefold()
    classification = str(metadata.get("classification") or "").casefold()
    allowed_users = set(_as_values(metadata.get("allowed_user_ids")))
    allowed_groups = set(_as_values(metadata.get("allowed_groups")))
    required_permissions = set(_as_values(metadata.get("required_permissions")))
    owner = str(metadata.get("owner") or "")

    # Missing principal is represented by an anonymous principal.  Public access is
    # explicit, not inferred from an absent ACL list or a default tenant value.
    if not principal.authenticated:
        return (
            str(tenant_raw or "").casefold() in {"public", "global"}
            and visibility == "public"
            and classification == "public"
            and not allowed_users
            and not allowed_groups
            and not required_permissions
        )

    if not tenant_raw:
        return False
    tenant_id = str(tenant_raw)
    if (
        tenant_id.casefold() in {"public", "global"}
        and visibility == "public"
        and classification == "public"
        and not allowed_users
        and not allowed_groups
        and not required_permissions
    ):
        return True
    if tenant_id != principal.tenant_id and "tenant:cross_read" not in principal.permissions:
        return False

    if visibility == "private" and owner != principal.user_id:
        if principal.user_id not in allowed_users and not (set(principal.groups) & allowed_groups):
            if not principal.is_privileged:
                return False
    elif allowed_users or allowed_groups:
        if principal.user_id not in allowed_users and not (set(principal.groups) & allowed_groups):
            if not principal.is_privileged:
                return False

    if required_permissions and not required_permissions.issubset(set(principal.permissions)):
        if not principal.is_privileged:
            return False

    if classification not in {"public", "internal", "confidential", "restricted"}:
        return False
    if classification in {"confidential", "restricted"}:
        permission = f"classification:{classification}:read"
        if permission not in principal.permissions and not principal.is_privileged:
            return False
    return True


def document_matches_filters(
    metadata: dict[str, Any],
    filters: RetrievalFilters,
    principal: RetrievalPrincipal,
) -> bool:
    """Apply the same filter semantics used by Dense, BM25, lookup and expansion."""

    if not principal_can_access(metadata, principal):
        return False
    if filters.tenant_id and str(metadata.get("tenant_id") or "") != filters.tenant_id:
        return False
    if filters.active_only and metadata.get("active", True) is not True:
        return False

    for field in (
        "doc_type",
        "product_id",
        "product_name",
        "product_model",
        "error_code",
        "region",
        "language",
        "source",
        "classification",
        "visibility",
        "owner",
        "document_id",
        "policy_id",
    ):
        expected = getattr(filters, field)
        if expected not in (None, "", [], {}):
            if not _matches_value(_metadata_values(metadata, field), expected):
                return False

    if filters.allowed_user_ids and principal.user_id not in filters.allowed_user_ids:
        return False
    if filters.allowed_groups and not (set(principal.groups) & set(filters.allowed_groups)):
        return False
    if filters.required_permissions and not set(filters.required_permissions).issubset(
        set(principal.permissions)
    ):
        return False

    effective_at = _parse_time(filters.effective_at)
    if effective_at:
        effective_from = _parse_time(
            metadata.get("effective_from") or metadata.get("effective_date")
        )
        effective_to = _parse_time(metadata.get("effective_to"))
        if effective_from and effective_at < effective_from:
            return False
        if effective_to and effective_at > effective_to:
            return False
    return True


def _escape_milvus_string(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _string_expression(field: str, values: Iterable[str]) -> str | None:
    safe_values = [_escape_milvus_string(value) for value in values if str(value).strip()]
    if not safe_values:
        return None
    if len(safe_values) == 1:
        return f'{field} == "{safe_values[0]}"'
    joined = ", ".join(f'"{value}"' for value in safe_values)
    return f"{field} in [{joined}]"


def _json_array(values: Iterable[str]) -> str:
    return "[" + ", ".join(
        f'"{_escape_milvus_string(value)}"' for value in values if str(value).strip()
    ) + "]"


def _milvus_acl_expression(principal: RetrievalPrincipal) -> str | None:
    """Build identity/classification pre-filter for the rebuilt dynamic schema.

    ``acl_identity_public`` is materialized at ingestion.  User/group arrays are
    stored in Milvus' dynamic JSON field, so JSON_CONTAINS operators are used.
    Required permissions are still checked after recall as defense in depth because
    subset evaluation is not portable across supported Milvus versions.
    """

    if not principal.authenticated:
        return '(visibility == "public" and classification == "public" and acl_identity_public == true)'
    if principal.is_privileged:
        return None
    identity_terms = ["acl_identity_public == true"]
    if principal.user_id:
        identity_terms.append(
            f'JSON_CONTAINS(allowed_user_ids, "{_escape_milvus_string(principal.user_id)}")'
        )
    if principal.groups:
        identity_terms.append(
            f"JSON_CONTAINS_ANY(allowed_groups, {_json_array(principal.groups)})"
        )

    allowed_classifications = ["public", "internal"]
    for classification in ("confidential", "restricted"):
        if f"classification:{classification}:read" in principal.permissions:
            allowed_classifications.append(classification)
    classification_expr = _string_expression("classification", allowed_classifications)
    denied_permissions = sorted(KNOWN_RETRIEVAL_PERMISSIONS - set(principal.permissions))
    permission_expr = None
    if denied_permissions:
        permission_expr = (
            "not JSON_CONTAINS_ANY(required_permissions, "
            + _json_array(denied_permissions)
            + ")"
        )
    identity_expr = "(" + " or ".join(identity_terms) + ")"
    parts = [identity_expr]
    if classification_expr:
        parts.append(f"({classification_expr})")
    if permission_expr:
        parts.append(f"({permission_expr})")
    return "(" + " and ".join(parts) + ")"


def retrieval_cache_key(
    query: str,
    *,
    filters: RetrievalFilters,
    principal: RetrievalPrincipal,
    source: str | None = None,
    corpus_version: str | None = None,
) -> str:
    """Return a non-reversible result-cache key including all access inputs.

    Stage 2 does not enable a retrieval-result cache, but any future cache must use
    this helper rather than a query-only key.  Corpus indexes are unfiltered data
    indexes and therefore intentionally use only the corpus version.
    """

    payload = {
        "query": query,
        "source": source,
        "corpus_version": corpus_version,
        "filters": json.loads(filters.cache_key()),
        "principal": json.loads(principal.cache_key()),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_milvus_expression(filters: RetrievalFilters, principal: RetrievalPrincipal) -> str:
    """Compile an allow-listed, escaped Milvus pre-filter expression.

    The Stage-2 corpus schema writes tenant, identity ACL and metadata fields to
    every chunk. Existing collections must be rebuilt before production use.
    ``document_matches_filters`` repeats every rule after recall as defense in depth.
    """

    expressions: list[str] = []
    if "tenant:cross_read" in principal.permissions:
        tenant_values = []
    elif filters.tenant_id:
        tenant_values = [filters.tenant_id]
    elif principal.authenticated:
        tenant_values = [principal.tenant_id, "public", "global"]
    else:
        tenant_values = [principal.tenant_id or "public"]
    tenant_expr = _string_expression("tenant_id", tenant_values)
    if tenant_expr:
        expressions.append(tenant_expr)
    acl_expr = _milvus_acl_expression(principal)
    if acl_expr:
        expressions.append(acl_expr)
    for field in (
        "doc_type",
        "product_id",
        "product_name",
        "product_model",
        "error_code",
        "region",
        "language",
        "source",
        "classification",
        "visibility",
        "owner",
        "document_id",
        "policy_id",
    ):
        if field not in MILVUS_FILTER_FIELDS:
            continue
        values = _as_values(getattr(filters, field))
        expr = _string_expression(field, values)
        if expr:
            expressions.append(expr)
    effective_at = _parse_time(filters.effective_at)
    if effective_at:
        epoch = int(effective_at.timestamp())
        expressions.append(f"effective_from_ts <= {epoch}")
        expressions.append(f"(effective_to_ts == 0 or effective_to_ts >= {epoch})")
    if filters.active_only:
        expressions.append("active == true")
    return " and ".join(expressions)
