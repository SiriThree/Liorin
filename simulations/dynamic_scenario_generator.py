"""Dynamic scenario generator for Liorin support simulations."""

import hashlib
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Archetype:
    archetype_id: str
    description: str
    requires_verification: bool
    sentiment_weights: list[int]
    typical_queries: list[str]
    tags: list[str]
    segment_filter: Optional[str] = None
    hint: str = ""


ARCHETYPES: list[Archetype] = [
    Archetype(
        archetype_id="order_status_check",
        description="Customer checking the status of a recent product order.",
        requires_verification=True,
        sentiment_weights=[60, 25, 15],
        typical_queries=["Where is my order?", "Has it shipped?", "What is the tracking number?"],
        tags=["order", "tracking", "order_agent"],
        hint="Ask about a recent order and tracking status.",
    ),
    Archetype(
        archetype_id="repair_ticket_followup",
        description="Customer following up on an after-sales repair or troubleshooting ticket.",
        requires_verification=True,
        sentiment_weights=[35, 10, 55],
        typical_queries=["What is happening with my repair?", "Is my support ticket still open?", "What is the next step?"],
        tags=["ticket", "repair", "order_agent"],
        hint="Mention a product problem and ask for the current ticket status.",
    ),
    Archetype(
        archetype_id="warranty_claim",
        description="Customer asking whether a purchased product is still under warranty.",
        requires_verification=True,
        sentiment_weights=[45, 10, 45],
        typical_queries=["Is this covered by warranty?", "Can I request warranty repair?", "When does coverage expire?"],
        tags=["warranty", "order_agent", "knowledge_agent"],
        hint="Reference a recent product and ask about warranty coverage.",
    ),
    Archetype(
        archetype_id="manual_troubleshooting",
        description="Customer asking for product manual troubleshooting without account access.",
        requires_verification=False,
        sentiment_weights=[55, 20, 25],
        typical_queries=["How do I fix this error?", "What should I check first?", "How do I reset the device?"],
        tags=["manual", "troubleshooting", "knowledge_agent"],
        hint="Ask a practical troubleshooting question that can be answered from a manual.",
    ),
    Archetype(
        archetype_id="refund_policy",
        description="Customer asking about refund, return, or approval policy.",
        requires_verification=False,
        sentiment_weights=[65, 20, 15],
        typical_queries=["Can I request a refund?", "What approvals are needed?", "What is the return window?"],
        tags=["policy", "refund", "knowledge_agent"],
        hint="Ask about policy requirements without asking to execute the refund yet.",
    ),
    Archetype(
        archetype_id="enterprise_fleet_issue",
        description="Enterprise customer asking about several devices and support priority.",
        requires_verification=True,
        sentiment_weights=[45, 10, 45],
        typical_queries=["We have multiple failing units", "What is our support priority?", "Can you summarize our open tickets?"],
        tags=["enterprise", "ticket", "order_agent"],
        segment_filter="Enterprise",
        hint="Use an operational enterprise tone and ask for support context.",
    ),
]

COMMUNICATION_STYLES: dict[tuple[str, str], str] = {
    ("Consumer", "neutral"): "Direct and conversational",
    ("Consumer", "positive"): "Friendly and casual",
    ("Consumer", "negative"): "Short and frustrated",
    ("Enterprise", "neutral"): "Formal and operational",
    ("Enterprise", "positive"): "Professional and appreciative",
    ("Enterprise", "negative"): "Formal, urgent, and business-critical",
}


def _fetch_customer(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT customer_id, name, email, segment FROM customers ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        return {"customer_id": row[0], "name": row[1], "email": row[2], "segment": row[3]}
    finally:
        conn.close()


def _fetch_recent_orders(db_path: Path, customer_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT o.order_id, o.status, o.order_date,
                   GROUP_CONCAT(p.name, ', ') AS products
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE o.customer_id = ?
            GROUP BY o.order_id, o.status, o.order_date
            ORDER BY o.order_date DESC
            LIMIT 3
            """,
            (customer_id,),
        ).fetchall()
        return [
            {"order_id": row[0], "status": row[1], "order_date": row[2], "products": row[3]}
            for row in rows
        ]
    finally:
        conn.close()


def _fetch_order_count(db_path: Path, customer_id: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def _select_archetype(segment: str, has_orders: bool) -> Archetype:
    candidates = []
    for archetype in ARCHETYPES:
        if archetype.segment_filter and archetype.segment_filter != segment:
            continue
        if archetype.requires_verification and not has_orders:
            continue
        candidates.append(archetype)

    if not candidates:
        candidates = [archetype for archetype in ARCHETYPES if not archetype.requires_verification]

    if segment == "Enterprise":
        weights = [2.5 if "enterprise" in archetype.tags else 1.0 for archetype in candidates]
    else:
        weights = [1.0 for _ in candidates]

    return random.choices(candidates, weights=weights, k=1)[0]


def _pick_sentiment(archetype: Archetype) -> str:
    return random.choices(
        ["neutral", "positive", "negative"],
        weights=archetype.sentiment_weights,
        k=1,
    )[0]


def _format_orders(orders: list[dict]) -> str:
    if not orders:
        return "No recent orders."
    return "\n".join(
        f"  {order['order_id']} ({order['status']}, {order['order_date']}): {order['products']}"
        for order in orders
    )


async def _generate_opening_query(
    llm,
    customer: dict,
    orders: list[dict],
    order_count: int,
    archetype: Archetype,
    sentiment: str,
) -> str:
    prompt = f"""You are generating a realistic customer support opening message for Liorin, an enterprise technical-product and after-sales support platform.

CUSTOMER: {customer['name']}, {customer['segment']} segment, {order_count} total orders
RECENT ORDERS:
{_format_orders(orders)}

CONVERSATION TYPE: {archetype.description}
TONE: {sentiment}
HINT: {archetype.hint}

Generate a single realistic 1-3 sentence opening message. Reference specific order history when relevant. Match the communication style for a {customer['segment']} customer with {sentiment} sentiment. Do not include preamble or quotation marks.

Your response:"""

    response = await llm.ainvoke(prompt, config={"run_name": "SimulatedHumanUser"})
    return response.content.strip().strip('"').strip("'")


async def generate_dynamic_scenario(db_path: Path, llm) -> dict:
    """Generate a run_scenario-compatible dynamic scenario."""
    customer = _fetch_customer(db_path)
    orders = _fetch_recent_orders(db_path, customer["customer_id"])
    order_count = _fetch_order_count(db_path, customer["customer_id"])
    archetype = _select_archetype(customer["segment"], has_orders=order_count > 0)
    sentiment = _pick_sentiment(archetype)

    initial_query = await _generate_opening_query(
        llm=llm,
        customer=customer,
        orders=orders,
        order_count=order_count,
        archetype=archetype,
        sentiment=sentiment,
    )

    hash_input = f"{archetype.archetype_id}_{customer['customer_id']}_{initial_query[:30]}"
    short_hash = hashlib.md5(hash_input.encode()).hexdigest()[:6]
    communication_style = COMMUNICATION_STYLES.get(
        (customer["segment"], sentiment),
        "Direct and conversational",
    )

    return {
        "scenario_id": f"dynamic_{archetype.archetype_id}_{customer['customer_id']}_{short_hash}",
        "customer": {
            "email": customer["email"],
            "name": customer["name"],
            "customer_id": customer["customer_id"],
            "segment": customer["segment"],
        },
        "persona": {
            "description": f"{customer['segment']} customer. {archetype.description}",
            "communication_style": communication_style,
            "sentiment": sentiment,
            "typical_queries": archetype.typical_queries,
        },
        "initial_query": initial_query,
        "requires_verification": archetype.requires_verification,
        "tags": archetype.tags
        + [f"segment:{customer['segment']}", "dynamic", f"archetype:{archetype.archetype_id}"],
        "_archetype_id": archetype.archetype_id,
    }
