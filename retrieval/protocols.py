"""Serializable Agentic RAG protocol models shared by production and benchmark code.

The models in this module are the stable boundary between Knowledge Agent nodes,
retrieval dependencies, checkpoint persistence and benchmark adapters.  They must
remain JSON serializable and must never contain live model, database or lock objects.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _checkpoint_safe(value: Any) -> Any:
    """Convert protocol payloads to plain JSON-safe checkpoint values.

    LangChain ``Document`` is intentionally recognized by interface rather than
    imported here, keeping the protocol module free of optional framework
    dependencies and supporting compatible test/runtime document objects.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _checkpoint_safe(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return _checkpoint_safe(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {str(key): _checkpoint_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_checkpoint_safe(item) for item in value]
    if hasattr(value, "page_content") and hasattr(value, "metadata"):
        return {
            "page_content": str(value.page_content),
            "metadata": _checkpoint_safe(dict(value.metadata or {})),
        }
    raise TypeError(f"protocol state contains non-serializable value: {type(value).__name__}")


class ProtocolModel(BaseModel):
    """Base class for checkpoint-safe protocol objects."""

    model_config = ConfigDict(
        extra="ignore",
        validate_assignment=True,
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    def to_state(self) -> dict[str, Any]:
        """Return a framework-independent JSON-safe LangGraph checkpoint value."""

        return _checkpoint_safe(self.model_dump(mode="python"))


class VerificationAction(StrEnum):
    ACCEPT = "accept"
    SUPPLEMENT = "supplement"
    REWRITE = "rewrite"
    DECOMPOSE = "decompose"
    RELAX_FILTERS = "relax_filters"
    CLARIFY = "clarify"
    HANDOFF = "handoff"


class RetrievalStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    NO_RESULTS = "no_results"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    DEPENDENCY_ERROR = "dependency_error"
    INVALID_FILTER = "invalid_filter"
    PERMISSION_DENIED = "permission_denied"
    VERIFICATION_FAILED = "verification_failed"


class RetrieverStatus(StrEnum):
    """Outcome of one concrete retriever invocation."""

    SUCCESS = "success"
    NO_RESULTS = "no_results"
    SKIPPED_BY_PLAN = "skipped_by_plan"
    SKIPPED_BY_BUDGET = "skipped_by_budget"
    TIMEOUT = "timeout"
    DEPENDENCY_ERROR = "dependency_error"
    INVALID_FILTER = "invalid_filter"
    PERMISSION_DENIED = "permission_denied"


class ScoreSemantics(StrEnum):
    SIMILARITY_HIGHER_BETTER = "similarity_higher_better"
    DISTANCE_LOWER_BETTER = "distance_lower_better"
    BM25_HIGHER_BETTER = "bm25_higher_better"
    EXACT_HIGHER_BETTER = "exact_higher_better"
    RRF_HIGHER_BETTER = "rrf_higher_better"
    RERANK_HIGHER_BETTER = "rerank_higher_better"


class QueryUnderstanding(ProtocolModel):
    """Created by ``understand_query`` and consumed by planning/retrieval.

    Clarification nodes may amend it.  The object is safe to persist.  Requirements
    represent independently answerable user needs rather than keyword bags.
    """

    original_query: str
    normalized_query: str
    language: str = "unknown"
    intent: str | None = None
    task_type: str | None = None
    product_name: str | None = None
    product_id: str | None = None
    product_models: list[str] = Field(default_factory=list)
    product_version: str | None = None
    error_codes: list[str] = Field(default_factory=list)
    order_id: str | None = None
    ticket_id: str | None = None
    customer_id: str | None = None
    document_id: str | None = None
    policy_id: str | None = None
    region: str | None = None
    time_range: dict[str, Any] | None = None
    requirements: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    clarification_question: str | None = None

    @field_validator("product_models", "error_codes", mode="before")
    @classmethod
    def normalize_entity_lists(cls, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        values = value if isinstance(value, list) else [value]
        return list(dict.fromkeys(str(item).strip().upper() for item in values if str(item).strip()))

    @model_validator(mode="after")
    def validate_requirements(self):
        cleaned = list(dict.fromkeys(x.strip() for x in self.requirements if x and x.strip()))
        object.__setattr__(
            self,
            "requirements",
            cleaned or ([self.normalized_query] if self.normalized_query else []),
        )
        return self

    def direct_lookup_entities(self) -> dict[str, list[str]]:
        """Return deterministic entities that justify metadata/database lookup."""

        values: dict[str, list[str]] = {
            "product_model": self.product_models,
            "product_id": [self.product_id.strip().upper()] if self.product_id else [],
            "error_code": self.error_codes,
        }
        for field in (
            "order_id",
            "ticket_id",
            "customer_id",
            "document_id",
            "policy_id",
        ):
            value = getattr(self, field)
            if value:
                values[field] = [str(value).strip().upper()]
        return {key: value for key, value in values.items() if value}

    @classmethod
    def from_legacy(cls, state: dict[str, Any]) -> "QueryUnderstanding":
        obj = state.get("query_understanding")
        if isinstance(obj, cls):
            return obj
        if isinstance(obj, dict):
            return cls.model_validate(obj)
        models = state.get("product_models") or (
            [state.get("product_model")] if state.get("product_model") else []
        )
        errors = state.get("error_codes") or (
            [state.get("error_code")] if state.get("error_code") else []
        )
        return cls(
            original_query=state.get("original_question") or "",
            normalized_query=state.get("rewritten_question")
            or state.get("original_question")
            or "",
            task_type=state.get("task_type"),
            product_name=state.get("product_name"),
            product_id=state.get("product_id"),
            product_models=models,
            product_version=state.get("product_version"),
            error_codes=errors,
            order_id=state.get("order_id"),
            ticket_id=state.get("ticket_id"),
            customer_id=state.get("customer_id"),
            document_id=state.get("document_id"),
            policy_id=state.get("policy_id"),
            region=state.get("region"),
            requirements=state.get("requirements") or [],
            needs_clarification=bool(state.get("needs_clarification")),
            clarification_question=state.get("clarification_question"),
            confidence=float(state.get("understanding_confidence", 0.0)),
        )


class RetrievalFilters(ProtocolModel):
    """Unified allow-listed metadata and ACL filters.

    The planner or compatibility layer creates this object.  All retrieval paths
    consume it before accessing candidates, and parent expansion re-validates it.
    It is checkpoint-safe.  Unknown fields are rejected rather than interpolated.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    tenant_id: str | None = None
    allowed_user_ids: list[str] = Field(default_factory=list)
    allowed_groups: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    doc_type: str | list[str] | None = None
    product_id: str | list[str] | None = None
    product_name: str | list[str] | None = None
    product_model: str | list[str] | None = None
    error_code: str | list[str] | None = None
    region: str | list[str] | None = None
    language: str | list[str] | None = None
    effective_at: datetime | str | None = None
    active_only: bool = True
    source: str | list[str] | None = None
    classification: str | list[str] | None = None
    visibility: str | list[str] | None = None
    owner: str | list[str] | None = None
    document_id: str | list[str] | None = None
    policy_id: str | list[str] | None = None

    @field_validator(
        "allowed_user_ids", "allowed_groups", "required_permissions", mode="before"
    )
    @classmethod
    def normalize_string_lists(cls, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        values = value if isinstance(value, list) else [value]
        return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))

    def cache_key(self) -> str:
        """Stable key containing every filter that can affect retrieval."""

        import json

        return json.dumps(self.to_state(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_legacy(
        cls,
        value: "RetrievalFilters | dict[str, Any] | None",
        *,
        tenant_id: str | None = None,
        source: str | None = None,
    ) -> "RetrievalFilters":
        if isinstance(value, cls):
            data = value.to_state()
        else:
            data = dict(value or {})
        aliases = {
            "error_codes": "error_code",
            "product_models": "product_model",
            "doc_id": "document_id",
        }
        for old, new in aliases.items():
            if old in data and new not in data:
                data[new] = data.pop(old)
        if tenant_id and not data.get("tenant_id"):
            data["tenant_id"] = tenant_id
        if source and source not in {"all", "database", "structured_db"} and not data.get("source"):
            data["source"] = source
        if "source" in data:
            source_values = data["source"] if isinstance(data["source"], list) else [data["source"]]
            normalized_sources = [
                "structured_db" if str(item) == "database" else item
                for item in source_values
            ]
            data["source"] = normalized_sources if isinstance(data["source"], list) else normalized_sources[0]
        return cls.model_validate(data)


class RetrievalSubquery(ProtocolModel):
    """Created by planner/retry nodes and consumed by the production executor.

    Execution status is recorded in ``RetrievalResponse`` rather than mutating this
    immutable plan description.  It is safe to persist.
    """

    subquery_id: str
    query: str
    source: Literal[
        "manual",
        "policy",
        "faq",
        "ticket_history",
        "database",
        "metadata",
        "structured_db",
        "all",
    ] = "all"
    filters: dict[str, Any] = Field(default_factory=dict)
    required_evidence: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)
    retrieval_mode: Literal[
        "parallel", "serial", "dense", "sparse", "hybrid", "metadata", "database"
    ] = "parallel"
    parent_query_id: str | None = None
    reason: str = ""

    @classmethod
    def from_legacy(cls, value: dict[str, Any], index: int = 0) -> "RetrievalSubquery":
        mode = value.get("retrieval_mode") or value.get("execution", "parallel")
        if mode == "exact":
            mode = "metadata"
        return cls(
            subquery_id=str(value.get("subquery_id") or f"sq-{index + 1}"),
            query=str(value.get("query") or ""),
            source=value.get("source", "all"),
            filters=value.get("filters") or {},
            required_evidence=value.get("required_evidence")
            or ([value.get("purpose")] if value.get("purpose") else []),
            priority=value.get("priority", 50),
            retrieval_mode=mode,
            parent_query_id=value.get("parent_query_id"),
            reason=value.get("reason") or value.get("purpose", ""),
        )


class RetrievalPlan(ProtocolModel):
    """Created by Retrieval Planner and consumed by the production executor.

    Retry nodes may replace the plan.  It contains only serializable data and is
    safe for LangGraph checkpoints.
    """

    strategy: str = "hybrid"
    subqueries: list[RetrievalSubquery] = Field(default_factory=list)
    max_rounds: int = Field(default=2, ge=1)
    reason: str = ""
    original_requirements: list[str] = Field(default_factory=list)
    created_by: str = "retrieval_planner"
    version: str = "2.0"

    @classmethod
    def from_legacy(cls, state: dict[str, Any]) -> "RetrievalPlan":
        obj = state.get("retrieval_plan_v2")
        if isinstance(obj, cls):
            return obj
        if isinstance(obj, dict):
            return cls.model_validate(obj)
        rows = state.get("retrieval_plan") or []
        return cls(
            subqueries=[RetrievalSubquery.from_legacy(row, i) for i, row in enumerate(rows)],
            original_requirements=state.get("requirements") or [],
        )


class RetrievalError(ProtocolModel):
    """Created by a retrieval dependency and consumed by routing/observability.

    It is safe to persist and deliberately distinguishes dependency failures from
    a successful query that returned no rows or documents.
    """

    stage: str
    error_type: str
    message: str
    retryable: bool = False
    dependency: str | None = None
    subquery_id: str | None = None


class RetrievalContribution(ProtocolModel):
    """Evidence-level provenance created by retrievers and consumed by fusion/rerank."""

    retriever: str
    subquery_id: str | None = None
    rank: int = Field(ge=1)
    raw_score: float
    normalized_score: float = Field(ge=0.0, le=1.0)
    fusion_weight: float = Field(default=1.0, ge=0.0)
    score_semantics: ScoreSemantics
    matched_fields: list[str] = Field(default_factory=list)
    matched_entities: dict[str, list[str]] = Field(default_factory=dict)


class RetrievalPrincipal(ProtocolModel):
    """Created at request boundary and consumed by every retrieval path.

    The object is persistent.  ``authenticated=False`` principals cannot access
    production knowledge or structured data.
    """

    user_id: str
    tenant_id: str
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    region: str | None = None
    permissions: list[str] = Field(default_factory=list)
    authenticated: bool = False

    @model_validator(mode="after")
    def validate_identity(self):
        if self.authenticated and (not self.user_id or not self.tenant_id):
            raise ValueError("authenticated principal requires user_id and tenant_id")
        return self

    @property
    def can_retrieve(self) -> bool:
        """Whether protected tenant knowledge may be accessed."""
        return self.authenticated and bool(self.tenant_id)

    @property
    def can_access_public(self) -> bool:
        """Anonymous callers may access only explicitly public/global material."""
        return not self.authenticated

    @classmethod
    def anonymous(cls, *, region: str | None = None) -> "RetrievalPrincipal":
        return cls(
            user_id="anonymous",
            tenant_id="public",
            roles=[],
            groups=[],
            region=region,
            permissions=[],
            authenticated=False,
        )

    def audit_identity(self) -> dict[str, str]:
        """Return irreversible identity fields for trace/audit records."""
        from retrieval.security import hash_identifier
        return {
            "principal_hash": hash_identifier(self.user_id, namespace="principal"),
            "tenant_hash": hash_identifier(self.tenant_id, namespace="tenant"),
        }

    @property
    def is_privileged(self) -> bool:
        return bool({"admin", "knowledge_admin"} & set(self.roles))

    def cache_key(self) -> str:
        import json

        return json.dumps(
            {
                "user_id": self.user_id,
                "tenant_id": self.tenant_id,
                "roles": sorted(self.roles),
                "groups": sorted(self.groups),
                "region": self.region,
                "permissions": sorted(self.permissions),
                "authenticated": self.authenticated,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class RequirementCoverage(ProtocolModel):
    """Requirement-level coverage produced by Evidence Verifier.

    The verifier creates and updates this record; routing, answer gating and
    benchmark adapters consume it.  It is safe to persist in LangGraph state.
    """

    requirement_id: str
    requirement: str
    covered: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    evidence_type: str = "general"
    authority_sufficient: bool = False
    validity_sufficient: bool = False
    authority_required: bool = False
    critical: bool = True


class SourceAuthorityAssessment(ProtocolModel):
    """Requirement-aware authority assessment for one evidence item; persistent."""

    evidence_id: str
    requirement_id: str
    source_type: str
    source_authority: float = Field(ge=0.0, le=1.0)
    authority_reason: str = ""
    authority_required: bool = False
    authority_passed: bool = False


class EvidenceValidity(ProtocolModel):
    """Time, version, region and product validity for one evidence item.

    Evidence Verifier creates this immutable audit record.  Answer gating and
    conflict resolution consume it.  It is checkpoint-safe.
    """

    evidence_id: str
    is_active: bool = True
    effective_from: str | None = None
    effective_to: str | None = None
    version: str | None = None
    superseded_by: str | None = None
    region_compatible: bool = True
    region_information_complete: bool = False
    product_compatible: bool = True
    product_information_complete: bool = False
    product_version_compatible: bool = True
    temporal_information_complete: bool = False
    validity_sufficient: bool = True
    reasons: list[str] = Field(default_factory=list)


class DuplicateEvidenceGroup(ProtocolModel):
    """Duplicate cluster used to prevent duplicate evidence inflating coverage."""

    duplicate_id: str
    evidence_ids: list[str]
    representative_evidence_id: str
    duplicate_type: str
    similarity: float = Field(default=1.0, ge=0.0, le=1.0)


class EvidenceConflict(ProtocolModel):
    """Conflict record created by verifier and consumed by routing/answer gate."""

    conflict_id: str
    requirement_id: str
    evidence_ids: list[str]
    conflict_type: str
    preferred_evidence_id: str | None = None
    resolution_reason: str = ""
    unresolved: bool = False
    risk_level: Literal["low", "medium", "high"] = "medium"


class VerificationRound(ProtocolModel):
    """One Retrieve→Verify round, persisted for checkpoint recovery and audit."""

    round_id: int = Field(ge=1)
    trigger: str
    missing_requirements: list[str] = Field(default_factory=list)
    generated_subqueries: list[RetrievalSubquery] = Field(default_factory=list)
    new_evidence_ids: list[str] = Field(default_factory=list)
    coverage_before: float = Field(default=0.0, ge=0.0, le=1.0)
    coverage_after: float = Field(default=0.0, ge=0.0, le=1.0)
    coverage_change: float = Field(default=0.0, ge=-1.0, le=1.0)
    budget_before: dict[str, Any] = Field(default_factory=dict)
    budget_after: dict[str, Any] = Field(default_factory=dict)


class EvidenceAudit(ProtocolModel):
    """Complete persistent output of the production Evidence Verifier.

    Created by ``grade_evidence``/Evidence Verifier, consumed by graph routing,
    answer gating and benchmark scoring.  It contains no live dependencies.
    """

    requirement_coverages: list[RequirementCoverage] = Field(default_factory=list)
    source_authority: list[SourceAuthorityAssessment] = Field(default_factory=list)
    evidence_validity: list[EvidenceValidity] = Field(default_factory=list)
    duplicate_groups: list[DuplicateEvidenceGroup] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    accepted_evidence_ids: list[str] = Field(default_factory=list)
    excluded_evidence_ids: list[str] = Field(default_factory=list)
    coverage_score: float = Field(default=0.0, ge=0.0, le=1.0)
    all_critical_requirements_covered: bool = False
    unresolved_high_risk_conflicts: bool = False
    method: Literal["rules", "model", "hybrid", "human_gold"] = "rules"
    policy_version: str = "3.0"

    @property
    def missing_requirements(self) -> list[str]:
        return [item.requirement for item in self.requirement_coverages if not item.covered]

    @property
    def covered_requirements(self) -> list[str]:
        return [item.requirement for item in self.requirement_coverages if item.covered]


class VerificationDecision(ProtocolModel):
    """Created by Evidence/Answer Verifier and consumed by graph routing; persistent."""

    action: VerificationAction
    reason: str = ""
    missing_requirements: list[str] = Field(default_factory=list)
    next_subqueries: list[RetrievalSubquery] = Field(default_factory=list)
    filters_to_relax: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    handoff_reason: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    unresolved_conflict_ids: list[str] = Field(default_factory=list)
    partial_answer_allowed: bool = False
    decision_source: Literal["rule", "model", "hybrid", "human_gold"] = "rule"

    @model_validator(mode="after")
    def action_contract(self):
        if self.action == VerificationAction.CLARIFY and not self.clarification_question:
            raise ValueError("clarify action requires clarification_question")
        if self.action == VerificationAction.HANDOFF and not self.handoff_reason:
            raise ValueError("handoff action requires handoff_reason")
        return self

    @classmethod
    def from_legacy(cls, state: dict[str, Any]) -> "VerificationDecision":
        obj = state.get("verification_decision")
        if isinstance(obj, cls):
            return obj
        if isinstance(obj, dict):
            return cls.model_validate(obj)
        aliases = {
            "retrieve_more": "supplement",
            "regenerate": "rewrite",
            "retry": "rewrite",
            "rewrite_query": "rewrite",
            "search_again": "supplement",
            "supplement_retrieval": "supplement",
            "answer": "accept",
        }
        legacy_action = str(state.get("verification_action") or "").strip()
        raw = aliases.get(legacy_action, legacy_action or "handoff")
        handoff = state.get("handoff_reason")
        if raw == "handoff" and not handoff:
            handoff = "旧状态缺少可验证的 VerificationDecision，按安全策略转人工。"
        return cls(
            action=raw,
            reason=handoff or "legacy state",
            missing_requirements=state.get("missing_requirements") or [],
            handoff_reason=handoff if raw == "handoff" else None,
            confidence=float(state.get("verification_confidence", 0.0)),
        )


class RetrievalResponse(ProtocolModel):
    """Created by executor and consumed by verifier/answer/benchmark; persistent."""

    status: RetrievalStatus
    evidences: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[RetrievalError] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)
    budget_snapshot: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    executed_subqueries: list[str] = Field(default_factory=list)
    skipped_subqueries: list[str] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_contract(self):
        if self.status == RetrievalStatus.SUCCESS and not self.evidences:
            raise ValueError("success requires evidences")
        if self.status in {
            RetrievalStatus.TIMEOUT,
            RetrievalStatus.DEPENDENCY_ERROR,
            RetrievalStatus.INVALID_FILTER,
            RetrievalStatus.PERMISSION_DENIED,
        } and not self.errors:
            raise ValueError(f"{self.status} requires errors")
        return self
