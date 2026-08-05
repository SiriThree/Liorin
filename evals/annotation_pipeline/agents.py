from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .backends import JSONBackend
from .config import AgentConfig
from .io_utils import sha256_text, utc_now
from .models import AdjudicationResponse, AgentRecord, AnnotationEnvelope
from .prompts import build_adjudication_messages, build_annotation_messages

def validate_annotation_against_packet(annotation, packet: dict[str, Any]) -> None:
    allowed_locators = set()
    for row in packet.get("source_context", []) or []:
        for key in ["chunk_id", "record_id", "citation_id"]:
            if row.get(key):
                allowed_locators.add(str(row[key]))
    if annotation.layer == "retrieval":
        candidate_ids = {str(row.get("chunk_id")) for row in packet.get("source_context", []) if row.get("chunk_id")}
        qrel_ids = set(annotation.qrels)
        if qrel_ids != candidate_ids:
            missing = sorted(candidate_ids - qrel_ids)[:10]
            extra = sorted(qrel_ids - candidate_ids)[:10]
            raise ValueError(f"retrieval qrels must cover candidate pool exactly; missing={missing} extra={extra}")
    facts = getattr(annotation, "atomic_facts", []) or []
    requirements = getattr(annotation, "requirements", []) or []
    refs = []
    for fact in facts:
        refs.extend(fact.source_refs)
    for requirement in requirements:
        refs.extend(requirement.source_refs)
    invalid = []
    for ref in refs:
        locator = ref.chunk_id or ref.record_id
        if locator and allowed_locators and str(locator) not in allowed_locators:
            invalid.append(str(locator))
    if invalid:
        raise ValueError(f"annotation cites evidence outside source packet: {sorted(set(invalid))[:20]}")


class AnnotationAgent:
    def __init__(self, config: AgentConfig, backend: JSONBackend):
        self.config = config
        self.backend = backend

    def annotate(self, packet: dict[str, Any]) -> AgentRecord:
        system, user, schema = build_annotation_messages(packet, self.config.prompt_profile)
        last_error: Exception | None = None
        raw = ""
        parsed: dict[str, Any] | None = None
        validation_errors: list[str] = []
        attempt_count = 0
        backend_attempt_count = 0
        for attempt in range(3):
            attempt_count = attempt + 1
            counted_backend_attempt = False
            try:
                parsed, raw = self.backend.complete_json(system, user, schema)
                backend_attempt_count += max(1, self.backend.last_http_attempt_count)
                counted_backend_attempt = True
                annotation = AnnotationEnvelope.model_validate({"annotation": parsed}).annotation
                if annotation.sample_id != packet["sample_id"]:
                    raise ValueError(
                        f"returned sample_id={annotation.sample_id}, expected {packet['sample_id']}"
                    )
                if annotation.layer != packet["layer"]:
                    raise ValueError(
                        f"returned layer={annotation.layer}, expected {packet['layer']}"
                    )
                validate_annotation_against_packet(annotation, packet)
                break
            except (ValidationError, ValueError) as exc:
                if not counted_backend_attempt:
                    backend_attempt_count += max(1, self.backend.last_http_attempt_count)
                last_error = exc
                validation_errors.append(str(exc)[:2500])
                if attempt == 2:
                    raise ValueError(
                        f"{self.config.agent_id} produced invalid annotation after 3 attempts for "
                        f"{packet['sample_id']}: {exc}"
                    ) from exc
                user += (
                    "\n\n上一次输出未通过 Schema 校验。请修复后重新输出完整 JSON。"
                    f"\n校验错误：{str(exc)[:2500]}"
                )
        else:
            raise RuntimeError(last_error)

        request_hash = sha256_text(system + "\n" + user)
        return AgentRecord(
            sample_id=annotation.sample_id,
            layer=annotation.layer,
            annotator_id=self.config.agent_id,
            provider=self.config.provider,
            model=self.config.model,
            prompt_profile=self.config.prompt_profile,
            request_hash=request_hash,
            source_packet_hash=packet["packet_sha256"],
            annotation=annotation,
            raw_response_sha256=sha256_text(raw),
            attempt_count=max(attempt_count, backend_attempt_count),
            validation_errors=validation_errors,
            created_at=utc_now(),
        )


class AdjudicationAgent:
    def __init__(self, config: AgentConfig, backend: JSONBackend):
        self.config = config
        self.backend = backend

    def adjudicate(
        self,
        packet: dict[str, Any],
        annotation_a: dict[str, Any],
        annotation_b: dict[str, Any],
        conflicts: list[dict[str, Any]],
    ) -> tuple[AdjudicationResponse, str, str, int, list[str]]:
        if not conflicts:
            raise ValueError("adjudicator must not be called without conflicts")
        system, user, schema = build_adjudication_messages(
            packet, annotation_a, annotation_b, conflicts, self.config.prompt_profile
        )
        raw = ""
        response: AdjudicationResponse | None = None
        validation_errors: list[str] = []
        attempt_count = 0
        backend_attempt_count = 0
        expected_paths = {item["path"] for item in conflicts}
        for attempt in range(3):
            attempt_count = attempt + 1
            counted_backend_attempt = False
            try:
                parsed, raw = self.backend.complete_json(system, user, schema)
                backend_attempt_count += max(1, self.backend.last_http_attempt_count)
                counted_backend_attempt = True
                response = AdjudicationResponse.model_validate(parsed)
                if response.sample_id != packet["sample_id"]:
                    raise ValueError("adjudicator returned wrong sample_id")
                actual_paths = [item.path for item in response.resolutions]
                if set(actual_paths) != expected_paths or len(actual_paths) != len(expected_paths):
                    raise ValueError(
                        "resolutions must cover conflict paths exactly; "
                        f"expected={sorted(expected_paths)} actual={sorted(actual_paths)}"
                    )
                allowed_locators = {
                    str(row.get(key))
                    for row in packet.get("source_context", []) or []
                    for key in ["chunk_id", "record_id", "citation_id"]
                    if row.get(key)
                }
                invalid_refs = []
                for resolution in response.resolutions:
                    for ref in resolution.source_refs:
                        locator = ref.chunk_id or ref.record_id
                        if locator and allowed_locators and str(locator) not in allowed_locators:
                            invalid_refs.append(str(locator))
                if invalid_refs:
                    raise ValueError(f"adjudication cites evidence outside source packet: {sorted(set(invalid_refs))[:20]}")
                break
            except (ValidationError, ValueError) as exc:
                if not counted_backend_attempt:
                    backend_attempt_count += max(1, self.backend.last_http_attempt_count)
                validation_errors.append(str(exc)[:2500])
                if attempt == 2:
                    raise ValueError(
                        f"{self.config.agent_id} produced invalid adjudication after 3 attempts for "
                        f"{packet['sample_id']}: {exc}"
                    ) from exc
                user += (
                    "\n\n上一次仲裁输出未通过校验。请只修复 JSON，不得新增或遗漏 conflict path。"
                    f"\n校验错误：{str(exc)[:2500]}"
                )
        assert response is not None
        return response, sha256_text(system + "\n" + user), sha256_text(raw), max(attempt_count, backend_attempt_count), validation_errors
