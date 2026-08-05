#!/usr/bin/env python3
"""Create the Liorin SQLite database from structured JSON files."""

import json
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "structured"
DB_PATH = DATA_DIR / "liorin.db"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    segment TEXT NOT NULL,
    activity_score REAL NOT NULL CHECK(activity_score > 0),
    phone TEXT,
    company_name TEXT,
    source_system TEXT
);

CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    manual_file TEXT NOT NULL,
    source_file TEXT,
    category TEXT NOT NULL,
    warranty_months INTEGER NOT NULL,
    price REAL NOT NULL CHECK(price >= 0),
    currently_in_stock INTEGER NOT NULL CHECK(currently_in_stock IN (0, 1))
);

CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_date TEXT NOT NULL,
    status TEXT NOT NULL,
    total_amount REAL NOT NULL CHECK(total_amount >= 0),
    tracking_number TEXT,
    cancel_reason TEXT,
    channel TEXT,
    sales_rep TEXT,
    discount_code TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_status_events (
    event_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    status TEXT NOT NULL,
    happened_at TEXT NOT NULL,
    actor TEXT,
    note TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    price_per_unit REAL NOT NULL CHECK(price_per_unit >= 0),
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE tickets (
    ticket_id TEXT PRIMARY KEY,
    parent_ticket_id TEXT,
    customer_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    order_id TEXT,
    issue_type TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    channel TEXT,
    assigned_team TEXT,
    attachments_count INTEGER NOT NULL DEFAULT 0 CHECK(attachments_count >= 0),
    customer_sentiment TEXT,
    FOREIGN KEY (parent_ticket_id) REFERENCES tickets(ticket_id),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE ticket_events (
    event_id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    happened_at TEXT NOT NULL,
    actor TEXT,
    note TEXT,
    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
);

CREATE TABLE warranty_cases (
    case_id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    order_id TEXT,
    status TEXT NOT NULL,
    coverage_type TEXT NOT NULL,
    coverage_status TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_order_status_events_order ON order_status_events(order_id);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);
CREATE INDEX idx_tickets_customer ON tickets(customer_id);
CREATE INDEX idx_tickets_order ON tickets(order_id);
CREATE INDEX idx_tickets_parent ON tickets(parent_ticket_id);
CREATE INDEX idx_ticket_events_ticket ON ticket_events(ticket_id);
CREATE INDEX idx_warranty_cases_customer ON warranty_cases(customer_id);
CREATE INDEX idx_warranty_cases_ticket ON warranty_cases(ticket_id);
"""


def _load_json(name: str):
    with open(DATA_DIR / f"{name}.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _load_json_optional(name: str):
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_database() -> Path:
    """Create liorin.db from JSON source files."""
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()
    cursor.executescript(SCHEMA_SQL)

    customers = _load_json("customers")
    products = _load_json("products")
    orders = _load_json("orders")
    order_items = _load_json("order_items")
    order_status_events = _load_json_optional("order_status_events")
    tickets = _load_json("tickets")
    ticket_events = _load_json_optional("ticket_events")
    warranty_cases = _load_json("warranty_cases")

    cursor.executemany(
        """
        INSERT INTO customers (
            customer_id, email, name, tenant_id, segment, activity_score,
            phone, company_name, source_system
        )
        VALUES (
            :customer_id, :email, :name, :tenant_id, :segment, :activity_score,
            :phone, :company_name, :source_system
        )
        """,
        customers,
    )
    cursor.executemany(
        """
        INSERT INTO products (
            product_id, name, manual_file, source_file, category,
            warranty_months, price, currently_in_stock
        )
        VALUES (
            :product_id, :name, :manual_file, :source_file, :category,
            :warranty_months, :price, :currently_in_stock
        )
        """,
        products,
    )
    cursor.executemany(
        """
        INSERT INTO orders (
            order_id, customer_id, order_date, status, total_amount,
            tracking_number, cancel_reason, channel, sales_rep, discount_code
        )
        VALUES (
            :order_id, :customer_id, :order_date, :status,
            :total_amount, :tracking_number, :cancel_reason,
            :channel, :sales_rep, :discount_code
        )
        """,
        orders,
    )
    cursor.executemany(
        """
        INSERT INTO order_status_events (
            event_id, order_id, status, happened_at, actor, note
        )
        VALUES (
            :event_id, :order_id, :status, :happened_at, :actor, :note
        )
        """,
        order_status_events,
    )
    cursor.executemany(
        """
        INSERT INTO order_items (
            order_item_id, order_id, product_id, quantity, price_per_unit
        )
        VALUES (
            :order_item_id, :order_id, :product_id, :quantity, :price_per_unit
        )
        """,
        order_items,
    )
    cursor.executemany(
        """
        INSERT INTO tickets (
            ticket_id, parent_ticket_id, customer_id, product_id, order_id, issue_type,
            priority, status, created_at, summary, channel, assigned_team,
            attachments_count, customer_sentiment
        )
        VALUES (
            :ticket_id, :parent_ticket_id, :customer_id, :product_id, :order_id, :issue_type,
            :priority, :status, :created_at, :summary, :channel, :assigned_team,
            :attachments_count, :customer_sentiment
        )
        """,
        tickets,
    )
    cursor.executemany(
        """
        INSERT INTO ticket_events (
            event_id, ticket_id, event_type, happened_at, actor, note
        )
        VALUES (
            :event_id, :ticket_id, :event_type, :happened_at, :actor, :note
        )
        """,
        ticket_events,
    )
    cursor.executemany(
        """
        INSERT INTO warranty_cases (
            case_id, ticket_id, customer_id, product_id, order_id, status,
            coverage_type, coverage_status, expires_at
        )
        VALUES (
            :case_id, :ticket_id, :customer_id, :product_id, :order_id,
            :status, :coverage_type, :coverage_status, :expires_at
        )
        """,
        warranty_cases,
    )

    conn.commit()
    conn.close()
    print(f"Created database: {DB_PATH}")
    return DB_PATH


if __name__ == "__main__":
    create_database()
