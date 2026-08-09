"""Deterministic Phase G0.1 Knowledge Source Space audit and KSU construction."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .fact_inventory import extract_atomic_facts
from .knowledge_ownership import build_ownership_inputs, ownership_for_fact
from .knowledge_source_unit import CoherentFactGroup, KnowledgeFactAudit, KnowledgeSourceUnit
from .source_inventory import build_document_source_inventory


FRAGMENT_PREFIX = ("然后", "之后", "随后", "否则", "此外", "同时", "再次", "接着", "此时", "这时", "在这种情况下", "上述", "以下")
NON_TASK_TERMS = ("版权所有", "目录", "商标", "文档版本", "本页故意留白", "扫码", "网址", "www.", "http://", "fcc", "法律声明")
CONDITION_TERMS = ("如果", "若", "当", "如遇", "仅当", "只有", "除非", "在…时", "情况下")
ACTION_TERMS = ("请", "应", "必须", "建议", "按", "选择", "设置", "连接", "安装", "清洁", "检查", "使用", "保持", "不要", "不得", "切勿", "关闭", "打开", "调整", "更换", "咨询", "联系")
PROCEDURE_TERMS = ("步骤", "第1步", "第 1 步", "首先", "然后", "下一步", "安装", "设置", "操作")
GENERIC_HEADINGS = {"注意", "说明", "警告", "重要", "其他", "其他问题", "简介", "概述", "preamble", "root"}


def _hash(prefix: str, payload: str, n: int = 16) -> str:
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:n]


def _norm(text: str) -> str:
    text = re.sub(r"<PIC>", " ", text or "")
    text = re.sub(r"\s+", "", text).lower()
    text = re.sub(r"[，。！？；：、,.!?;:'\"“”‘’`()（）\[\]【】<>《》*_#`]+", "", text)
    return text


def _section_structure(section: dict[str, Any], facts: list[Any]) -> str:
    text = section.get("text") or ""
    title = section.get("title") or ""
    if not facts:
        return "FRAGMENT_CONTAINER"
    if section.get("source_type") == "faq":
        return "FAQ_QA" if len(facts) else "FRAGMENT_CONTAINER"
    if section.get("source_type") == "policy":
        return "POLICY_RULE"
    type_counts = Counter(f.fact_type for f in facts)
    bullets = len(re.findall(r"(?:^|\n)\s*(?:\d+[.、)]|[-●·•○])", text))
    table_like = text.count("|") >= 4 or bool(re.search(r"\b(?:重量|尺寸|容量|电压|功率|频率)\s*[：:]", text))
    if table_like and type_counts["PRODUCT_SPEC"]:
        return "ATTRIBUTE_TABLE"
    if type_counts["COMPATIBILITY"] >= max(1, len(facts) // 2):
        return "COMPATIBILITY_RULE"
    if type_counts["LIMITATION"] >= max(1, len(facts) // 2):
        return "LIMITATION_RULE"
    if bullets >= 2 and (any(x in title for x in PROCEDURE_TERMS) or re.search(r"(?:^|\s)\d+[.、)]", text)):
        return "PROCEDURE"
    if any(x in text for x in ("如果", "若", "当", "否则")) and any(x in text for x in ACTION_TERMS):
        return "CONDITION_ACTION"
    if len(facts) == 1:
        return "SINGLE_FACT"
    if bullets >= 2:
        return "BULLET_FACT_LIST"
    if len(facts) >= 2:
        return "MULTI_FACT_DESCRIPTION"
    return "MIXED_STRUCTURE"


def _relationship(source_type: str, section_structure: str, fact: Any) -> str:
    if source_type == "faq":
        return "QUESTION_ANSWER"
    if source_type == "policy" or fact.fact_type in {"POLICY", "RETURN_POLICY", "WARRANTY_POLICY", "AFTER_SALES"}:
        return "POLICY_RULE"
    if fact.fact_type == "PRODUCT_SPEC":
        return "ATTRIBUTE_VALUE"
    if fact.fact_type == "COMPATIBILITY":
        return "COMPATIBILITY_RELATION"
    if fact.fact_type == "LIMITATION":
        return "LIMITATION"
    text = fact.normalized_value
    if section_structure == "PROCEDURE":
        return "PROCEDURE"
    if any(text.startswith(x) for x in ("如果", "若", "当", "如")) or (any(x in text for x in ("如果", "若", "当", "否则")) and any(x in text for x in ACTION_TERMS)):
        return "CONDITION_ACTION"
    if section_structure in {"BULLET_FACT_LIST", "MULTI_FACT_DESCRIPTION"} and len(text) > 120:
        return "MULTI_FACT_DESCRIPTION"
    return "INDEPENDENT"


def _semantic_topic(section: dict[str, Any], facts: list[Any], relationship: str) -> str:
    hay = ((section.get("path") or "") + "\n" + "\n".join(f.normalized_value for f in facts[:8])).lower()
    source_type = section.get("source_type")
    if source_type == "faq": return "faq_process"
    if source_type == "policy":
        if "退货" in hay or "退款" in hay: return "return_refund_policy"
        if "保修" in hay or "质保" in hay: return "warranty_rule"
        if "取消" in hay: return "cancellation_policy"
        if "身份" in hay: return "identity_policy"
        return "after_sales_policy"
    rules = [
        (("兼容", "适用", "支持"), "compatibility"),
        (("限制", "不支持", "不能", "不可"), "usage_limitation"),
        (("规格", "参数", "尺寸", "重量", "容量", "电压", "功率"), "physical_spec"),
        (("清洁", "维护", "保养"), "maintenance"),
        (("安装", "装配", "接线"), "installation"),
        (("充电", "电池"), "charging"),
        (("蓝牙", "连接", "网络", "usb", "接口"), "connectivity"),
        (("安全", "警告", "危险", "禁止", "切勿", "不得"), "safety_usage"),
        (("保修", "质保"), "warranty_information"),
        (("功能", "模式", "设置", "操作"), "feature_configuration"),
        (("使用", "说明"), "usage_instruction"),
    ]
    for keys, topic in rules:
        if any(k in hay for k in keys):
            return topic
    return {
        "ATTRIBUTE_VALUE":"physical_spec",
        "COMPATIBILITY_RELATION":"compatibility",
        "LIMITATION":"usage_limitation",
        "PROCEDURE":"procedure",
        "CONDITION_ACTION":"conditional_instruction",
    }.get(relationship, "product_knowledge")


def _local_context(section: dict[str, Any], fact: Any, relationship: str) -> tuple[str, ...]:
    text = fact.normalized_value.strip()
    ctx: list[str] = []
    if section.get("title") and section.get("title") not in GENERIC_HEADINGS:
        if text.startswith(FRAGMENT_PREFIX) or len(text) < 42 or relationship in {"ATTRIBUTE_VALUE", "PROCEDURE", "QUESTION_ANSWER"}:
            ctx.append("section_heading")
    if relationship == "ATTRIBUTE_VALUE":
        ctx.append("attribute_label_or_table_header")
    if text.startswith(("如果", "若", "当", "如")):
        ctx.append("condition_clause")
    if text.startswith(FRAGMENT_PREFIX):
        ctx.append("preceding_context")
    if any(x in text for x in ("该", "此", "上述", "以下", "其", "它")) and len(text) < 80:
        ctx.append("referent_context")
    return tuple(dict.fromkeys(ctx))


def _non_task(section: dict[str, Any], text: str) -> bool:
    path = section.get("path") or ""
    title = section.get("title") or ""
    if title in {"目录", "preamble", "root"} or path.endswith(" / 目录"):
        return True
    low = f"{title}\n{path}\n{text}".lower()
    return any(term in low for term in NON_TASK_TERMS)


def _task_usability(section: dict[str, Any], fact: Any, relationship: str, ownership: str) -> tuple[str, bool, tuple[str, ...]]:
    text = fact.normalized_value.strip()
    flags: list[str] = []
    if not fact.benchmark_usable:
        return "UNSUPPORTED", False, ("D0_HEURISTIC_UNUSABLE",)
    if ownership == "TROUBLESHOOTING":
        return "CATEGORY_OWNERSHIP_EXCLUDED", False, ("TROUBLESHOOTING_OWNED",)
    if _non_task(section, text):
        return "NON_TASK_INFORMATION", False, ("NON_TASK_INFORMATION",)
    if len(_norm(text)) < 8:
        return "FRAGMENT", False, ("TOO_SHORT_FOR_TASK_CORE",)
    if text.endswith(("：", ":")) or (text.startswith(FRAGMENT_PREFIX) and len(text) < 60):
        return "FRAGMENT", False, ("FRAGMENT_PRESENT",)
    ctx = _local_context(section, fact, relationship)
    if text.startswith(FRAGMENT_PREFIX) or ("preceding_context" in ctx and len(text) < 120):
        return "CONTEXT_DEPENDENT", False, ("CONTEXT_DEPENDENT",)
    # Avoid procedure-step inflation: source truth is useful, but an individual
    # step is not automatically an independent task core.
    if relationship == "PROCEDURE":
        if len(text) < 55 or re.match(r"^(?:\d+[.、)]\s*)?(?:按|然后|接着|选择|输入|点击|再次|完成后)", text):
            return "GROUP_ONLY", False, ("PROCEDURE_STEP_NOT_INDEPENDENT",)
        # Long procedure sentences with explicit object/condition may still be
        # independently askable, but the enclosing procedure is preserved too.
        return "TASK_USABLE", True, ("PROCEDURE_CONTEXT_PRESERVED",)
    if relationship == "QUESTION_ANSWER":
        # FAQ leaf answer sentences are preserved as one Q/A SourceUnit rather
        # than inflated into sentence-level independent QA capacity.
        return "GROUP_ONLY", False, ("FAQ_ANSWER_GROUPED",)
    if relationship == "POLICY_RULE" and len(text) < 18:
        return "GROUP_ONLY", False, ("POLICY_RULE_REQUIRES_LOCAL_GROUP",)
    if relationship == "CONDITION_ACTION":
        has_condition = any(x in text for x in ("如果", "若", "当", "如"))
        has_action = any(x in text for x in ACTION_TERMS)
        if has_condition and has_action:
            return "TASK_USABLE", True, ()
        return "GROUP_ONLY", False, ("CONDITION_ACTION_GROUP_REQUIRED",)
    if relationship in {"ATTRIBUTE_VALUE", "COMPATIBILITY_RELATION", "LIMITATION"}:
        return "TASK_USABLE", True, ()
    # Broad safety/feature facts can be independently meaningful if they are
    # self-contained. Very short imperative fragments stay group-only.
    if len(text) < 28 and any(text.startswith(x) for x in ACTION_TERMS):
        return "GROUP_ONLY", False, ("SHORT_INSTRUCTION_GROUP_REQUIRED",)
    return "TASK_USABLE", True, ()


def _group_semantics(facts: list[KnowledgeFactAudit], relationship: str) -> str:
    if relationship == "PROCEDURE": return "minimal procedure context"
    if relationship == "QUESTION_ANSWER": return "canonical FAQ question and answer facts"
    if relationship == "POLICY_RULE": return "policy condition/rule/exception context"
    if relationship == "CONDITION_ACTION": return "condition and required action"
    return "minimal coherent related fact group"


def audit_knowledge_source_space(root: Path) -> dict[str, Any]:
    docs, sections = build_document_source_inventory(root)
    facts = extract_atomic_facts(sections)
    section_map = {s["section_id"]: s for s in sections}
    facts_by_section: dict[str, list[Any]] = defaultdict(list)
    for f in facts:
        facts_by_section[f.section_id].append(f)
    ownership_inputs = build_ownership_inputs(root)

    section_audits: list[dict[str, Any]] = []
    fact_audits: list[KnowledgeFactAudit] = []
    fact_audit_map: dict[str, KnowledgeFactAudit] = {}
    fact_obj_map = {f.fact_id: f for f in facts}

    for section in sections:
        sfacts = facts_by_section.get(section["section_id"], [])
        structure = _section_structure(section, sfacts)
        section_audits.append({
            "document_id": section["document_id"], "section_id": section["section_id"],
            "heading": section.get("title"), "parent_heading": (section.get("path") or "").rsplit(" / ",1)[0] if " / " in (section.get("path") or "") else None,
            "section_path": section.get("path"), "section_text": section.get("text"),
            "fact_ids": [f.fact_id for f in sfacts], "fact_count": len(sfacts),
            "section_semantics": _semantic_topic(section, sfacts, structure),
            "section_structure": structure, "benchmark_usable": bool(sfacts),
        })
        for fact in sfacts:
            owner, overlaps = ownership_for_fact(fact_id=fact.fact_id, section_id=fact.section_id, inputs=ownership_inputs)
            rel = _relationship(section["source_type"], structure, fact)
            usability, independent, flags = _task_usability(section, fact, rel, owner)
            ctx = _local_context(section, fact, rel)
            audit = KnowledgeFactAudit(
                fact_id=fact.fact_id, document_id=fact.document_id, section_id=fact.section_id,
                source_type=section["source_type"], product_id=section.get("product_id"), fact_type=fact.fact_type,
                fact_text=fact.normalized_value, relationship=rel, task_usability=usability,
                independently_askable=independent, required_local_context=ctx,
                category_ownership=owner, ownership_overlaps=overlaps, quality_flags=tuple(flags),
            )
            fact_audits.append(audit); fact_audit_map[audit.fact_id] = audit

    # Build minimal coherent groups only for facts that are not independently
    # usable. One section cannot inflate into arbitrary sliding-window groups.
    coherent_groups: list[CoherentFactGroup] = []
    groups_by_section: dict[str, list[CoherentFactGroup]] = defaultdict(list)
    for section in sections:
        audits = [fact_audit_map[f.fact_id] for f in facts_by_section.get(section["section_id"], [])]
        eligible = [a for a in audits if a.category_ownership == "KNOWLEDGE_AVAILABLE" and a.task_usability in {"GROUP_ONLY", "CONTEXT_DEPENDENT"}]
        if not eligible:
            continue
        structure = _section_structure(section, facts_by_section.get(section["section_id"], []))
        rels = [a.relationship for a in eligible]
        # FAQ and policy are one semantic rule/Q&A unit, but group size is
        # capped to 3; larger answers remain a SourceUnit and are not counted as
        # many independent groups.
        if structure in {"FAQ_QA", "POLICY_RULE"}:
            chunks = [eligible[:3]] if eligible else []
        elif structure == "PROCEDURE":
            chunks = [eligible[:3]] if len(eligible) >= 2 else []
        else:
            chunks = []
            if len(eligible) >= 2:
                chunks = [eligible[:3]]
        for chunk in chunks:
            if not chunk:
                continue
            relationship = Counter(a.relationship for a in chunk).most_common(1)[0][0]
            gids = tuple(a.fact_id for a in chunk)
            gid = _hash("KFG-", f"{section['section_id']}|{relationship}|{'|'.join(gids)}")
            ctx = tuple(sorted({x for a in chunk for x in a.required_local_context}))
            grp = CoherentFactGroup(
                group_id=gid, document_id=section["document_id"], section_id=section["section_id"],
                fact_ids=gids, relationship=relationship, group_semantics=_group_semantics(chunk, relationship),
                minimal=len(gids) <= 3, independently_askable_as_group=True, required_context=ctx,
                reason="facts are context-linked; grouped once without section-wide or sliding-window inflation",
            )
            coherent_groups.append(grp); groups_by_section[section["section_id"]].append(grp)

    # KSU construction: preserve section-level semantic structure, but split
    # mixed sections by ownership and relationship bucket. This supports
    # 1-section->multiple-units without making every AtomicFact a unit.
    units: list[KnowledgeSourceUnit] = []
    doc_map = {d["document_id"]: d for d in docs}
    for section in sections:
        audits = [fact_audit_map[f.fact_id] for f in facts_by_section.get(section["section_id"], [])]
        if not audits:
            continue
        structure = _section_structure(section, facts_by_section.get(section["section_id"], []))
        # Source structures that are semantically one object remain one bucket.
        buckets: dict[tuple[str,str], list[KnowledgeFactAudit]] = defaultdict(list)
        for a in audits:
            owner = a.category_ownership
            if structure in {"FAQ_QA", "POLICY_RULE", "PROCEDURE"}:
                rel_bucket = structure
            else:
                rel_bucket = a.relationship
            buckets[(owner, rel_bucket)].append(a)
        for (owner, rel_bucket), rows in sorted(buckets.items()):
            fact_ids = tuple(a.fact_id for a in rows)
            askable = tuple(a.fact_id for a in rows if a.independently_askable and a.task_usability == "TASK_USABLE")
            grouped = tuple(g.group_id for g in groups_by_section.get(section["section_id"], []) if set(g.fact_ids).issubset(set(fact_ids)))
            context_ids = tuple(a.fact_id for a in rows if a.task_usability in {"CONTEXT_DEPENDENT", "FRAGMENT"})
            supporting = tuple(a.fact_id for a in rows if a.task_usability in {"GROUP_ONLY", "CONTEXT_DEPENDENT"})
            primary = askable if askable else tuple(g.fact_ids[0] for g in groups_by_section.get(section["section_id"], []) if set(g.fact_ids).issubset(set(fact_ids)))
            req_ctx = tuple(sorted({x for a in rows for x in a.required_local_context}))
            if owner != "KNOWLEDGE_AVAILABLE":
                usability = "OWNED_BY_OTHER_CATEGORY"
            elif askable:
                usability = "BENCHMARK_USABLE"
            elif grouped:
                usability = "BENCHMARK_USABLE_WITH_GROUPING"
            else:
                usability = "NOT_USABLE"
            relationship = rel_bucket if rel_bucket not in {"FAQ_QA", "POLICY_RULE"} else ("QUESTION_ANSWER" if rel_bucket == "FAQ_QA" else "POLICY_RULE")
            topic = _semantic_topic(section, [fact_obj_map[a.fact_id] for a in rows], relationship)
            norm_sem = "|".join(sorted(_norm(a.fact_text) for a in rows if a.task_usability not in {"NON_TASK_INFORMATION", "UNSUPPORTED"}))
            product_family = (doc_map.get(section["document_id"]) or {}).get("product_family")
            semantic_payload = f"{product_family}|{topic}|{relationship}|{norm_sem}"
            cross_payload = f"{topic}|{relationship}|{norm_sem}"
            flags = set()
            if any(a.task_usability == "FRAGMENT" for a in rows): flags.add("FRAGMENT_PRESENT")
            if any(a.task_usability == "CONTEXT_DEPENDENT" for a in rows): flags.add("CONTEXT_DEPENDENT")
            if len(rows) > 12: flags.add("TOO_MANY_FACTS")
            if structure == "PROCEDURE": flags.add("PROCEDURE_STRUCTURE")
            if grouped: flags.add("MULTI_FACT_GROUP")
            if owner == "TROUBLESHOOTING": flags.add("TROUBLESHOOTING_OWNED")
            if any(a.required_local_context and "attribute_label_or_table_header" in a.required_local_context for a in rows): flags.add("TABLE_CONTEXT_REQUIRED")
            if section.get("source_type") == "policy" and any("通常" in a.fact_text or "可能" in a.fact_text for a in rows): flags.add("POLICY_AMBIGUITY")
            sid = _hash("KSU-", f"{section['document_id']}|{section['section_id']}|{owner}|{relationship}|{norm_sem}")
            units.append(KnowledgeSourceUnit(
                source_unit_id=sid, document_id=section["document_id"], section_ids=(section["section_id"],),
                source_type=section["source_type"], product_id=section.get("product_id"), product_family=product_family,
                semantic_topic=topic, unit_type=structure, fact_ids=fact_ids, primary_fact_ids=primary,
                supporting_fact_ids=supporting, context_fact_ids=context_ids, fact_relationship=relationship,
                independent_askable_fact_ids=askable, coherent_fact_group_ids=grouped,
                required_local_context=req_ctx, category_ownership=owner, knowledge_usability=usability,
                semantic_signature=hashlib.sha256(semantic_payload.encode()).hexdigest(),
                cross_product_signature=hashlib.sha256(cross_payload.encode()).hexdigest(), quality_flags=tuple(sorted(flags)),
            ))

    # Cross-product semantic duplicate flag is added at report level; the
    # immutable units retain signatures and can be re-evaluated deterministically.
    return {
        "documents": docs, "sections": sections, "facts": facts,
        "section_audits": section_audits, "fact_audits": fact_audits,
        "coherent_groups": coherent_groups, "source_units": units,
        "ownership_inputs": ownership_inputs,
    }
