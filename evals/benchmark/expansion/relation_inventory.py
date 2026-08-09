"""Real relation and mixed-task space audit."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .contracts import RelationRecord


def build_relation_inventory(root: Path) -> list[RelationRecord]:
    db = root / "data/structured/liorin.db"
    counts={}
    with sqlite3.connect(db) as conn:
        queries={
            "customer_order":"SELECT COUNT(*) FROM orders",
            "order_product":"SELECT COUNT(*) FROM order_items",
            "order_event":"SELECT COUNT(*) FROM order_status_events",
            "customer_ticket":"SELECT COUNT(*) FROM tickets",
            "ticket_product":"SELECT COUNT(*) FROM tickets WHERE product_id IS NOT NULL",
            "ticket_order":"SELECT COUNT(*) FROM tickets WHERE order_id IS NOT NULL",
            "ticket_event":"SELECT COUNT(*) FROM ticket_events",
            "customer_warranty":"SELECT COUNT(*) FROM warranty_cases",
            "warranty_product":"SELECT COUNT(*) FROM warranty_cases WHERE product_id IS NOT NULL",
            "warranty_order":"SELECT COUNT(*) FROM warranty_cases WHERE order_id IS NOT NULL",
            "warranty_ticket":"SELECT COUNT(*) FROM warranty_cases WHERE ticket_id IS NOT NULL",
        }
        for key, sql in queries.items(): counts[key]=int(conn.execute(sql).fetchone()[0])
    rows=[
        RelationRecord("rel:customer:order","customer","order","customer_id","structured_db",True,True,("PRIVATE_BUSINESS_QUERY","MIXED_KNOWLEDGE_STRUCTURED"),counts["customer_order"]),
        RelationRecord("rel:order:product","order","product","order_items(order_id,product_id)","structured_db",True,True,("PRIVATE_BUSINESS_QUERY","MIXED_KNOWLEDGE_STRUCTURED"),counts["order_product"]),
        RelationRecord("rel:order:event","order","order_event","order_id","structured_db",True,True,("PRIVATE_BUSINESS_QUERY",),counts["order_event"]),
        RelationRecord("rel:customer:ticket","customer","ticket","customer_id","structured_db",True,True,("PRIVATE_BUSINESS_QUERY",),counts["customer_ticket"]),
        RelationRecord("rel:ticket:product","ticket","product","product_id","structured_db",True,True,("MIXED_KNOWLEDGE_STRUCTURED","TROUBLESHOOTING"),counts["ticket_product"]),
        RelationRecord("rel:ticket:order","ticket","order","order_id","structured_db",True,True,("PRIVATE_BUSINESS_QUERY",),counts["ticket_order"]),
        RelationRecord("rel:ticket:event","ticket","ticket_event","ticket_id","structured_db",True,True,("PRIVATE_BUSINESS_QUERY",),counts["ticket_event"]),
        RelationRecord("rel:customer:warranty","customer","warranty","customer_id","structured_db",True,True,("PRIVATE_BUSINESS_QUERY","MIXED_KNOWLEDGE_STRUCTURED"),counts["customer_warranty"]),
        RelationRecord("rel:warranty:product","warranty","product","product_id","structured_db",True,True,("MIXED_KNOWLEDGE_STRUCTURED",),counts["warranty_product"]),
        RelationRecord("rel:warranty:order","warranty","order","order_id","structured_db",True,True,("PRIVATE_BUSINESS_QUERY",),counts["warranty_order"]),
        RelationRecord("rel:warranty:ticket","warranty","ticket","ticket_id","structured_db",True,True,("PRIVATE_BUSINESS_QUERY",),counts["warranty_ticket"]),
        RelationRecord("rel:product:manual","product","document","products.manual_file -> manual document","structured+knowledge",True,True,("KNOWLEDGE_QA","TROUBLESHOOTING","MIXED_KNOWLEDGE_STRUCTURED"),20),
        RelationRecord("rel:product:after_sales_policy","product","policy","global product after-sales applicability","knowledge_policy",True,True,("MIXED_KNOWLEDGE_STRUCTURED",),20,"Policy is repository-global; product/contract/region exceptions may override."),
    ]
    return rows


def build_mixed_combination_inventory(root: Path, facts: list[Any], structured_facts: list[Any]) -> list[dict[str, Any]]:
    by_type={f.fact_type for f in facts if f.benchmark_usable}
    sf={f.fact_type for f in structured_facts if f.benchmark_usable}
    candidates=[]
    def add(fid,sfact,dfacts,path,capacity,notes):
        available=[x for x in dfacts if x in by_type]
        if sfact in sf and available:
            candidates.append({"mixed_family_id":fid,"structured_fact_type":sfact,"document_fact_types":available,"join_path":path,"required_evidence_types":["STRUCTURED_DATA","DOCUMENT"],"production_supported":True,"candidate_capacity":capacity,"notes":notes})
    with sqlite3.connect(root/'data/structured/liorin.db') as conn:
        order_product=int(conn.execute('SELECT COUNT(DISTINCT i.order_id) FROM order_items i').fetchone()[0])
        ticket_product=int(conn.execute('SELECT COUNT(*) FROM tickets WHERE product_id IS NOT NULL').fetchone()[0])
        warranty_product=int(conn.execute('SELECT COUNT(*) FROM warranty_cases WHERE product_id IS NOT NULL').fetchone()[0])
    add("mixed:order-date:return-policy","order.order_date",["RETURN_POLICY"],"order -> after_sales_policy",order_product,"Return eligibility needs both purchase/delivery timing and policy; actual delivery date may additionally require order events.")
    add("mixed:order-status:cancel-policy","order.status",["RETURN_POLICY","POLICY"],"order -> after_sales_policy",order_product,"Cancellation/return path depends on current order state and policy.")
    add("mixed:order-product:manual","order.product_id",["FEATURE_OR_INSTRUCTION","PRODUCT_SPEC","SAFETY_INSTRUCTION","TROUBLESHOOTING_STEP"],"order -> order_items -> product -> manual",order_product,"Product purchased in the private order determines which manual is applicable.")
    add("mixed:ticket-product:troubleshooting","ticket.product_id",["TROUBLESHOOTING_STEP","ERROR_CODE","SAFETY_INSTRUCTION"],"ticket -> product -> manual",ticket_product,"Ticket identifies product/context; manual provides resolution evidence.")
    add("mixed:warranty-status:policy","warranty.coverage_status",["WARRANTY_POLICY","POLICY"],"warranty -> after_sales_policy",warranty_product,"Structured warranty state plus policy explains coverage/next step.")
    add("mixed:warranty-product:manual","warranty.product_id",["TROUBLESHOOTING_STEP","SAFETY_INSTRUCTION","FEATURE_OR_INSTRUCTION"],"warranty -> product -> manual",warranty_product,"Warranty case anchors product while manual supplies troubleshooting/safety content.")
    return candidates
