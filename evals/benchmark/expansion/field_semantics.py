"""Deterministic field semantics registry for D2 Private Business Gold preparation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from eval_platform.contracts import ComparisonMode, FactValueType


# Classification intentionally separates "Production exposed" from
# "normal customer-facing benchmark-worthy".
_FIELD_SPECS: dict[tuple[str, str], dict[str, Any]] = {
    ("order", "status"): dict(classification="USER_FACING", value_type=FactValueType.ENUM.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="当前状态", gold_description="订单当前状态", annotation_risk="LOW"),
    ("order", "order_date"): dict(classification="USER_FACING", value_type=FactValueType.DATE.value, comparison_mode=ComparisonMode.DATE.value, natural_language_label="下单日期", gold_description="订单下单日期", annotation_risk="LOW"),
    ("order", "product_id"): dict(classification="USER_FACING", value_type=FactValueType.STRING.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="产品型号", gold_description="订单商品的产品型号", annotation_risk="MEDIUM"),
    ("order", "product_name"): dict(classification="USER_FACING", value_type=FactValueType.STRING.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="产品名称", gold_description="订单商品的产品名称", annotation_risk="LOW"),
    ("order", "quantity"): dict(classification="USER_FACING", value_type=FactValueType.INTEGER.value, comparison_mode=ComparisonMode.NUMERIC.value, natural_language_label="购买数量", gold_description="订单中该商品的购买数量", annotation_risk="LOW"),
    ("order", "price_per_unit"): dict(classification="USER_FACING", value_type=FactValueType.FLOAT.value, comparison_mode=ComparisonMode.NUMERIC.value, natural_language_label="商品单价", gold_description="订单中该商品的单价", annotation_risk="MEDIUM"),
    ("order", "total_amount"): dict(classification="USER_FACING", value_type=FactValueType.FLOAT.value, comparison_mode=ComparisonMode.NUMERIC.value, natural_language_label="订单总金额", gold_description="订单总金额", annotation_risk="MEDIUM"),
    ("order", "channel"): dict(classification="USER_FACING", value_type=FactValueType.ENUM.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="下单渠道", gold_description="订单下单渠道", annotation_risk="MEDIUM"),

    ("ticket", "status"): dict(classification="USER_FACING", value_type=FactValueType.ENUM.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="工单状态", gold_description="售后工单当前状态", annotation_risk="LOW"),
    # Priority and assigned team are deliberately not auto-approved merely because
    # the Production tool exposes them. They require business-facing policy review.
    ("ticket", "priority"): dict(classification="BUSINESS_VALID_BUT_REVIEW", value_type=FactValueType.ENUM.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="工单优先级", gold_description="售后工单优先级", annotation_risk="HIGH"),
    ("ticket", "issue_type"): dict(classification="USER_FACING", value_type=FactValueType.ENUM.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="问题类型", gold_description="工单记录的问题类型", annotation_risk="MEDIUM"),
    ("ticket", "product_id"): dict(classification="USER_FACING", value_type=FactValueType.STRING.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="关联产品型号", gold_description="工单关联的产品型号", annotation_risk="LOW"),
    ("ticket", "order_id"): dict(classification="USER_FACING", value_type=FactValueType.STRING.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="关联订单参考号", gold_description="工单关联的订单", annotation_risk="MEDIUM", fixture_identifier=True),
    ("ticket", "assigned_team"): dict(classification="BUSINESS_VALID_BUT_REVIEW", value_type=FactValueType.ENUM.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="处理团队", gold_description="工单当前处理团队", annotation_risk="HIGH"),
    ("ticket", "summary"): dict(classification="USER_FACING", value_type=FactValueType.STRING.value, comparison_mode=ComparisonMode.SEMANTIC.value, natural_language_label="问题摘要", gold_description="工单记录的问题摘要", annotation_risk="HIGH", judge_required=True),
    ("ticket", "created_at"): dict(classification="USER_FACING", value_type=FactValueType.DATE.value, comparison_mode=ComparisonMode.DATE.value, natural_language_label="创建日期", gold_description="工单创建日期", annotation_risk="LOW"),

    ("warranty", "status"): dict(classification="USER_FACING", value_type=FactValueType.ENUM.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="质保案例状态", gold_description="质保案例当前处理状态", annotation_risk="LOW"),
    ("warranty", "coverage_status"): dict(classification="USER_FACING", value_type=FactValueType.ENUM.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="保修覆盖状态", gold_description="质保案例当前是否在保修范围内", annotation_risk="LOW"),
    ("warranty", "coverage_type"): dict(classification="USER_FACING", value_type=FactValueType.ENUM.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="保修类型", gold_description="质保案例的保修覆盖类型", annotation_risk="MEDIUM"),
    ("warranty", "expires_at"): dict(classification="USER_FACING", value_type=FactValueType.DATE.value, comparison_mode=ComparisonMode.DATE.value, natural_language_label="保修到期日期", gold_description="质保案例到期日期", annotation_risk="LOW"),
    ("warranty", "product_id"): dict(classification="USER_FACING", value_type=FactValueType.STRING.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="关联产品型号", gold_description="质保案例关联的产品型号", annotation_risk="LOW"),
    ("warranty", "order_id"): dict(classification="USER_FACING", value_type=FactValueType.STRING.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="关联订单参考号", gold_description="质保案例关联的订单", annotation_risk="MEDIUM", fixture_identifier=True),
    ("warranty", "ticket_id"): dict(classification="USER_FACING", value_type=FactValueType.STRING.value, comparison_mode=ComparisonMode.NORMALIZED_EXACT.value, natural_language_label="关联工单参考号", gold_description="质保案例关联的工单", annotation_risk="MEDIUM", fixture_identifier=True),
}


def build_field_semantics_registry(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    covered = sorted({(str(c["record_type"]), str(f)) for c in candidates for f in c["required_structured_fields"]})
    missing = [f"{r}.{f}" for r, f in covered if (r, f) not in _FIELD_SPECS]
    if missing:
        raise ValueError(f"D2 field semantics missing for covered fields: {missing}")
    fields = []
    for record_type, field_path in covered:
        spec = dict(_FIELD_SPECS[(record_type, field_path)])
        spec.update({
            "record_type": record_type,
            "field_path": field_path,
            "production_exposed": True,
            "user_facing": spec["classification"] == "USER_FACING",
            "sensitive": spec["classification"] == "SENSITIVE",
            "internal": spec["classification"] == "INTERNAL_ONLY",
            "recommended_comparison_mode": spec["comparison_mode"],
        })
        fields.append(spec)
    return {
        "registry_version": "private-business-field-semantics-v1",
        "covered_field_count": len(fields),
        "classification_counts": {
            key: sum(1 for x in fields if x["classification"] == key)
            for key in ("USER_FACING", "BUSINESS_VALID_BUT_REVIEW", "INTERNAL_ONLY", "SENSITIVE", "UNSUPPORTED")
        },
        "semantic_judge_required_count": sum(1 for x in fields if x.get("judge_required")),
        "fields": fields,
    }


def registry_index(payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(x["record_type"], x["field_path"]): x for x in payload["fields"]}
