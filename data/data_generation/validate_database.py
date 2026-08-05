#!/usr/bin/env python3
"""Validate the Liorin SQLite database."""

import sqlite3
import sys
import time
import calendar
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "structured"
DB_PATH = DATA_DIR / "liorin.db"
CURRENT_DATE = date(2026, 8, 4)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _count(cursor: sqlite3.Cursor, table: str) -> int:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    return cursor.fetchone()[0]


def validate_database() -> None:
    conn = _connect()
    cursor = conn.cursor()

    expected_minimums = {
        "customers": 100,
        "products": 1,
        "orders": 1000,
        "order_status_events": 1000,
        "order_items": 100,
        "tickets": 100,
        "ticket_events": 100,
        "warranty_cases": 100,
    }

    print("Liorin database validation")
    print("=" * 60)
    print(f"Database: {DB_PATH}")

    for table, minimum in expected_minimums.items():
        count = _count(cursor, table)
        print(f"{table}: {count}")
        if count < minimum:
            raise AssertionError(f"{table} has {count} rows, expected at least {minimum}")

    cursor.execute("PRAGMA foreign_key_check")
    violations = cursor.fetchall()
    if violations:
        raise AssertionError(f"Foreign key violations: {violations}")
    print("Foreign keys: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM orders o
        WHERE ABS(
            o.total_amount - COALESCE((
                SELECT ROUND(SUM(oi.quantity * oi.price_per_unit), 2)
                FROM order_items oi
                WHERE oi.order_id = o.order_id
            ), 0)
        ) > 0.02
        """
    )
    mismatched_totals = cursor.fetchone()[0]
    if mismatched_totals:
        raise AssertionError(f"Orders with mismatched totals: {mismatched_totals}")
    print("Order totals: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM orders
        WHERE substr(order_id, 5, 4) != substr(order_date, 1, 4)
        """
    )
    invalid_order_years = cursor.fetchone()[0]
    if invalid_order_years:
        raise AssertionError(f"Order IDs with year/date mismatch: {invalid_order_years}")
    print("Order ID years: ok")

    cursor.execute("SELECT COUNT(*) FROM orders WHERE order_date > ?", (CURRENT_DATE.isoformat(),))
    future_orders = cursor.fetchone()[0]
    if future_orders:
        raise AssertionError(f"Orders created in the future: {future_orders}")
    print("Future order dates: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM order_status_events ose
        JOIN orders o ON o.order_id = ose.order_id
        WHERE ose.happened_at < o.order_date OR ose.happened_at > ?
        """,
        (CURRENT_DATE.isoformat(),),
    )
    invalid_order_events = cursor.fetchone()[0]
    if invalid_order_events:
        raise AssertionError(f"Order status events outside valid date range: {invalid_order_events}")
    print("Order status event dates: ok")

    cursor.execute(
        """
        WITH latest AS (
            SELECT order_id, status
            FROM (
                SELECT
                    order_id,
                    status,
                    ROW_NUMBER() OVER (
                        PARTITION BY order_id
                        ORDER BY happened_at DESC, event_id DESC
                    ) AS rn
                FROM order_status_events
            )
            WHERE rn = 1
        )
        SELECT COUNT(*)
        FROM orders o
        JOIN latest l ON l.order_id = o.order_id
        WHERE lower(o.status) != l.status
        """
    )
    mismatched_order_event_status = cursor.fetchone()[0]
    if mismatched_order_event_status:
        raise AssertionError(f"Orders whose latest event does not match status: {mismatched_order_event_status}")
    print("Order latest status events: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM products p
        WHERE NOT EXISTS (
            SELECT 1 FROM order_items oi WHERE oi.product_id = p.product_id
        )
        """
    )
    products_without_orders = cursor.fetchone()[0]
    print(f"Products without orders: {products_without_orders}")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM orders
        WHERE status = 'Cancelled'
          AND (cancel_reason IS NULL OR tracking_number IS NOT NULL)
        """
    )
    invalid_cancelled_orders = cursor.fetchone()[0]
    if invalid_cancelled_orders:
        raise AssertionError(f"Cancelled orders with invalid reason/tracking: {invalid_cancelled_orders}")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM orders o
        WHERE o.status = 'Cancelled'
          AND NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id = o.order_id)
        """
    )
    cancelled_without_items = cursor.fetchone()[0]
    if cancelled_without_items:
        raise AssertionError(f"Cancelled orders without line items: {cancelled_without_items}")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM orders
        WHERE status != 'Cancelled' AND cancel_reason IS NOT NULL
        """
    )
    non_cancelled_with_reason = cursor.fetchone()[0]
    if non_cancelled_with_reason:
        raise AssertionError(f"Non-cancelled orders with cancel reason: {non_cancelled_with_reason}")
    print("Cancelled order semantics: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT order_id, product_id
            FROM order_items
            GROUP BY order_id, product_id
            HAVING COUNT(*) > 1
        )
        """
    )
    duplicate_order_skus = cursor.fetchone()[0]
    if duplicate_order_skus:
        raise AssertionError(f"Orders with duplicate SKU rows: {duplicate_order_skus}")
    print("Duplicate order SKU rows: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        JOIN customers c ON c.customer_id = o.customer_id
        JOIN products p ON p.product_id = oi.product_id
        WHERE c.segment = 'Consumer'
          AND p.category IN (
              'marine_vehicle', 'kids_vehicle', 'power_equipment', 'water_system',
              'major_appliance', 'hvac'
          )
          AND oi.quantity > 2
        """
    )
    consumer_low_volume_bulk = cursor.fetchone()[0]
    if consumer_low_volume_bulk:
        raise AssertionError(f"Consumer low-volume items with quantity > 2: {consumer_low_volume_bulk}")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        WHERE p.category = 'marine_vehicle' AND oi.quantity > 2
        """
    )
    marine_bulk = cursor.fetchone()[0]
    if marine_bulk:
        raise AssertionError(f"Marine vehicle items with quantity > 2: {marine_bulk}")
    print("Product quantity semantics: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM tickets t
        JOIN orders o ON o.order_id = t.order_id
        WHERE t.created_at < o.order_date
        """
    )
    tickets_before_orders = cursor.fetchone()[0]
    if tickets_before_orders:
        raise AssertionError(f"Tickets created before order date: {tickets_before_orders}")
    print("Ticket dates: ok")

    cursor.execute("SELECT COUNT(*) FROM tickets WHERE created_at > ?", (CURRENT_DATE.isoformat(),))
    future_tickets = cursor.fetchone()[0]
    if future_tickets:
        raise AssertionError(f"Tickets created in the future: {future_tickets}")
    print("Future ticket dates: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM ticket_events te
        JOIN tickets t ON t.ticket_id = te.ticket_id
        WHERE te.happened_at < t.created_at OR te.happened_at > ?
        """,
        (CURRENT_DATE.isoformat(),),
    )
    invalid_ticket_events = cursor.fetchone()[0]
    if invalid_ticket_events:
        raise AssertionError(f"Ticket events outside valid date range: {invalid_ticket_events}")
    print("Ticket event dates: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM ticket_events current
        JOIN ticket_events previous
          ON previous.ticket_id = current.ticket_id
         AND previous.event_id < current.event_id
        WHERE previous.happened_at > current.happened_at
        """
    )
    ticket_event_time_reversals = cursor.fetchone()[0]
    if ticket_event_time_reversals:
        raise AssertionError(f"Ticket event time reversals: {ticket_event_time_reversals}")
    print("Ticket event order: ok")

    cursor.execute(
        """
        WITH latest AS (
            SELECT ticket_id, event_type
            FROM (
                SELECT
                    ticket_id,
                    event_type,
                    ROW_NUMBER() OVER (
                        PARTITION BY ticket_id
                        ORDER BY happened_at DESC, event_id DESC
                    ) AS rn
                FROM ticket_events
            )
            WHERE rn = 1
        )
        SELECT COUNT(*)
        FROM tickets t
        JOIN latest l ON l.ticket_id = t.ticket_id
        WHERE (t.status = 'resolved' AND l.event_type != 'resolved')
           OR (t.status = 'pending_customer' AND l.event_type != 'pending_customer')
           OR (t.status = 'in_progress' AND l.event_type NOT IN ('assigned', 'first_response'))
           OR (t.status = 'open' AND l.event_type != 'created')
        """
    )
    mismatched_ticket_event_status = cursor.fetchone()[0]
    if mismatched_ticket_event_status:
        raise AssertionError(
            f"Tickets whose latest event does not match status: {mismatched_ticket_event_status}"
        )
    print("Ticket latest status events: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM tickets child
        JOIN tickets parent ON parent.ticket_id = child.parent_ticket_id
        WHERE child.created_at <= parent.created_at
        """
    )
    invalid_parent_dates = cursor.fetchone()[0]
    if invalid_parent_dates:
        raise AssertionError(f"Child tickets earlier than parent: {invalid_parent_dates}")
    print("Parent ticket dates: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT order_id, product_id, issue_type
            FROM tickets
            WHERE parent_ticket_id IS NULL
              AND order_id IS NOT NULL
            GROUP BY order_id, product_id, issue_type
            HAVING COUNT(*) > 1
        )
        """
    )
    duplicate_root_tickets = cursor.fetchone()[0]
    if duplicate_root_tickets:
        raise AssertionError(f"Duplicate root tickets for same order/product/issue: {duplicate_root_tickets}")
    print("Duplicate root tickets: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM warranty_cases w
        LEFT JOIN tickets t ON t.ticket_id = w.ticket_id
        WHERE t.ticket_id IS NULL
        """
    )
    orphaned_warranty_tickets = cursor.fetchone()[0]
    if orphaned_warranty_tickets:
        raise AssertionError(f"Warranty cases without source ticket: {orphaned_warranty_tickets}")
    print("Warranty source tickets: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT ticket_id
            FROM warranty_cases
            GROUP BY ticket_id
            HAVING COUNT(*) > 1
        )
        """
    )
    duplicate_warranty_tickets = cursor.fetchone()[0]
    if duplicate_warranty_tickets:
        raise AssertionError(f"Tickets with duplicate warranty cases: {duplicate_warranty_tickets}")
    print("Duplicate warranty tickets: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM warranty_cases w
        JOIN tickets t ON t.ticket_id = w.ticket_id
        WHERE t.parent_ticket_id IS NOT NULL
        """
    )
    warranty_from_child_tickets = cursor.fetchone()[0]
    if warranty_from_child_tickets:
        raise AssertionError(f"Warranty cases created from child tickets: {warranty_from_child_tickets}")
    print("Warranty root tickets: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT t.order_id, t.product_id, t.issue_type
            FROM warranty_cases w
            JOIN tickets t ON t.ticket_id = w.ticket_id
            GROUP BY t.order_id, t.product_id, t.issue_type
            HAVING COUNT(*) > 1
        )
        """
    )
    duplicate_warranty_incidents = cursor.fetchone()[0]
    if duplicate_warranty_incidents:
        raise AssertionError(f"Warranty cases sharing same incident: {duplicate_warranty_incidents}")
    print("Warranty incident uniqueness: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM warranty_cases
        WHERE status = 'expired' AND expires_at >= ?
        """,
        (CURRENT_DATE.isoformat(),),
    )
    invalid_expired = cursor.fetchone()[0]
    if invalid_expired:
        raise AssertionError(f"Expired warranty cases with future expiry: {invalid_expired}")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM warranty_cases
        WHERE status IN ('active', 'under_review') AND expires_at < ?
        """,
        (CURRENT_DATE.isoformat(),),
    )
    invalid_active = cursor.fetchone()[0]
    if invalid_active:
        raise AssertionError(f"Active warranty cases past expiry: {invalid_active}")
    print("Warranty status/date causality: ok")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM warranty_cases
        WHERE (coverage_status = 'expired' AND expires_at >= ?)
           OR (coverage_status = 'in_warranty' AND expires_at < ?)
        """,
        (CURRENT_DATE.isoformat(), CURRENT_DATE.isoformat()),
    )
    invalid_coverage_status = cursor.fetchone()[0]
    if invalid_coverage_status:
        raise AssertionError(f"Warranty coverage status/date mismatch: {invalid_coverage_status}")
    print("Warranty coverage status/date causality: ok")

    cursor.execute(
        """
        SELECT w.case_id, o.order_date, p.warranty_months, w.expires_at
        FROM warranty_cases w
        JOIN orders o ON o.order_id = w.order_id
        JOIN products p ON p.product_id = w.product_id
        WHERE w.coverage_type = 'extended_warranty'
        """
    )
    invalid_extended = []
    for case_id, order_date, base_months, expires_at in cursor.fetchall():
        expected = _add_months(date.fromisoformat(order_date), base_months + 12)
        if date.fromisoformat(expires_at) != expected:
            invalid_extended.append(case_id)
    if invalid_extended:
        raise AssertionError(f"Extended warranty expiry mismatch: {invalid_extended[:5]}")
    print("Extended warranty expiry: ok")

    sample_queries = [
        ("customer lookup", "SELECT * FROM customers WHERE email LIKE '%@%' LIMIT 1"),
        ("order lookup", "SELECT * FROM orders ORDER BY order_date DESC LIMIT 5"),
        (
            "ticket context",
            """
            SELECT t.ticket_id, c.email, p.name, t.status
            FROM tickets t
            JOIN customers c ON c.customer_id = t.customer_id
            JOIN products p ON p.product_id = t.product_id
            LIMIT 5
            """,
        ),
        (
            "warranty context",
            """
            SELECT w.case_id, c.email, p.name, w.status, w.coverage_status, w.expires_at
            FROM warranty_cases w
            JOIN customers c ON c.customer_id = w.customer_id
            JOIN products p ON p.product_id = w.product_id
            LIMIT 5
            """,
        ),
    ]

    for name, query in sample_queries:
        start = time.perf_counter()
        cursor.execute(query)
        cursor.fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"{name}: {elapsed_ms:.2f}ms")

    conn.close()
    print("Validation passed")


if __name__ == "__main__":
    try:
        validate_database()
    except Exception as exc:
        print(f"Validation failed: {exc}")
        sys.exit(1)
