from __future__ import annotations

import random
import re
from typing import Any

from .models import HumanReviewRecord

HIGH_RISK_PATTERNS = {
    "numeric_or_date": re.compile(r"\d|日期|时间|天|小时|分钟|月|年|金额|价格|费用|伏|毫安", re.I),
    "model_or_error_code": re.compile(r"型号|错误码|故障码|\b[A-Z]{1,8}[-_]?[A-Z0-9]{2,}\b|E\d{2,}", re.I),
    "policy_high_risk": re.compile(r"退款|退货|取消|撤销|赔付|维修|质保|保修|换货|人工审批", re.I),
    "identity_or_privacy": re.compile(r"身份|邮箱|客户|隐私|权限|验证|个人信息", re.I),
    "safety": re.compile(r"危险|警告|安全|受伤|死亡|触电|火灾|立即停止|就医", re.I),
    "conflict_or_limitation": re.compile(r"冲突|版本|证据不足|无法确认|未知|缺少|超时|失败", re.I),
}


def sample_text(sample: dict[str, Any]) -> str:
    """Only inspect user-visible input/state text; metadata suffixes must not create false risk tags."""
    input_data = sample.get("input", {})
    parts: list[str] = []
    if isinstance(input_data, dict):
        for key in ["question", "query"]:
            if input_data.get(key):
                parts.append(str(input_data[key]))
        for message in input_data.get("conversation", []) or []:
            if isinstance(message, dict) and message.get("content"):
                parts.append(str(message["content"]))
        state = input_data.get("state_fixture") or {}
        if isinstance(state, dict):
            for key in ["original_question", "rewritten_question", "clarification_question", "handoff_reason"]:
                if state.get(key):
                    parts.append(str(state[key]))
            parts.extend(str(x) for x in state.get("tool_errors", []) or [])
    return " ".join(parts)


def risk_tags(sample: dict[str, Any], adjudicated: dict[str, Any]) -> list[str]:
    text = sample_text(sample)
    tags = [name for name, pattern in HIGH_RISK_PATTERNS.items() if pattern.search(text)]
    final = adjudicated.get("final_annotation", {})
    if final.get("quality_status") != "valid":
        tags.append("non_valid_quality_status")
    if float(final.get("confidence", 1.0)) < 0.75:
        tags.append("low_confidence")
    fact_blob = str(final.get("atomic_facts", []))
    if re.search(r"\d|exact_numbers|金额|日期|时间|电压|毫安", fact_blob, re.I):
        tags.append("annotated_numeric_fact")
    if sample.get("layer") in {"agent_behavior", "end_to_end"}:
        if any(token in str(final).lower() for token in ["handoff", "refund", "cancel", "warranty", "identity", "unsafe", "timeout"]):
            tags.append("agentic_high_risk")
    return sorted(set(tags))


def build_review_queue(
    samples: list[dict[str, Any]],
    packets: dict[str, dict[str, Any]],
    adjudicated_records: list[dict[str, Any]],
    *,
    random_review_rate: float,
    seed: int,
) -> list[dict[str, Any]]:
    sample_by_id = {sample["id"]: sample for sample in samples}
    adjudicated_by_id = {row["sample_id"]: row for row in adjudicated_records}
    reasons_by_id: dict[str, set[str]] = {}

    consensus_ids = []
    for sample_id, record in adjudicated_by_id.items():
        reasons = reasons_by_id.setdefault(sample_id, set())
        if record.get("had_disagreement"):
            reasons.add("all_agent_disagreements")
        else:
            consensus_ids.append(sample_id)
        for tag in risk_tags(sample_by_id[sample_id], record):
            reasons.add(tag)

    rng = random.Random(seed)
    random_count = int(round(len(consensus_ids) * random_review_rate))
    for sample_id in rng.sample(sorted(consensus_ids), min(random_count, len(consensus_ids))):
        reasons_by_id.setdefault(sample_id, set()).add("random_consensus_sample")

    queue = []
    for sample_id in sorted(reasons_by_id):
        reasons = sorted(reasons_by_id[sample_id])
        if not reasons:
            continue
        sample = sample_by_id[sample_id]
        record = adjudicated_by_id[sample_id]
        queue.append(
            HumanReviewRecord(
                sample_id=sample_id,
                layer=sample["layer"],
                mandatory_reasons=reasons,
                source_packet=packets[sample_id],
                adjudicated_record=record,
            ).model_dump(mode="json")
        )
    return queue


def validate_completed_reviews(queue: list[dict[str, Any]]) -> list[str]:
    errors = []
    for row in queue:
        review = row.get("human_review") or {}
        status = review.get("status")
        if status not in {"approved", "modified", "rejected"}:
            errors.append(f"{row['sample_id']}: review status must be approved/modified/rejected")
        if not review.get("reviewer_id"):
            errors.append(f"{row['sample_id']}: reviewer_id is required")
        if status == "modified" and not review.get("final_annotation"):
            errors.append(f"{row['sample_id']}: modified review requires final_annotation")
        if status == "rejected" and not review.get("notes"):
            errors.append(f"{row['sample_id']}: rejected review requires notes")
    return errors
