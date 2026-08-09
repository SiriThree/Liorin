"""Phase G0.4 Knowledge Gold Draft construction.

Dataset-construction only.  This module never invokes Production, retrieval,
LLMs, judges, or annotators.  It converts the frozen G0.3 SOURCE_VALIDATED
candidate surface into source-derived Gold Drafts while preserving G0.1/G0.2/
G0.3 lineage.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from enum import StrEnum
import hashlib
import re
from typing import Any, Mapping

from eval_platform.contracts import ComparisonMode, SuccessCriterion
from .gold_draft import canonical_hash

KNOWLEDGE_GOLD_DRAFT_VERSION = "knowledge-gold-draft-g0.4-v1"
KNOWLEDGE_SOURCE_SNAPSHOT_VERSION = "knowledge-source-snapshot-g0.4-v1"
KNOWLEDGE_PACKET_VERSION = "knowledge-annotation-packet-g0.4-v1"


class KnowledgeGoldStatus(StrEnum):
    READY_FOR_DUAL_ANNOTATION = "READY_FOR_DUAL_ANNOTATION"
    NEEDS_MANUAL_PRECHECK = "NEEDS_MANUAL_PRECHECK"
    REJECTED_BEFORE_ANNOTATION = "REJECTED_BEFORE_ANNOTATION"


class GoldFactRole(StrEnum):
    ANSWER_REQUIRED = "ANSWER_REQUIRED"
    REASONING_REQUIRED = "REASONING_REQUIRED"
    SUPPORTING_ONLY = "SUPPORTING_ONLY"
    OPTIONAL_OUTPUT = "OPTIONAL_OUTPUT"


class PolicyQualification(StrEnum):
    ABSOLUTE = "ABSOLUTE"
    CONDITIONAL = "CONDITIONAL"
    QUALIFIED = "QUALIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class KnowledgeGoldFact:
    gold_fact_id: str
    source_fact_ids: tuple[str, ...]
    description: str
    normalized_value_or_semantics: Any
    fact_role: str
    critical: bool
    comparison_mode: str
    evaluator_comparison_mode: str
    evidence_ids: tuple[str, ...]
    source_supported: bool
    source_fact_type: str
    value_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        x = asdict(self)
        x["source_fact_ids"] = list(self.source_fact_ids)
        x["evidence_ids"] = list(self.evidence_ids)
        x["value_metadata"] = dict(self.value_metadata)
        return x


@dataclass(frozen=True)
class KnowledgeGoldEvidence:
    evidence_id: str
    source_type: str
    required: bool
    document_id: str
    section_id: str
    heading: str
    parent_heading: str | None
    source_fact_ids: tuple[str, ...]
    authority: str
    stable: bool = True

    def to_state(self) -> dict[str, Any]:
        x = asdict(self)
        x["source_fact_ids"] = list(self.source_fact_ids)
        return x


@dataclass(frozen=True)
class DerivedFactDraft:
    derived_fact_id: str
    input_fact_ids: tuple[str, ...]
    reasoning_type: str
    operator_or_relation: str
    normalized_result: Any
    answer_required: bool
    critical: bool

    def to_state(self) -> dict[str, Any]:
        x = asdict(self)
        x["input_fact_ids"] = list(self.input_fact_ids)
        return x


def stable_gold_fact_id(candidate_id: str, source_fact_id: str, role: str) -> str:
    token = hashlib.sha256(f"{candidate_id}|{source_fact_id}|{role}".encode()).hexdigest()[:20]
    return f"kgf:{token}"


def stable_derived_fact_id(candidate_id: str, input_fact_ids: list[str], relation: str) -> str:
    token = canonical_hash([candidate_id, sorted(input_fact_ids), relation])[:20]
    return f"kgd:{token}"


def evidence_id(document_id: str, section_id: str) -> str:
    return f"doc:{document_id}#{section_id}"


def normalize_semantics(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("；", "，")
    return text


_NUM_UNIT = re.compile(
    r"(?<![A-Za-z0-9])(-?\d+(?:\.\d+)?)\s*(kg|g|mg|mm|cm|m|km|V|W|Hz|A|mA|mAh|Ah|°C|℃|°F|%|英尺|英寸|米|厘米|毫米|公斤|千克|克|年|个月|天|小时|分钟|秒)(?![A-Za-z])",
    re.I,
)


def numeric_value(text: str) -> dict[str, Any] | None:
    hits = _NUM_UNIT.findall(text or "")
    if len(hits) != 1:
        return None
    raw, unit = hits[0]
    try:
        value: int | float = int(raw) if re.fullmatch(r"-?\d+", raw) else float(raw)
    except ValueError:
        return None
    return {"value": value, "unit": unit, "raw": f"{raw}{unit}", "tolerance": None}


def comparison_for(*, task_type: str, answer_scope: str, fact_type: str, fact_text: str, relationship: str) -> tuple[str, str, Any, dict[str, Any]]:
    """Return construction mode, evaluator mode, normalized value, metadata."""
    text = normalize_semantics(fact_text)
    n = numeric_value(text)
    if task_type == "PRODUCT_SPEC" and n is not None:
        return "NUMERIC", ComparisonMode.NUMERIC.value, n, {"unit": n["unit"], "tolerance": None}
    if answer_scope == "PROCEDURE_SUBSET" or relationship == "PROCEDURE":
        return "ORDERED_SEQUENCE", ComparisonMode.SEMANTIC.value, text, {"order_semantics": "SOURCE_ORDER_WHERE_EXPLICIT"}
    if task_type == "MULTI_FACT_SYNTHESIS" and answer_scope == "BOUNDED_FACT_SET":
        return "UNORDERED_SET", ComparisonMode.SEMANTIC.value, text, {"set_member": True}
    if task_type in {"COMPATIBILITY", "LIMITATION"}:
        return "CONDITIONAL", ComparisonMode.SEMANTIC.value, text, {"preserve_condition_and_exception": True}
    if task_type == "POLICY_OR_WARRANTY":
        return "CONDITIONAL", ComparisonMode.SEMANTIC.value, text, {"preserve_policy_qualification": True}
    if fact_type == "PRODUCT_SPEC" and ("=" in text or len(text) <= 40):
        return "EXACT_VALUE", ComparisonMode.NORMALIZED_EXACT.value, text, {}
    return "SEMANTIC", ComparisonMode.SEMANTIC.value, text, {}


def policy_qualification(text: str) -> str:
    t = str(text or "").lower()
    qualified = ("通常", "一般", "可能", "may", "generally", "usually", "原则上", "视", "具体以")
    conditional = ("如果", "若", "当", "凡", "只有", "除非", "在", "自购买", "需要", "需提供", "不一致时")
    if any(x in t for x in qualified):
        return PolicyQualification.QUALIFIED.value
    if any(x in t for x in conditional):
        return PolicyQualification.CONDITIONAL.value
    return PolicyQualification.ABSOLUTE.value


def looks_heading_only(text: str, section_heading: str = "") -> bool:
    t = normalize_semantics(text).strip("：:。；;，,")
    h = normalize_semantics(section_heading).strip("：:。；;，,")
    if not t:
        return True
    if t.startswith("[CDATA[#") or t.startswith("#"):
        return True
    # Numbered labels such as "1 首次使用驱动程序" or "③化油器放油螺塞"
    # are structural only when they contain no sentence-level predicate/punctuation.
    if re.fullmatch(r"[①②③④⑤⑥⑦⑧⑨⑩]?\s*\d+[\.、]?\s*[^，。；：:!?！？]{1,40}", t):
        if not re.search(r"(不|可|应|需|为|是|表示|包含|包括|限制|适用|支持|使用|保修|优先|存放|显示|启动|按|将|请|必须|禁止|能够|可以|需要|继续|享受|退款|连接|安装|调整|检查|设置|选择|关闭|打开|返回)", t):
            return True
    # A section heading can itself be a valid proposition.  Only demote exact
    # heading matches when they look like labels rather than claims.
    if h and t == h and len(t) <= 36 and not re.search(r"[，。；!?！？=]", t):
        if not re.search(r"(不|可|应|需|为|是|表示|包含|包括|限制|适用|支持|使用|保修|优先|存放|显示|启动|按|将|请|必须|禁止|能够|可以|需要|继续|享受|退款|连接|安装|调整|检查|设置|选择|关闭|打开|返回)", t):
            return True
    return False

def looks_intro_only(text: str) -> bool:
    t = normalize_semantics(text)
    return bool(re.search(r"(请按照以下步骤|如下步骤|检查以下内容|需要同时|首次使用驱动程序$|连接其他 HID 设备$|卸载 WIDCOMM 蓝牙驱动程序$)", t))


def unresolved_deictic(text: str) -> bool:
    t = normalize_semantics(text)
    return bool(re.search(r"(^|[，。；：\s])(此功能|该功能|上述|这项说明|这种情况下|该操作)([，。；：\s]|$)", t))


def task_success_contract() -> dict[str, Any]:
    return {
        "required_criteria": [
            SuccessCriterion.RESPONSE_TYPE_CORRECT.value,
            SuccessCriterion.CRITICAL_FACTS_CORRECT.value,
            SuccessCriterion.CRITICAL_FACTS_GROUNDED.value,
            SuccessCriterion.NO_CRITICAL_HALLUCINATION.value,
        ],
        "conditional_criteria": [],
        "success_rule": "ALL_REQUIRED_CRITERIA_MUST_PASS",
    }


def gold_signature(draft: Mapping[str, Any]) -> str:
    return canonical_hash({
        "task_type": draft["primary_task_type"],
        "answer_required_fact_set": sorted(x["normalized_value_or_semantics"] if isinstance(x["normalized_value_or_semantics"], str) else canonical_hash(x["normalized_value_or_semantics"]) for x in draft["gold_facts"] if x["fact_role"] == GoldFactRole.ANSWER_REQUIRED.value),
        "reasoning_required_fact_set": sorted(x["normalized_value_or_semantics"] if isinstance(x["normalized_value_or_semantics"], str) else canonical_hash(x["normalized_value_or_semantics"]) for x in draft["gold_facts"] if x["fact_role"] == GoldFactRole.REASONING_REQUIRED.value),
        "required_evidence_set": sorted(x["evidence_id"] for x in draft["gold_evidence"] if x["required"]),
        "comparison": draft["comparison_contract"],
        "answer_scope": draft["answer_scope"],
        "derived": draft.get("derived_facts", []),
    })
