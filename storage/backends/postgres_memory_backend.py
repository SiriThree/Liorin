"""PostgreSQL MemoryBackend with transactional lifecycle outbox.

The adapter accepts a DB-API connection factory. Production uses psycopg;
tests can use sqlite through ``dialect='sqlite'`` without changing runtime code.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from identity import IdentityContext
from memory.facts.models import MemoryFact, canonical_value
from storage.backends._dbapi import DBAPIAdapter, safe_identifier


def psycopg_connection_factory(dsn: str) -> Callable[[], Any]:
    def connect() -> Any:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg[binary] is required for PostgreSQL storage") from exc
        return psycopg.connect(dsn)
    return connect


def sqlite_connection_factory(path: str | Path) -> Callable[[], Any]:
    def connect() -> Any:
        import sqlite3
        return sqlite3.connect(str(path))
    return connect


def _terms(value: str) -> set[str]:
    normalized = "".join(char.casefold() if char.isalnum() else " " for char in value)
    tokens = {token for token in normalized.split() if token}
    tokens.update(char for char in value if "\u4e00" <= char <= "\u9fff")
    return tokens


class PostgresMemoryBackend:
    def __init__(
        self,
        *,
        dsn: str | None = None,
        connection_factory: Callable[[], Any] | None = None,
        schema: str = "liorin",
        dialect: str = "postgres",
        auto_migrate: bool = True,
    ) -> None:
        if connection_factory is None:
            if not dsn:
                raise ValueError("dsn or connection_factory is required")
            connection_factory = psycopg_connection_factory(dsn)
        self.schema = safe_identifier(schema)
        self.db = DBAPIAdapter(connection_factory, dialect=dialect)
        prefix = f"{self.schema}." if dialect == "postgres" else f"{self.schema}_"
        self.fact_table = f"{prefix}memory_facts"
        self.audit_table = f"{prefix}memory_lifecycle_outbox"
        if auto_migrate:
            self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.db.transaction() as cursor:
            if self.db.dialect == "postgres":
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
                json_type, timestamp_type = "JSONB", "TIMESTAMPTZ"
            else:
                json_type, timestamp_type = "TEXT", "TEXT"
            cursor.execute(
                f"""CREATE TABLE IF NOT EXISTS {self.fact_table} (
                    fact_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_json {json_type} NOT NULL,
                    updated_at {timestamp_type} NOT NULL,
                    expires_at {timestamp_type} NULL
                )"""
            )
            cursor.execute(
                f"""CREATE TABLE IF NOT EXISTS {self.audit_table} (
                    outbox_id TEXT PRIMARY KEY,
                    fact_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    record_json {json_type} NOT NULL,
                    created_at {timestamp_type} NOT NULL,
                    published_at {timestamp_type} NULL
                )"""
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.schema}_memory_owner ON {self.fact_table} (tenant_id, user_id, fact_key)"
            )

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _load(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)

    def _write_fact(self, cursor: Any, fact: MemoryFact, *, update: bool) -> None:
        payload = self._dump(fact.to_state())
        expires_at = fact.expires_at.isoformat() if fact.expires_at else None
        if update:
            statement = f"""UPDATE {self.fact_table}
                SET fact_json=%s, updated_at=%s, expires_at=%s
                WHERE fact_id=%s AND tenant_id=%s AND user_id=%s"""
            params = (payload, fact.updated_at.isoformat(), expires_at, fact.fact_id, fact.identity_context.tenant_id, fact.identity_context.user_id)
        else:
            statement = f"""INSERT INTO {self.fact_table}
                (fact_id, tenant_id, user_id, fact_key, fact_json, updated_at, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)"""
            params = (fact.fact_id, fact.identity_context.tenant_id, fact.identity_context.user_id, fact.key, payload, fact.updated_at.isoformat(), expires_at)
        cursor.execute(self.db.sql(statement), params)
        if update and getattr(cursor, "rowcount", 1) == 0:
            raise KeyError(f"MemoryFact not found: {fact.fact_id}")

    def _write_audit(self, cursor: Any, record: Any) -> None:
        state = record.to_state() if hasattr(record, "to_state") else dict(record)
        memory = state.get("memory") or {}
        identity = state.get("identity_context") or {}
        occurred_at = state.get("occurred_at") or datetime.now(timezone.utc).isoformat()
        outbox_id = f"{memory.get('id')}:{state.get('event')}:{occurred_at}"
        statement = f"""INSERT INTO {self.audit_table}
            (outbox_id, fact_id, tenant_id, user_id, event, record_json, created_at, published_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"""
        cursor.execute(self.db.sql(statement), (
            outbox_id, memory.get("id"), identity.get("tenant_id"), identity.get("user_id"),
            state.get("event"), self._dump(state), occurred_at, None,
        ))

    def save_fact(self, fact: MemoryFact) -> MemoryFact:
        with self.db.transaction() as cursor:
            self._write_fact(cursor, fact, update=False)
        return fact

    def save_fact_with_audit(self, fact: MemoryFact, audit_record: Any) -> MemoryFact:
        with self.db.transaction() as cursor:
            self._write_fact(cursor, fact, update=False)
            self._write_audit(cursor, audit_record)
        return fact

    def update_fact(self, fact: MemoryFact) -> MemoryFact:
        with self.db.transaction() as cursor:
            self._write_fact(cursor, fact, update=True)
        return fact

    def update_fact_with_audit(self, fact: MemoryFact, audit_record: Any) -> MemoryFact:
        with self.db.transaction() as cursor:
            self._write_fact(cursor, fact, update=True)
            self._write_audit(cursor, audit_record)
        return fact

    def get_fact(self, fact_id: str, *, identity_context: IdentityContext) -> MemoryFact:
        statement = f"SELECT fact_json FROM {self.fact_table} WHERE fact_id=%s AND tenant_id=%s AND user_id=%s"
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(statement), (fact_id, identity_context.tenant_id, identity_context.user_id))
            row = cursor.fetchone()
        if row is None:
            raise KeyError(f"MemoryFact not found: {fact_id}")
        return MemoryFact.from_state(self._load(row[0]))

    def delete_fact(self, fact_id: str, *, identity_context: IdentityContext) -> MemoryFact:
        fact = self.get_fact(fact_id, identity_context=identity_context)
        statement = f"DELETE FROM {self.fact_table} WHERE fact_id=%s AND tenant_id=%s AND user_id=%s"
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(statement), (fact_id, identity_context.tenant_id, identity_context.user_id))
        return fact

    def delete_fact_with_audit(self, fact_id: str, *, identity_context: IdentityContext, audit_record: Any) -> MemoryFact:
        fact = self.get_fact(fact_id, identity_context=identity_context)
        statement = f"DELETE FROM {self.fact_table} WHERE fact_id=%s AND tenant_id=%s AND user_id=%s"
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(statement), (fact_id, identity_context.tenant_id, identity_context.user_id))
            self._write_audit(cursor, audit_record)
        return fact

    def _owner_rows(self, identity_context: IdentityContext) -> list[MemoryFact]:
        statement = f"SELECT fact_json FROM {self.fact_table} WHERE tenant_id=%s AND user_id=%s"
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(statement), (identity_context.tenant_id, identity_context.user_id))
            rows = cursor.fetchall()
        return [MemoryFact.from_state(self._load(row[0])) for row in rows]

    def search_fact(
        self, *, identity_context: IdentityContext, query: str, keys: Iterable[str] = (),
        limit: int = 8, now: datetime | None = None, include_expired: bool = False,
    ) -> list[MemoryFact]:
        if limit <= 0:
            return []
        now = now or datetime.now(timezone.utc)
        requested_keys = {str(key).strip().casefold() for key in keys if str(key).strip()}
        query_terms = _terms(str(query or ""))
        ranked: list[tuple[float, MemoryFact]] = []
        for fact in self._owner_rows(identity_context):
            if fact.is_expired(now=now) and not include_expired:
                continue
            score = 0.0
            if fact.key.casefold() in requested_keys:
                score += 20.0
            score += 4.0 * len(query_terms & _terms(fact.key.replace("_", " ")))
            score += 1.5 * len(query_terms & _terms(canonical_value(fact.value)))
            if score:
                score += fact.confidence + (1.0 if fact.verified else 0.0)
                ranked.append((score, fact))
        ranked.sort(key=lambda item: (-item[0], -int(item[1].verified), -item[1].confidence, item[1].fact_id))
        return [fact for _, fact in ranked[:limit]]

    def list_facts(
        self, *, identity_context: IdentityContext | None = None, tenant_id: str | None = None,
        include_expired: bool = True, now: datetime | None = None,
    ) -> list[MemoryFact]:
        conditions, params = [], []
        if identity_context is not None:
            conditions.extend(["tenant_id=%s", "user_id=%s"])
            params.extend([identity_context.tenant_id, identity_context.user_id])
        elif tenant_id is not None:
            conditions.append("tenant_id=%s")
            params.append(tenant_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(f"SELECT fact_json FROM {self.fact_table}{where}"), tuple(params))
            rows = cursor.fetchall()
        now = now or datetime.now(timezone.utc)
        facts = [MemoryFact.from_state(self._load(row[0])) for row in rows]
        if not include_expired:
            facts = [fact for fact in facts if not fact.is_expired(now=now)]
        return sorted(facts, key=lambda fact: (fact.identity_context.tenant_id, fact.identity_context.user_id, fact.key, fact.fact_id))

    def pending_audit_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(f"SELECT record_json FROM {self.audit_table} WHERE published_at IS NULL ORDER BY created_at LIMIT %s"), (limit,))
            rows = cursor.fetchall()
        return [self._load(row[0]) for row in rows]
