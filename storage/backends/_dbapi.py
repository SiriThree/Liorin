"""Small DB-API helpers shared by PostgreSQL production adapters."""
from __future__ import annotations

from contextlib import contextmanager
import re
from typing import Any, Callable, Iterator

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return value


class DBAPIAdapter:
    def __init__(self, connection_factory: Callable[[], Any], *, dialect: str = "postgres") -> None:
        if dialect not in {"postgres", "sqlite"}:
            raise ValueError("dialect must be postgres or sqlite")
        self.connection_factory = connection_factory
        self.dialect = dialect

    def sql(self, statement: str) -> str:
        return statement.replace("%s", "?") if self.dialect == "sqlite" else statement

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            try:
                yield cursor
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
        finally:
            connection.close()
