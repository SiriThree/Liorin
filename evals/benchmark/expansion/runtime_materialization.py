"""Deterministic D2 candidate-token -> realistic fixture-query materialization."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from .gold_draft import resolve_candidate_source


MATERIALIZATION_VERSION = "private-business-runtime-materialization-v1"
_TOKEN_RE = re.compile(r"<(ORDER|TICKET|WARRANTY)_REF:[0-9a-f]+>", re.I)


def _raw_identifier(candidate: Mapping[str, Any], record: Mapping[str, Any]) -> str:
    return str(record[{"order": "order_id", "ticket": "ticket_id", "warranty": "case_id"}[candidate["record_type"]]])


def materialize_runtime_query(root: Path, candidate: Mapping[str, Any]) -> str:
    record = resolve_candidate_source(root, candidate)
    raw = _raw_identifier(candidate, record)
    query = str(candidate["candidate_query"])
    matches = _TOKEN_RE.findall(query)
    if len(matches) != 1:
        raise ValueError(f"candidate {candidate['candidate_id']} expected one construction entity token")
    expected = str(candidate["record_type"]).upper()
    if matches[0].upper() != expected:
        raise ValueError(f"candidate {candidate['candidate_id']} entity token type mismatch")
    materialized = _TOKEN_RE.sub(raw, query, count=1)
    if "<" in materialized and "_REF:" in materialized:
        raise ValueError("construction token remained after runtime materialization")
    return materialized


def build_runtime_materialization(root: Path, candidate: Mapping[str, Any]) -> dict[str, Any]:
    query = materialize_runtime_query(root, candidate)
    record = resolve_candidate_source(root, candidate)
    raw = _raw_identifier(candidate, record)
    redacted = query.replace(raw, f"[{str(candidate['record_type']).upper()}_FIXTURE_ID]")
    # The structured DB is explicitly synthetic fixture data (data/structured/SCHEMA.md).
    # Raw fixture IDs may enter future RuntimeCaseInput, but are intentionally not
    # persisted in public D2 artifacts.
    return {
        "candidate_id": candidate["candidate_id"],
        "materialization_version": MATERIALIZATION_VERSION,
        "policy": "RAW_FIXTURE_ID_ALLOWED",
        "status": "MATERIALIZABLE",
        "runtime_query_redacted": redacted,
        "runtime_query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "fixture_identifier_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "fixture_identifier_type": {"order": "order_id", "ticket": "ticket_id", "warranty": "case_id"}[candidate["record_type"]],
        "raw_identifier_persisted": False,
        "deterministic": True,
        "naturalness_checks": {
            "construction_token_absent_after_materialization": True,
            "sql_or_schema_syntax_absent": not any(x in query.casefold() for x in ("select ", " from ", " where ", "customer_id", "tenant_id")),
            "answer_value_not_intentionally_injected": True,
        },
    }
