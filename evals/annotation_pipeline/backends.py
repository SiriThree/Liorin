from __future__ import annotations

import json
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .config import AgentConfig


class BackendError(RuntimeError):
    pass


class JSONBackend(ABC):
    def __init__(self, config: AgentConfig):
        self.config = config
        self.last_http_attempt_count = 0

    @abstractmethod
    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> tuple[dict[str, Any], str]:
        raise NotImplementedError


class OpenAICompatibleBackend(JSONBackend):
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self.client = httpx.Client(timeout=config.timeout_seconds)

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> tuple[dict[str, Any], str]:
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self.config.seed is not None:
            payload["seed"] = self.config.seed
        headers = {
            "Authorization": f"Bearer {self.config.api_key()}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(5):
            self.last_http_attempt_count = attempt + 1
            try:
                response = self.client.post(endpoint, headers=headers, json=payload)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise BackendError(f"transient HTTP {response.status_code}: {response.text[:500]}")
                response.raise_for_status()
                body = response.json()
                raw = body["choices"][0]["message"]["content"]
                return parse_json_object(raw), raw
            except (httpx.HTTPError, KeyError, ValueError, BackendError) as exc:
                last_error = exc
                if attempt == 4:
                    break
                time.sleep(min(16.0, 1.5 * (2**attempt)))
        raise BackendError(f"{self.config.agent_id} failed after retries: {last_error}")


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response must be a JSON object")
    return value


class MockBackend(JSONBackend):
    """Deterministic flow-test backend. It is not a semantic annotator."""

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> tuple[dict[str, Any], str]:
        self.last_http_attempt_count = 1
        payload = json.loads(user)
        if payload.get("task") == "adjudicate_disagreements_only":
            conflicts = payload["conflicts"]
            output = {
                "sample_id": payload["sample"]["sample_id"],
                "resolutions": [
                    {
                        "path": item["path"],
                        "value": item["value_a"],
                        "reason": "mock flow test selects annotator A value",
                        "source_refs": [],
                    }
                    for item in conflicts
                ],
                "quality_status": "valid",
                "quality_issues": [],
                "confidence": 0.5,
                "rationale": "mock adjudication for pipeline validation only",
            }
            raw = json.dumps(output, ensure_ascii=False)
            return output, raw
        sample = payload["sample"]
        output = mock_annotation(sample, variant=self.config.prompt_profile)
        raw = json.dumps(output, ensure_ascii=False)
        return output, raw


def mock_annotation(packet: dict[str, Any], variant: str) -> dict[str, Any]:
    layer = packet["layer"]
    sid = packet["sample_id"]
    source_context = packet.get("source_context", [])
    question = packet.get("input", {}).get("question") or packet.get("input", {}).get("query") or ""
    base = {
        "sample_id": sid,
        "layer": layer,
        "quality_status": "valid",
        "confidence": 0.9,
        "quality_issues": [],
        "rationale": "mock output validates orchestration, not semantic correctness",
    }
    if layer == "query_understanding":
        base.update({
            "entities": {"product_name": None, "product_id": None, "product_model": None, "product_alias": None, "accessory_model": None, "error_code": None},
            "task_type": "product_support",
            "requirements": [{"concept_id": "mock:requirement", "description": str(question), "source_refs": []}],
            "needs_clarification": not bool(question),
            "clarification_slots": ["question"] if not question else [],
            "rewritten_question": str(question),
            "must_not_invent": ["completed_business_action"],
        })
    elif layer == "routing":
        required = [source_context[0].get("source_type", "manual")] if source_context else ["manual"]
        if variant == "counterexample_first" and sid.endswith("1"):
            required = ["policy"]
        base.update({"required_sources": required, "conditional_sources": [], "optional_sources": [], "forbidden_sources": [s for s in ["manual","policy","faq","ticket_history","database"] if s not in required], "min_queries": 1, "parallelizable": False})
    elif layer == "retrieval":
        qrels = {str(row.get("chunk_id")): (3 if i == 0 else 0) for i, row in enumerate(source_context) if row.get("chunk_id")}
        if variant == "counterexample_first" and len(qrels) > 1 and sid.endswith("1"):
            keys = list(qrels); qrels[keys[0]] = 2; qrels[keys[1]] = 3
        base.update({"qrels": qrels or {"NO_CANDIDATE": 0}, "atomic_facts": [], "missing_relevant_evidence": False, "omitted_relevant_descriptions": []})
    elif layer == "answer_generation":
        refs = []
        if source_context:
            row = source_context[0]
            refs = [{"source_type": row.get("source_type", "manual"), "chunk_id": row.get("chunk_id") or row.get("citation_id"), "source_file": row.get("source_file"), "heading": row.get("heading"), "record_id": row.get("record_id")}]
        base.update({"expected_response_type": "answer", "atomic_facts": [{"fact_text": "mock fact", "source_refs": refs, "necessity": "required", "support_label": "fully_supported", "exact_numbers": [], "conditions": []}] if refs else [], "forbidden_claims": ["completed_business_action"], "citation_required": bool(refs)})
    elif layer == "agent_behavior":
        base.update({"expected_action": "clarify", "allowed_actions": ["clarify"], "reason_codes": ["mock_reason"], "clarification_slots": ["product_name_or_model"], "supplemental_sources": [], "max_retrieval_rounds": 0, "must_not_claim_completed_action": False})
    elif layer == "end_to_end":
        required = sorted({row.get("source_type") for row in source_context if row.get("source_type")})[:2]
        base.update({"expected_response_type": "answer", "decision_code": "mock_decision", "required_sources": required, "conditional_sources": [], "required_actions": [], "allowed_actions": ["answer"], "atomic_facts": [], "forbidden_claims": ["completed_business_action"], "max_retrieval_rounds": 2})
    return base


def make_backend(config: AgentConfig) -> JSONBackend:
    if config.backend == "mock":
        return MockBackend(config)
    return OpenAICompatibleBackend(config)
