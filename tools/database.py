"""Principal-bound, fixed-template, read-only database tools for Liorin agents."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sqlite3
from contextlib import closing
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_community.utilities import SQLDatabase

from config import DEFAULT_DB_PATH
from retrieval.security import redact_text

MAX_RESULT_ROWS = 100
MAX_SQL_VM_STEPS = 1_000_000
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")
_EMAIL = re.compile(r"(?i)^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$")

_db = None


@dataclass(frozen=True)
class SafeSQLTemplate:
    template_id: str
    sql: str
    parameter_order: tuple[str, ...]
    description: str


SQL_TEMPLATES: dict[str, SafeSQLTemplate] = {
    "customer_summary": SafeSQLTemplate(
        "customer_summary",
        "SELECT customer_id, name, segment, company_name, source_system FROM customers "
        "WHERE tenant_id=? AND customer_id=? LIMIT ?",
        ("tenant_id", "customer_id", "limit"),
        "已验证租户内客户的基础资料，不返回邮箱、电话或地址。",
    ),
    "customer_orders": SafeSQLTemplate(
        "customer_orders",
        "SELECT o.order_id, o.status, o.order_date, o.total_amount, o.channel FROM orders o "
        "JOIN customers c ON c.customer_id=o.customer_id "
        "WHERE c.tenant_id=? AND o.customer_id=? ORDER BY o.order_date DESC LIMIT ?",
        ("tenant_id", "customer_id", "limit"),
        "已验证租户内客户的订单列表。",
    ),
    "order_detail": SafeSQLTemplate(
        "order_detail",
        "SELECT o.order_id, o.status, o.order_date, o.total_amount, o.channel, i.product_id, "
        "p.name AS product_name, i.quantity, i.price_per_unit FROM orders o "
        "JOIN customers c ON c.customer_id=o.customer_id "
        "JOIN order_items i ON i.order_id=o.order_id "
        "JOIN products p ON p.product_id=i.product_id "
        "WHERE c.tenant_id=? AND o.customer_id=? AND o.order_id=? "
        "ORDER BY i.product_id LIMIT ?",
        ("tenant_id", "customer_id", "entity_id", "limit"),
        "已验证租户内客户名下某一订单及商品明细。",
    ),
    "order_events": SafeSQLTemplate(
        "order_events",
        "SELECT e.order_id, e.status, e.happened_at, e.actor, e.note FROM order_status_events e "
        "JOIN orders o ON o.order_id=e.order_id "
        "JOIN customers c ON c.customer_id=o.customer_id "
        "WHERE c.tenant_id=? AND o.customer_id=? AND e.order_id=? "
        "ORDER BY e.happened_at LIMIT ?",
        ("tenant_id", "customer_id", "entity_id", "limit"),
        "已验证租户内客户名下订单生命周期。",
    ),
    "customer_tickets": SafeSQLTemplate(
        "customer_tickets",
        "SELECT t.ticket_id, t.order_id, t.product_id, t.status, t.priority, t.issue_type, t.created_at "
        "FROM tickets t JOIN customers c ON c.customer_id=t.customer_id "
        "WHERE c.tenant_id=? AND t.customer_id=? ORDER BY t.created_at DESC LIMIT ?",
        ("tenant_id", "customer_id", "limit"),
        "已验证租户内客户的工单列表。",
    ),
    "ticket_detail": SafeSQLTemplate(
        "ticket_detail",
        "SELECT t.ticket_id, t.order_id, t.product_id, t.status, t.priority, t.issue_type, "
        "t.summary, t.created_at, t.assigned_team FROM tickets t "
        "JOIN customers c ON c.customer_id=t.customer_id "
        "WHERE c.tenant_id=? AND t.customer_id=? AND t.ticket_id=? LIMIT ?",
        ("tenant_id", "customer_id", "entity_id", "limit"),
        "已验证租户内客户名下单个工单。",
    ),
    "ticket_events": SafeSQLTemplate(
        "ticket_events",
        "SELECT e.ticket_id, e.event_type, e.happened_at, e.actor, e.note FROM ticket_events e "
        "JOIN tickets t ON t.ticket_id=e.ticket_id "
        "JOIN customers c ON c.customer_id=t.customer_id "
        "WHERE c.tenant_id=? AND t.customer_id=? AND e.ticket_id=? "
        "ORDER BY e.happened_at LIMIT ?",
        ("tenant_id", "customer_id", "entity_id", "limit"),
        "已验证租户内客户名下工单生命周期。",
    ),
    "warranty_cases": SafeSQLTemplate(
        "warranty_cases",
        "SELECT w.case_id, w.ticket_id, w.order_id, w.product_id, w.coverage_type, "
        "w.coverage_status, w.status, w.expires_at FROM warranty_cases w "
        "JOIN customers c ON c.customer_id=w.customer_id "
        "WHERE c.tenant_id=? AND w.customer_id=? ORDER BY w.expires_at DESC LIMIT ?",
        ("tenant_id", "customer_id", "limit"),
        "已验证租户内客户的质保案例。",
    ),
}


def get_database() -> SQLDatabase:
    """Return schema-introspection database; agent data reads use fixed templates."""
    global _db
    if _db is None:
        _db = SQLDatabase.from_uri(f"sqlite:///{DEFAULT_DB_PATH}")
    return _db


def _readonly_authorizer(action_code, _param1, _param2, _db_name, _trigger_name):
    allowed_actions = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    if hasattr(sqlite3, "SQLITE_RECURSIVE"):
        allowed_actions.add(sqlite3.SQLITE_RECURSIVE)
    return sqlite3.SQLITE_OK if action_code in allowed_actions else sqlite3.SQLITE_DENY


def _open_readonly_connection(*, timeout_seconds: float = 0.5) -> sqlite3.Connection:
    db_uri = DEFAULT_DB_PATH.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=timeout_seconds)
    conn.row_factory = sqlite3.Row
    # Configure query-only mode before installing the strict authorizer; PRAGMA
    # itself is intentionally denied after initialization.
    conn.execute("PRAGMA query_only=ON")
    conn.set_authorizer(_readonly_authorizer)
    conn.set_progress_handler(lambda: 1, MAX_SQL_VM_STEPS)
    return conn


def _validate_identifier(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise ValueError(f"invalid {field}")
    return text


def lookup_customer_by_email(email: str) -> tuple[str, str, str] | None:
    """Parameterised identity lookup used before principal construction."""
    normalized = str(email or "").strip().casefold()
    if not _EMAIL.fullmatch(normalized):
        return None
    with closing(_open_readonly_connection()) as connection:
        row = connection.execute(
            "SELECT customer_id, name, tenant_id FROM customers WHERE lower(email)=? LIMIT 1",
            (normalized,),
        ).fetchone()
    return (str(row["customer_id"]), str(row["name"]), str(row["tenant_id"])) if row else None


def execute_template(
    template_id: str,
    *,
    tenant_id: str,
    customer_id: str,
    entity_id: str | None = None,
    max_rows: int = MAX_RESULT_ROWS,
) -> list[dict[str, Any]]:
    """Execute one allow-listed SQL template with bound tenant and owner conditions."""
    template = SQL_TEMPLATES.get(str(template_id))
    if template is None:
        raise ValueError("unknown SQL template")
    tenant = _validate_identifier(tenant_id, "tenant_id")
    customer = _validate_identifier(customer_id, "customer_id")
    entity = _validate_identifier(entity_id, "entity_id") if "entity_id" in template.parameter_order else None
    limit = max(1, min(int(max_rows), MAX_RESULT_ROWS))
    values = {
        "tenant_id": tenant,
        "customer_id": customer,
        "entity_id": entity,
        "limit": limit + 1,
    }
    parameters = tuple(values[name] for name in template.parameter_order)
    with closing(_open_readonly_connection()) as connection:
        rows = connection.execute(template.sql, parameters).fetchmany(limit + 1)
    output = [dict(row) for row in rows[:limit]]
    if len(rows) > limit:
        output.append({"_truncated": True, "max_rows": limit})
    return output


@tool
def execute_sql_template(
    template_id: str,
    runtime: ToolRuntime,
    entity_id: str | None = None,
) -> str:
    """执行固定只读 SQL 模板；租户与客户身份由运行时状态注入。"""
    state = getattr(runtime, "state", {})
    customer_id = state.get("customer_id") if isinstance(state, dict) else None
    tenant_id = state.get("tenant_id") if isinstance(state, dict) else None
    if not customer_id or not tenant_id:
        return "结构化查询被拒绝：当前工具运行时没有已验证的租户与客户身份。"
    try:
        rows = execute_template(
            template_id,
            tenant_id=str(tenant_id),
            customer_id=str(customer_id),
            entity_id=entity_id,
        )
    except (ValueError, sqlite3.DatabaseError) as exc:
        return f"结构化查询失败：{type(exc).__name__}"
    # Selected fields contain no email/phone/address. Redaction remains defense in depth.
    return redact_text(json.dumps(rows, ensure_ascii=False), keep_business_ids=True, limit=12_000)


@tool
def execute_sql(query: str) -> str:
    """Legacy arbitrary SQL entrypoint retained only to fail closed."""
    return (
        "任意 SQL 工具已因企业安全策略停用。"
        "请使用 execute_sql_template 的固定模板，不得提交自由 SQL。"
    )
