"""Deterministic, source-linked fact-space extraction for Phase D0."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .contracts import AtomicFact, StructuredFactCandidate

PIC = re.compile(r"<PIC>|<!\[CDATA\[|\]\]>")
TOC = re.compile(r"\.{3,}\s*\d+\s*$|^[\d\s\.]+$")
SPLIT = re.compile(r"(?<=[。！？；!?])\s*|\n+")


def _clean(value: str) -> str:
    value = PIC.sub(" ", value)
    value = re.sub(r"^#{1,6}\s+", "", value).strip()
    value = re.sub(r"^[●·•○\-*]+\s*", "", value).strip()
    value = re.sub(r"^\d+[.)、]\s*", "", value).strip()
    return re.sub(r"\s+", " ", value).strip()


def _fact_type(source_type: str, heading: str, text: str) -> str:
    hay = f"{heading}\n{text}".lower()
    if any(x in hay for x in ("错误码", "故障码", "error code", "报错")): return "ERROR_CODE"
    if any(x in hay for x in ("故障", "排查", "异常", "无法", "无响应", "troubleshoot")): return "TROUBLESHOOTING_STEP"
    if any(x in hay for x in ("退货", "退换", "退款")): return "RETURN_POLICY" if source_type in {"policy", "faq"} else "AFTER_SALES"
    if any(x in hay for x in ("保修", "质保", "warranty")): return "WARRANTY_POLICY" if source_type in {"policy", "faq"} else "WARRANTY"
    if any(x in hay for x in ("警告", "安全", "危险", "禁止", "切勿", "不得")): return "SAFETY_INSTRUCTION"
    if any(x in hay for x in ("规格", "参数", "技术规格", "电压", "重量", "尺寸", "容量")): return "PRODUCT_SPEC"
    if any(x in hay for x in ("兼容", "支持", "适用")): return "COMPATIBILITY"
    if any(x in hay for x in ("限制", "不适用", "不能", "不可")): return "LIMITATION"
    if source_type == "policy": return "POLICY"
    if source_type == "faq": return "FAQ_PROCESS"
    return "FEATURE_OR_INSTRUCTION"


def _ambiguity(text: str) -> str:
    if any(x in text for x in ("可能", "通常", "视情况", "根据", "具体", "因人而异", "建议咨询")):
        return "MEDIUM"
    return "LOW"


def extract_atomic_facts(sections: list[dict[str, Any]]) -> list[AtomicFact]:
    facts: list[AtomicFact] = []
    seen = set()
    for section in sections:
        heading = section.get("title") or ""
        body_lines = []
        for raw in SPLIT.split(section.get("text") or ""):
            text = _clean(raw)
            if not text or text == heading or TOC.search(text):
                continue
            # Avoid labels/headings and OCR/PIC remnants as fact capacity.
            if len(text) < 8 or len(text) > 420 or text.count("…") > 3:
                continue
            if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text):
                continue
            normalized = re.sub(r"\s+", "", text).lower()
            dedup_key = (section["document_id"], section["section_id"], normalized)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            ftype = _fact_type(section["source_type"], heading, text)
            digest = hashlib.sha256(f"{section['section_id']}|{normalized}".encode()).hexdigest()[:16]
            subject = section.get("product_name") or section["document_id"]
            predicate = ftype.lower()
            usable = not any(x in text for x in ("访问以下网址", "详见第", "参见第", "目录"))
            facts.append(AtomicFact(
                fact_id=f"af:{digest}", source_id=section["source_id"], document_id=section["document_id"],
                section_id=section["section_id"], subject=str(subject), predicate=predicate,
                normalized_value=text, authority=section["source_type"], ambiguity=_ambiguity(text),
                benchmark_usable=usable, notes=None if usable else "cross-reference/external-reference requires additional source resolution",
                fact_type=ftype,
            ))
    return facts


def troubleshooting_space(facts: list[AtomicFact], sections: list[dict[str, Any]]) -> dict[str, Any]:
    tfacts = [f for f in facts if f.fact_type in {"TROUBLESHOOTING_STEP", "ERROR_CODE"}]
    section_ids = {f.section_id for f in tfacts}
    multi_step = 0; missing_info = 0; handoff = 0; conditional = 0
    for section in sections:
        if section["section_id"] not in section_ids:
            continue
        text = section["text"]
        if len(re.findall(r"(?:^|\n)\s*(?:\d+[.、)]|[-●·])", text)) >= 2: multi_step += 1
        if any(x in text for x in ("型号", "确认", "检查是否", "若", "如果")): missing_info += 1
        if any(x in text for x in ("联系", "就医", "维修", "专业人员", "客服")): handoff += 1
        if any(x in text for x in ("若", "如果", "否则", "当")): conditional += 1
    return {
        "fact_count": len(tfacts), "section_count": len(section_ids), "multi_step_sections": multi_step,
        "missing_information_sections": missing_info, "handoff_or_escalation_sections": handoff,
        "conditional_sections": conditional,
        "fact_type_distribution": dict(Counter(f.fact_type for f in tfacts)),
    }


def build_structured_fact_candidates(root: Path, structured_inventory: dict[str, Any]) -> list[StructuredFactCandidate]:
    db = root / structured_inventory["database"]
    table_map = {row["record_type"]: row for row in structured_inventory["tables"]}
    template_map: dict[tuple[str,str], list[str]] = defaultdict(list)
    for tpl in structured_inventory["sql_templates"]:
        tid = tpl["template_id"]
        if tid == "order_events": rtype="order_event"
        elif tid.startswith("order_") or tid == "customer_orders": rtype="order"
        elif tid == "ticket_events": rtype="ticket_event"
        elif tid.startswith("ticket_") or tid == "customer_tickets": rtype="ticket"
        elif tid.startswith("warranty_"): rtype="warranty"
        elif tid.startswith("customer_"): rtype="customer"
        else: continue
        for field in tpl["output_fields"]:
            template_map[(rtype, field)].append(tid)
    source_table = {"customer":"customers", "order":"orders", "order_event":"order_status_events", "ticket":"tickets", "ticket_event":"ticket_events", "warranty":"warranty_cases"}
    # Fields which are available in joined output but live on related tables are counted via template rows, not base PRAGMA.
    joined_fields = {"product_id", "product_name", "quantity", "price_per_unit"}
    results=[]
    with sqlite3.connect(db) as conn:
        conn.row_factory=sqlite3.Row
        for (rtype, field), tids in sorted(template_map.items()):
            if rtype == "order" and field in joined_fields:
                if field == "product_name":
                    sql="SELECT p.name v FROM order_items i JOIN products p ON p.product_id=i.product_id"
                else:
                    sql=f"SELECT {field} v FROM order_items"
            else:
                table=source_table.get(rtype)
                cols={c["name"] for c in (table_map.get(rtype) or {}).get("columns",[])}
                if not table or field not in cols:
                    # event-only fields are intentionally excluded from normal snapshot fact inventory; events remain separate source capacity.
                    continue
                sql=f"SELECT {field} v FROM {table}"
            vals=[r[0] for r in conn.execute(sql)]
            non=[v for v in vals if v is not None and str(v) != ""]
            distinct=len({str(v) for v in non})
            privacy="SENSITIVE" if field in {"name","company_name"} else "BUSINESS_PRIVATE"
            event_identity_gap = rtype in {"order_event", "ticket_event"}
            usable = field not in {"name", "company_name", "source_system"} and not event_identity_gap
            example=None
            if non and field in {"status","channel","priority","issue_type","coverage_type","coverage_status","product_id","product_name"}:
                example=str(non[0])[:80]
            results.append(StructuredFactCandidate(
                fact_type=f"{rtype}.{field}", record_type=rtype, field_path=field,
                exposed_by_templates=tuple(sorted(tids)), record_count=len(vals), non_null_count=len(non),
                distinct_value_count=distinct, benchmark_usable=usable, privacy_class=privacy,
                example_value_redacted=example,
            ))
    return results
