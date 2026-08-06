"""PostgreSQL ArtifactBackend storing metadata and payload as JSONB."""
from __future__ import annotations

import json
from typing import Any, Callable

from artifact import Artifact, ArtifactLifecycleState, ArtifactType
from identity import IdentityContext
from storage.backends._dbapi import DBAPIAdapter, safe_identifier
from storage.backends.postgres_memory_backend import psycopg_connection_factory


class PostgresArtifactBackend:
    def __init__(
        self, *, dsn: str | None = None, connection_factory: Callable[[], Any] | None = None,
        schema: str = "liorin", dialect: str = "postgres", auto_migrate: bool = True,
    ) -> None:
        if connection_factory is None:
            if not dsn:
                raise ValueError("dsn or connection_factory is required")
            connection_factory = psycopg_connection_factory(dsn)
        self.schema = safe_identifier(schema)
        self.db = DBAPIAdapter(connection_factory, dialect=dialect)
        prefix = f"{self.schema}." if dialect == "postgres" else f"{self.schema}_"
        self.table = f"{prefix}artifacts"
        if auto_migrate:
            self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.db.transaction() as cursor:
            if self.db.dialect == "postgres":
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
                json_type, timestamp_type = "JSONB", "TIMESTAMPTZ"
            else:
                json_type, timestamp_type = "TEXT", "TEXT"
            cursor.execute(f"""CREATE TABLE IF NOT EXISTS {self.table} (
                artifact_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_json {json_type} NOT NULL,
                created_at {timestamp_type} NOT NULL,
                status TEXT NOT NULL
            )""")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.schema}_artifact_owner ON {self.table} (tenant_id,user_id,conversation_id,thread_id,session_id,artifact_type)")

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _load(value: Any) -> Any:
        if isinstance(value, dict):
            return value
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)

    @staticmethod
    def _identity_params(identity: IdentityContext) -> tuple[str, ...]:
        return identity.tenant_id, identity.user_id, identity.conversation_id, identity.thread_id, identity.session_id

    def save_artifact(self, artifact: Artifact) -> Artifact:
        statement = f"""INSERT INTO {self.table}
            (artifact_id,tenant_id,user_id,conversation_id,thread_id,session_id,artifact_type,artifact_json,created_at,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(artifact_id) DO UPDATE SET
                artifact_json=excluded.artifact_json, status=excluded.status
            WHERE {self.table}.tenant_id=excluded.tenant_id
              AND {self.table}.user_id=excluded.user_id
              AND {self.table}.conversation_id=excluded.conversation_id
              AND {self.table}.thread_id=excluded.thread_id
              AND {self.table}.session_id=excluded.session_id"""
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(statement), (
                artifact.artifact_id, *self._identity_params(artifact.identity_context), artifact.artifact_type.value,
                self._dump(artifact.to_state()), artifact.created_at.isoformat(), artifact.status.value,
            ))
            if getattr(cursor, "rowcount", 1) == 0:
                raise PermissionError(
                    f"Artifact identity mismatch for existing artifact_id: {artifact.artifact_id}"
                )
        return artifact

    def update_artifact(self, artifact: Artifact) -> Artifact:
        statement = f"""UPDATE {self.table} SET artifact_json=%s,status=%s
            WHERE artifact_id=%s AND tenant_id=%s AND user_id=%s AND conversation_id=%s AND thread_id=%s AND session_id=%s"""
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(statement), (
                self._dump(artifact.to_state()), artifact.status.value, artifact.artifact_id,
                *self._identity_params(artifact.identity_context),
            ))
            if getattr(cursor, "rowcount", 1) == 0:
                raise KeyError(artifact.artifact_id)
        return artifact

    def get_artifact(self, artifact_id: str, *, identity_context: IdentityContext, include_deleted: bool = False) -> Artifact:
        statement = f"""SELECT artifact_json FROM {self.table}
            WHERE artifact_id=%s AND tenant_id=%s AND user_id=%s AND conversation_id=%s AND thread_id=%s AND session_id=%s"""
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(statement), (artifact_id, *self._identity_params(identity_context)))
            row = cursor.fetchone()
        if row is None:
            raise KeyError(artifact_id)
        artifact = Artifact.from_state(self._load(row[0]))
        if artifact.status is ArtifactLifecycleState.DELETED and not include_deleted:
            raise KeyError(artifact_id)
        return artifact

    def delete_artifact(self, artifact_id: str, *, identity_context: IdentityContext) -> Artifact:
        artifact = self.get_artifact(artifact_id, identity_context=identity_context, include_deleted=True)
        if artifact.status is ArtifactLifecycleState.DELETED:
            return artifact
        deleted = artifact.with_status(ArtifactLifecycleState.DELETED, payload=None, size=0)
        return self.update_artifact(deleted)

    def list_artifacts(self, *, identity_context: IdentityContext, artifact_type: ArtifactType | None = None, include_deleted: bool = False) -> list[Artifact]:
        statement = f"""SELECT artifact_json FROM {self.table}
            WHERE tenant_id=%s AND user_id=%s AND conversation_id=%s AND thread_id=%s AND session_id=%s"""
        params: list[Any] = list(self._identity_params(identity_context))
        if artifact_type is not None:
            statement += " AND artifact_type=%s"
            params.append(artifact_type.value)
        with self.db.transaction() as cursor:
            cursor.execute(self.db.sql(statement), tuple(params))
            rows = cursor.fetchall()
        artifacts = [Artifact.from_state(self._load(row[0])) for row in rows]
        if not include_deleted:
            artifacts = [artifact for artifact in artifacts if artifact.status is not ArtifactLifecycleState.DELETED]
        return sorted(artifacts, key=lambda item: (item.created_at, item.artifact_id))
