"""Phase D3 independent Private Business Gold Draft annotation infrastructure.

This module reviews frozen D2 annotation packets. It never runs the Production
Agent and never adjudicates or mutates Gold drafts.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from evals.annotation_pipeline.backends import BackendError, JSONBackend, make_backend
from evals.annotation_pipeline.config import AgentConfig
from evals.benchmark.expansion.gold_draft import canonical_hash

PROMPT_VERSION = "private_gold_review_v1"
PROMPT_SCHEMA_VERSION = "private-business-dual-annotation-output-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionStatus(str, Enum):
    ACCEPT = "ACCEPT"
    ACCEPT_WITH_EDITS = "ACCEPT_WITH_EDITS"
    REJECT = "REJECT"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class DimensionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AmbiguityStatus(str, Enum):
    NONE = "NONE"
    PRESENT = "PRESENT"
    UNCERTAIN = "UNCERTAIN"


class EditOperation(str, Enum):
    REPLACE = "REPLACE"
    ADD = "ADD"
    REMOVE = "REMOVE"
    MAKE_OPTIONAL = "MAKE_OPTIONAL"
    MAKE_REQUIRED = "MAKE_REQUIRED"


class SuggestedEdit(StrictModel):
    target: str
    operation: EditOperation
    old_value: Any | None = None
    proposed_value: Any | None = None
    reason: str = Field(min_length=1, max_length=1000)


class GoldFactReview(StrictModel):
    fact_id: str
    source_supported: DimensionStatus
    criticality_correct: DimensionStatus
    value_correct: DimensionStatus
    comparison_mode_correct: DimensionStatus
    disposition: str = Field(pattern="^(KEEP|EDIT|REMOVE|UNCERTAIN)$")


class GoldEvidenceReview(StrictModel):
    evidence_id: str
    entity_correct: DimensionStatus
    field_correct: DimensionStatus
    required_correct: DimensionStatus
    supporting_relation_correct: DimensionStatus


class TaskContractReview(StrictModel):
    required_criteria_correct: DimensionStatus
    required_agents_correct: DimensionStatus
    required_tools_correct: DimensionStatus
    authorization_criteria_correct: DimensionStatus
    grounding_requirements_correct: DimensionStatus


class AnnotatorMetadata(StrictModel):
    annotator_id: str
    provider: str
    model: str
    packet_hash: str
    prompt_version: str
    structured_output_version: str


class PrivateGoldAnnotationDecision(StrictModel):
    schema_version: str = PROMPT_SCHEMA_VERSION
    candidate_id: str
    packet_hash: str
    annotator_id: str
    annotation_run_id: str
    overall_decision: DecisionStatus
    query_quality: DimensionStatus
    answerability: DimensionStatus
    response_type_correct: DimensionStatus
    gold_fact_correct: DimensionStatus
    gold_fact_complete: DimensionStatus
    gold_fact_minimal: DimensionStatus
    gold_evidence_correct: DimensionStatus
    task_contract_correct: DimensionStatus
    source_support: DimensionStatus
    ambiguity: AmbiguityStatus
    privacy_safe: DimensionStatus
    gold_fact_reviews: list[GoldFactReview]
    gold_evidence_reviews: list[GoldEvidenceReview]
    task_contract_review: TaskContractReview
    suggested_edits: list[SuggestedEdit] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: str | None = Field(default=None, pattern="^(HIGH|MEDIUM|LOW)$")
    annotator_metadata: AnnotatorMetadata

    @model_validator(mode="after")
    def validate_decision_semantics(self):
        if self.overall_decision is DecisionStatus.ACCEPT:
            required_pass = [
                self.query_quality, self.answerability, self.response_type_correct,
                self.gold_fact_correct, self.gold_fact_complete, self.gold_fact_minimal,
                self.gold_evidence_correct, self.task_contract_correct,
                self.source_support, self.privacy_safe,
            ]
            if any(value is not DimensionStatus.PASS for value in required_pass) or self.ambiguity is not AmbiguityStatus.NONE:
                raise ValueError("ACCEPT requires all critical review dimensions PASS and ambiguity NONE")
            if self.suggested_edits:
                raise ValueError("ACCEPT cannot contain suggested_edits")
        if self.overall_decision is DecisionStatus.ACCEPT_WITH_EDITS and not self.suggested_edits:
            raise ValueError("ACCEPT_WITH_EDITS requires structured suggested_edits")
        return self


class D3AnnotationConfig(StrictModel):
    annotator_a: AgentConfig
    annotator_b: AgentConfig
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_validation_attempts: int = Field(default=3, ge=1, le=5)
    allow_same_model_independent_runs: bool = False

    @model_validator(mode="after")
    def validate_independence(self):
        if self.annotator_a.role != "annotator" or self.annotator_b.role != "annotator":
            raise ValueError("both D3 annotators must have role=annotator")
        if self.annotator_a.agent_id == self.annotator_b.agent_id:
            raise ValueError("annotator A and B require distinct annotator_id values")
        if (
            self.annotator_a.independence_signature == self.annotator_b.independence_signature
            and not self.allow_same_model_independent_runs
        ):
            raise ValueError("same provider/base_url/model requires allow_same_model_independent_runs=true")
        return self

    @property
    def annotation_diversity(self) -> str:
        if self.annotator_a.independence_signature == self.annotator_b.independence_signature:
            return "SAME_MODEL_INDEPENDENT_RUNS"
        return "MODEL_DIVERSE"


def load_d3_config(path: str | Path) -> D3AnnotationConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return D3AnnotationConfig.model_validate(raw)


def _prompt_hash(system: str) -> str:
    return hashlib.sha256(system.encode("utf-8")).hexdigest()


def annotation_system_instruction() -> str:
    return """你是 Liorin Benchmark 的独立 Gold Annotation Reviewer。

你的任务不是回答用户问题，也不是评价 Liorin Agent 的表现。你只检查当前 Annotation Packet 中的 Benchmark Gold Draft。
你必须仅依据 Packet 中提供的 User Query、Minimal Source Snapshot、Production Capability、Gold Draft To Review 和 Review Requirements 做判断。

不得使用外部常识补充 Source 中不存在的信息；不得假设 Production Agent 会怎样回答；不得修改 Source Truth；不得根据另一个 Annotator 的判断调整结论；不得因为字段存在就默认它必须进入 Gold。

Gold 必须满足：SOURCE_SUPPORTED、COMPLETE、MINIMAL、EVIDENCE_ALIGNED、RESPONSE_BEHAVIOR_CORRECT、CONTRACT_CORRECT、UNAMBIGUOUS、PRIVACY_SAFE。
Gold Draft 只是待审核草案，不是参考答案。只输出结构化 AnnotationDecision；rationale 必须简短、source-grounded、dimension-specific，不要输出私人 chain-of-thought。"""


def _output_schema() -> dict[str, Any]:
    return PrivateGoldAnnotationDecision.model_json_schema()


def annotation_request_semantic_hash(system: str, user: str) -> str:
    """Hash request content with only annotator-runtime metadata normalized.

    A and B must review the same frozen packet/prompt. Their actual request hashes
    differ because annotator_id/model/run_id are intentionally distinct; this
    normalized hash proves the semantic packet input is otherwise identical.
    """
    payload = json.loads(user)
    req = payload.get("output_requirements") or {}
    if "annotator_id" in req:
        req["annotator_id"] = "<ANNOTATOR>"
    if "annotation_run_id" in req:
        req["annotation_run_id"] = "<RUN>"
    md = req.get("annotator_metadata") or {}
    for key in ("annotator_id", "provider", "model"):
        if key in md:
            md[key] = f"<{key.upper()}>"
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((system + "\n" + normalized).encode("utf-8")).hexdigest()


def build_annotation_request(packet: Mapping[str, Any], *, annotator_id: str, provider: str, model: str, run_id: str) -> tuple[str, str, dict[str, Any]]:
    system = annotation_system_instruction()
    payload = {
        "task": "review_private_business_gold_draft",
        "candidate_id": packet["candidate_id"],
        "packet_hash": packet["annotation_packet_hash"],
        "user_query": packet["candidate_query"],
        "runtime_query_preview": packet["runtime_query_preview"],
        # Source comes before Gold to reduce anchoring.
        "source_snapshot": packet["source_snapshot"],
        "production_capability": packet["production_capability_summary"],
        "gold_draft_to_review": packet["gold_draft"],
        "review_requirements": packet.get("review_requirements", []),
        "output_requirements": {
            "candidate_id": packet["candidate_id"],
            "packet_hash": packet["annotation_packet_hash"],
            "annotator_id": annotator_id,
            "annotation_run_id": run_id,
            "annotator_metadata": {
                "annotator_id": annotator_id,
                "provider": provider,
                "model": model,
                "packet_hash": packet["annotation_packet_hash"],
                "prompt_version": PROMPT_VERSION,
                "structured_output_version": PROMPT_SCHEMA_VERSION,
            },
            "review_every_gold_fact_id": [x["fact_id"] for x in packet["gold_draft"]["gold_facts_draft"]],
            "review_every_evidence_id": [x["evidence_id"] for x in packet["gold_draft"]["gold_evidence_draft"]],
            "do_not_answer_user_query": True,
        },
        "output_schema": _output_schema(),
    }
    return system, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), _output_schema()


def _validate_against_packet(decision: PrivateGoldAnnotationDecision, packet: Mapping[str, Any], config: AgentConfig, run_id: str) -> None:
    if decision.candidate_id != packet["candidate_id"]:
        raise ValueError("candidate_id mismatch")
    if decision.packet_hash != packet["annotation_packet_hash"]:
        raise ValueError("packet_hash mismatch")
    if decision.annotator_id != config.agent_id or decision.annotation_run_id != run_id:
        raise ValueError("annotator/run provenance mismatch")
    md = decision.annotator_metadata
    expected_meta = (config.agent_id, config.provider, config.model, packet["annotation_packet_hash"], PROMPT_VERSION, PROMPT_SCHEMA_VERSION)
    actual_meta = (md.annotator_id, md.provider, md.model, md.packet_hash, md.prompt_version, md.structured_output_version)
    if actual_meta != expected_meta:
        raise ValueError("annotator_metadata mismatch")
    expected_facts = {x["fact_id"] for x in packet["gold_draft"]["gold_facts_draft"]}
    actual_facts = {x.fact_id for x in decision.gold_fact_reviews}
    if actual_facts != expected_facts or len(actual_facts) != len(decision.gold_fact_reviews):
        raise ValueError("gold_fact_reviews must cover each draft fact exactly once")
    expected_evidence = {x["evidence_id"] for x in packet["gold_draft"]["gold_evidence_draft"]}
    actual_evidence = {x.evidence_id for x in decision.gold_evidence_reviews}
    if actual_evidence != expected_evidence or len(actual_evidence) != len(decision.gold_evidence_reviews):
        raise ValueError("gold_evidence_reviews must cover each draft evidence exactly once")


@dataclass(frozen=True)
class AnnotationCallResult:
    status: str
    decision: dict[str, Any] | None
    error: str | None
    retry_count: int
    raw_response_sha256: str | None
    request_sha256: str
    request_semantic_sha256: str
    request_started_at: str
    latency_ms: float
    provider_attempt_count: int


class PrivateGoldAnnotationAgent:
    def __init__(self, config: AgentConfig, backend: JSONBackend | None = None, *, max_validation_attempts: int = 3):
        self.config = config
        self.backend = backend or make_backend(config)
        self.max_validation_attempts = max_validation_attempts

    def annotate(self, packet: Mapping[str, Any], *, run_id: str) -> AnnotationCallResult:
        system, user, schema = build_annotation_request(
            packet, annotator_id=self.config.agent_id, provider=self.config.provider, model=self.config.model, run_id=run_id
        )
        request_sha = hashlib.sha256((system + "\n" + user).encode("utf-8")).hexdigest()
        request_semantic_sha = annotation_request_semantic_hash(system, user)
        request_started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        validation_errors: list[str] = []
        raw = ""
        backend_attempts = 0
        for attempt in range(self.max_validation_attempts):
            try:
                parsed, raw = self.backend.complete_json(system, user, schema)
                backend_attempts += max(1, self.backend.last_http_attempt_count)
                decision = PrivateGoldAnnotationDecision.model_validate(parsed)
                _validate_against_packet(decision, packet, self.config, run_id)
                return AnnotationCallResult(
                    status="VALID", decision=decision.model_dump(mode="json"), error=None,
                    retry_count=max(0, backend_attempts - 1),
                    raw_response_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(), request_sha256=request_sha,
                    request_semantic_sha256=request_semantic_sha, request_started_at=request_started_at, latency_ms=round((time.perf_counter()-started)*1000, 3),
                    provider_attempt_count=backend_attempts,
                )
            except BackendError as exc:
                # The backend already applied bounded infra retry. Do not semantic-retry valid decisions.
                return AnnotationCallResult(
                    status="ANNOTATOR_INFRA_ERROR", decision=None, error=str(exc)[:2000],
                    retry_count=max(0, self.backend.last_http_attempt_count - 1), raw_response_sha256=None, request_sha256=request_sha,
                    request_semantic_sha256=request_semantic_sha, request_started_at=request_started_at, latency_ms=round((time.perf_counter()-started)*1000, 3),
                    provider_attempt_count=max(1, self.backend.last_http_attempt_count),
                )
            except (ValidationError, ValueError) as exc:
                validation_errors.append(str(exc)[:2000])
                if attempt + 1 >= self.max_validation_attempts:
                    return AnnotationCallResult(
                        status="ANNOTATOR_INFRA_ERROR", decision=None,
                        error="structured output validation exhausted: " + " | ".join(validation_errors),
                        retry_count=attempt, raw_response_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else None,
                        request_sha256=request_sha, request_semantic_sha256=request_semantic_sha,
                        request_started_at=request_started_at, latency_ms=round((time.perf_counter()-started)*1000, 3),
                        provider_attempt_count=max(1, backend_attempts),
                    )
                user += "\n上一次 JSON 未通过结构校验。仅修复结构/字段，不要改变基于 Source 的判断。错误：" + str(exc)[:1200]
        raise AssertionError("unreachable")


def credential_status(config: AgentConfig) -> dict[str, Any]:
    if config.backend == "mock":
        return {"ready": False, "reason": "MOCK_BACKEND_FORBIDDEN_FOR_FORMAL_D3", "api_key_env": config.api_key_env, "configured": False}
    configured = bool(os.getenv(config.api_key_env, ""))
    provider = config.provider.strip().lower()
    model = config.model.strip().lower()
    host = (urlparse(config.base_url).hostname or "").lower()
    placeholder = (
        provider in {"provider-a", "provider-b", "provider", "example"}
        or model in {"model-a", "model-b", "model", "example-model"}
        or host.endswith(".example") or host.endswith(".invalid")
    )
    ready = configured and not placeholder
    if placeholder:
        reason = "PLACEHOLDER_RUNTIME_CONFIG"
    elif not configured:
        reason = "API_KEY_NOT_CONFIGURED"
    else:
        reason = "READY"
    return {
        "ready": ready,
        "reason": reason,
        "api_key_env": config.api_key_env,
        "configured": configured,
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "placeholder_config": placeholder,
    }


def new_run_id(prefix: str, batch_hash: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    entropy = hashlib.sha256(f"{prefix}:{batch_hash}:{now}".encode()).hexdigest()[:10]
    return f"{prefix}-{now}-{entropy}"


def prompt_metadata() -> dict[str, str]:
    text = annotation_system_instruction()
    return {"prompt_version": PROMPT_VERSION, "prompt_hash": _prompt_hash(text), "structured_output_version": PROMPT_SCHEMA_VERSION}
