#!/usr/bin/env python3
"""Validate the Liorin SQLite database."""

import sqlite3
import sys
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "structured"
DB_PATH = DATA_DIR / "liorin.db"


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
        "customers": 1,
        "products": 1,
        "orders": 1,
        "order_items": 1,
        "tickets": 1,
        "warranty_cases": 1,
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
        FROM products p
        WHERE NOT EXISTS (
            SELECT 1 FROM order_items oi WHERE oi.product_id = p.product_id
        )
        """
    )
    products_without_orders = cursor.fetchone()[0]
    print(f"Products without orders: {products_without_orders}")

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
            SELECT w.case_id, c.email, p.name, w.status, w.expires_at
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
