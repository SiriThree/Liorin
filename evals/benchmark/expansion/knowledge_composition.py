"""Deterministic multi-fact and strongly-related multi-section proposal construction for G0.2."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any


def _sha_obj(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def _document_product_name(document_id: str) -> str:
    raw = document_id.split("_", 1)[1] if "_" in document_id else document_id
    for suffix in ("用户手册", "使用手册", "说明书", "手册", "指南"):
        raw = raw.replace(suffix, "")
    return raw.strip()


_GENERIC_HEADINGS = {
    "注意", "警告", "说明", "操作", "操作方法", "使用", "使用方法", "设置", "功能", "其他", "其它",
    "故障", "故障排除", "故障处理", "技术规格", "规格", "参数", "特性", "安全", "维护", "保养",
    "用户档案", "部件说明", "重要", "提示", "控制台", "包装盒内含物品", "使用说明书", "说明书",
    "产品描述", "基本装配提示", "装配前", "开始", "概述", "简介", "问题", "服务", "支持", "常见问题",
}
_GENERIC_NORMALIZED = {_normalize(x) for x in _GENERIC_HEADINGS}
_META_FACT_PATTERNS = (
    "参阅第", "请参阅", "详见", "如需更多信息", "更多信息请", "如下所示", "目录", "见第",
)


def _clean_heading_anchor(heading: str, document_id: str) -> str:
    text = re.sub(r"^\s*\d+(?:\.\d+)*[\.、\s-]*", "", heading or "")
    text = _normalize(text)
    product = _normalize(_document_product_name(document_id))
    if product and len(product) >= 2:
        text = text.replace(product, "")
    if not text or text in _GENERIC_NORMALIZED:
        return ""
    return text


def _fact_composition_safe(text: str) -> bool:
    text = (text or "").strip()
    if len(text) < 6 or len(text) > 180:
        return False
    if any(p in text for p in _META_FACT_PATTERNS):
        return False
    if re.search(r"第\s*\d+\s*页", text):
        return False
    if any(x in text for x in ("此功能", "该功能", "本功能")):
        return False
    # Reject table-of-contents / diagram / dense enumeration blobs. They may be valid
    # local context, but are not high-quality required answer facts for composition.
    if len(re.findall(r"[A-Z]-\d+", text)) >= 2:
        return False
    if len(re.findall(r"\.\s*\d{1,3}\b", text)) >= 2:
        return False
    if text.count("、") >= 7 or text.count("；") >= 7:
        return False
    if len(text.split()) >= 8:
        return False
    if len(re.findall(r"(?:^|\s)\d+(?:\.\d+)?(?:\s|$)", text)) >= 3:
        return False
    symbol_count = sum(text.count(x) for x in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "○", "⊛"))
    if symbol_count >= 5:
        return False
    return True


def _fact_pair_distinct(a: str, b: str) -> bool:
    aa, bb = _normalize(a), _normalize(b)
    if not aa or not bb or aa == bb:
        return False
    shorter, longer = sorted((aa, bb), key=len)
    if len(shorter) >= 12 and shorter in longer:
        return False
    # Reject near-restatements where one short fact adds no independent answer value.
    def grams(x: str) -> set[str]:
        return {x[i:i+2] for i in range(max(0, len(x)-1))}
    ga, gb = grams(aa), grams(bb)
    overlap = len(ga & gb) / max(1, min(len(ga), len(gb)))
    if overlap >= 0.40 and min(len(aa), len(bb)) <= 22:
        return False
    return True


def _active_troubleshooting_heading(unit: dict[str, Any], section_map: dict[str, dict[str, Any]]) -> bool:
    signals = ("故障", "问题", "异常", "无法", "无反应", "不工作", "过高", "过低", "洗不干净", "残留", "异味", "积水", "噪音")
    return any(any(sig in (section_map.get(sid, {}).get("heading", "") or "") for sig in signals) for sid in unit.get("section_ids", []))


def _relation_name(topic_a: str, topic_b: str) -> str:
    mapping = {
        frozenset(("feature_configuration", "usage_limitation")): "FEATURE_WITH_LIMITATION",
        frozenset(("compatibility", "usage_limitation")): "COMPATIBILITY_WITH_LIMITATION",
        frozenset(("connectivity", "compatibility")): "CONNECTIVITY_WITH_COMPATIBILITY",
        frozenset(("charging", "usage_limitation")): "CHARGING_WITH_LIMITATION",
        frozenset(("installation", "compatibility")): "INSTALLATION_WITH_COMPATIBILITY",
        frozenset(("maintenance", "safety_usage")): "MAINTENANCE_WITH_SAFETY",
        frozenset(("product_knowledge", "usage_limitation")): "CAPABILITY_WITH_LIMITATION",
        frozenset(("physical_spec", "usage_limitation")): "SPEC_WITH_LIMITATION",
        frozenset(("warranty_information", "usage_limitation")): "WARRANTY_WITH_LIMITATION",
        frozenset(("product_knowledge", "warranty_information")): "CAPABILITY_WITH_WARRANTY",
        frozenset(("feature_configuration", "warranty_information")): "FEATURE_WITH_WARRANTY",
        frozenset(("physical_spec", "compatibility")): "SPEC_WITH_COMPATIBILITY",
        frozenset(("usage_instruction", "compatibility")): "USAGE_WITH_COMPATIBILITY",
        frozenset(("feature_configuration", "compatibility")): "FEATURE_WITH_COMPATIBILITY",
        frozenset(("installation", "usage_instruction")): "INSTALLATION_WITH_USAGE",
        frozenset(("feature_configuration", "conditional_instruction")): "FEATURE_WITH_CONDITION",
        frozenset(("usage_instruction", "conditional_instruction")): "USAGE_WITH_CONDITION",
        frozenset(("product_knowledge", "feature_configuration")): "CAPABILITY_WITH_FEATURE",
    }
    if topic_a == topic_b:
        return "SAME_TOPIC_CROSS_REFERENCE"
    return mapping.get(frozenset((topic_a, topic_b)), "EXPLICIT_CROSS_REFERENCE")


def _heading_anchors(unit: dict[str, Any], section_map: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for sid in unit.get("section_ids", []):
        heading = section_map.get(sid, {}).get("heading", "") or ""
        anchor = _clean_heading_anchor(heading, unit.get("document_id", ""))
        # Three-character generic component names (e.g. 充电器/控制台) are too broad;
        # four or more normalized CJK/alphanumeric characters is the conservative gate.
        if len(anchor) >= 4 and not (anchor.endswith("设置") and len(anchor) <= 4):
            rows.append({"section_id": sid, "heading": heading, "anchor": anchor})
    return rows



def _relation_semantics_supported(relation: str, fact_a: str, fact_b: str) -> bool:
    text = fact_a + " " + fact_b
    if relation in {"SAME_TOPIC_CROSS_REFERENCE", "EXPLICIT_CROSS_REFERENCE"}:
        return False
    if "LIMITATION" in relation:
        if not any(x in text for x in ("不支持", "不适用", "不得", "不能", "不可", "限制", "仅", "无权", "超过")):
            return False
    if "WARRANTY" in relation and "保修" not in text:
        return False
    if "COMPATIBILITY" in relation:
        if not any(x in text for x in ("支持", "兼容", "适用", "不支持", "配对", "连接", "可用于", "可让", "可在")):
            return False
    if "CONDITION" in relation:
        if not any(x in text for x in ("若", "如果", "当", "需要", "时", "后", "前", "达到", "超过")):
            return False
    if "SAFETY" in relation:
        if not any(x in text for x in ("安全", "警告", "不得", "必须", "仅可", "成人", "断开", "受伤", "火灾", "触电", "危险")):
            return False
    return True

def _best_explicit_fact_pair(
    a: dict[str, Any],
    b: dict[str, Any],
    fact_map: dict[str, dict[str, Any]],
    section_map: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    anchors_a = _heading_anchors(a, section_map)
    anchors_b = _heading_anchors(b, section_map)
    if not anchors_a and not anchors_b:
        return None
    candidates = []
    a_facts = [fid for fid in a.get("independent_askable_fact_ids", []) if fid in fact_map][:12]
    b_facts = [fid for fid in b.get("independent_askable_fact_ids", []) if fid in fact_map][:12]
    for af in a_facts:
        ta = fact_map[af].get("fact_text", "")
        if not _fact_composition_safe(ta):
            continue
        nta = _normalize(ta)
        for bf in b_facts:
            tb = fact_map[bf].get("fact_text", "")
            if not _fact_composition_safe(tb) or not _fact_pair_distinct(ta, tb):
                continue
            ntb = _normalize(tb)
            links = []
            # A's section concept explicitly appears in B's fact, or vice versa.
            for row in anchors_a:
                if row["anchor"] in ntb:
                    links.append({"referenced_source_unit_id": a["source_unit_id"], "referencing_source_unit_id": b["source_unit_id"], **row})
            for row in anchors_b:
                if row["anchor"] in nta:
                    links.append({"referenced_source_unit_id": b["source_unit_id"], "referencing_source_unit_id": a["source_unit_id"], **row})
            if not links:
                continue
            best_anchor = max(len(x["anchor"]) for x in links)
            relation = _relation_name(a.get("semantic_topic", ""), b.get("semantic_topic", ""))
            if not _relation_semantics_supported(relation, ta, tb):
                continue
            high_value = int(any(x in relation for x in ("LIMITATION", "WARRANTY", "COMPATIBILITY", "CONDITION", "SAFETY")))
            bounded = int(10 <= len(ta) <= 130) + int(10 <= len(tb) <= 130)
            score = best_anchor + 4 * high_value + 2 * bounded
            candidates.append((
                -score,
                af,
                bf,
                {
                    "required_fact_ids": [af, bf],
                    "semantic_relation": relation,
                    "relation_evidence": sorted(links, key=lambda x: (x["section_id"], x["anchor"])),
                    "relation_score": score,
                },
            ))
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x[0], x[1], x[2]))[0][3]


def multi_fact_proposals(units: list[dict[str, Any]], groups: list[dict[str, Any]], fact_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    group_map = {g["group_id"]: g for g in groups}
    rows = []
    for u in units:
        if not u.get("benchmark_usable"):
            continue
        for gid in u.get("coherent_fact_group_ids", []):
            g = group_map.get(gid)
            if not g or not g.get("minimal") or not g.get("independently_askable_as_group"):
                continue
            facts = [fid for fid in g.get("fact_ids", []) if fid in fact_map]
            if not (2 <= len(facts) <= 3):
                continue
            if any(fact_map[fid].get("category_ownership") != "KNOWLEDGE_AVAILABLE" for fid in facts):
                continue
            rows.append({
                "proposal_kind": "MULTI_FACT",
                "source_unit_ids": [u["source_unit_id"]],
                "document_ids": [u["document_id"]],
                "section_ids": list(u["section_ids"]),
                "product_ids": [u["product_id"]] if u.get("product_id") else [],
                "required_fact_ids": facts,
                "supporting_fact_ids": [],
                "fact_relationship": g.get("relationship") or u.get("fact_relationship"),
                "semantic_topic": u.get("semantic_topic"),
                "group_id": gid,
                "semantic_relation": g.get("relationship"),
                "composition_family_id": None,
                "necessity_per_source": [{"source_unit_id": u["source_unit_id"], "necessary": True}],
            })
    return sorted(rows, key=lambda x: (x["document_ids"], x["section_ids"], x["source_unit_ids"], x["required_fact_ids"]))


def multi_section_proposals(
    units: list[dict[str, Any]],
    fact_map: dict[str, dict[str, Any]],
    section_map: dict[str, dict[str, Any]],
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Build only source-linked multi-section compositions.

    The prior broad lexical-overlap heuristic could join two true facts merely because
    they belonged to the same product. G0.2 treats that as an invalid hard-case
    manufacturing strategy. A retained composition now requires explicit evidence in
    one source fact that refers to the other section's non-generic concept.
    """
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for u in units:
        if u.get("benchmark_usable") and u.get("product_id") and u.get("category_ownership") == "KNOWLEDGE_AVAILABLE":
            by_product[u["product_id"]].append(u)

    proposals = []
    for product, rows in sorted(by_product.items()):
        rows = sorted(rows, key=lambda x: x["source_unit_id"])
        for i, a in enumerate(rows):
            if not a.get("independent_askable_fact_ids"):
                continue
            for b in rows[i + 1 :]:
                if set(a.get("section_ids", [])) & set(b.get("section_ids", [])):
                    continue
                if _active_troubleshooting_heading(a, section_map) or _active_troubleshooting_heading(b, section_map):
                    continue
                pair = _best_explicit_fact_pair(a, b, fact_map, section_map)
                if not pair:
                    continue
                facts = pair["required_fact_ids"]
                sections = sorted(set(a["section_ids"] + b["section_ids"]))
                relation = pair["semantic_relation"]
                fam = "KCOMP-" + _sha_obj({"units": sorted([a["source_unit_id"], b["source_unit_id"]]), "facts": sorted(facts), "relation": relation})[:16]
                proposals.append({
                    "proposal_kind": "MULTI_SECTION",
                    "source_unit_ids": sorted([a["source_unit_id"], b["source_unit_id"]]),
                    "document_ids": [a["document_id"]],
                    "section_ids": sections,
                    "product_ids": [product],
                    "required_fact_ids": facts,
                    "supporting_fact_ids": [],
                    "fact_relationship": "MULTI_SECTION_COMPOSITION",
                    "semantic_topic": relation.lower(),
                    "group_id": None,
                    "semantic_relation": relation,
                    "composition_family_id": fam,
                    "necessity_per_source": [
                        {"source_unit_id": a["source_unit_id"], "necessary": True, "required_fact_id": facts[0]},
                        {"source_unit_id": b["source_unit_id"], "necessary": True, "required_fact_id": facts[1]},
                    ],
                    "relation_evidence": pair["relation_evidence"],
                    "relation_score": pair["relation_score"],
                    "composition_validation": "EXPLICIT_CROSS_SECTION_REFERENCE",
                })

    # Deterministic high-quality ordering: strongest relation first, while bounding
    # source concentration. This is proposal generation only; final balance happens
    # in knowledge_selection.select_balanced.
    out = []
    per_product = defaultdict(int)
    per_section = defaultdict(int)
    for p in sorted(
        proposals,
        key=lambda x: (-x.get("relation_score", 0), x["product_ids"], x["semantic_relation"], x["composition_family_id"]),
    ):
        pid = p["product_ids"][0]
        if per_product[pid] >= 8:
            continue
        if any(per_section[s] >= 2 for s in p["section_ids"]):
            continue
        out.append(p)
        per_product[pid] += 1
        for s in p["section_ids"]:
            per_section[s] += 1
        if len(out) >= limit:
            break
    return out
