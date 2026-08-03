"""Database access tools for the TechHub customer support agent."""

from langchain.tools import tool
from langchain_community.utilities import SQLDatabase

from config import DEFAULT_DB_PATH

_db = None


def get_database() -> SQLDatabase:
    """Return a cached SQLite database connection."""
    global _db
    if _db is None:
        _db = SQLDatabase.from_uri(f"sqlite:///{DEFAULT_DB_PATH}")
    return _db


@tool
def execute_sql(query: str) -> str:
    """Execute a read-only SELECT query against the TechHub database."""
    normalized_query = query.strip().upper()
    if not normalized_query.startswith("SELECT"):
        return "Error: Only SELECT queries are allowed."

    forbidden_keywords = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "ALTER",
        "DROP",
        "CREATE",
        "REPLACE",
        "TRUNCATE",
    ]
    if any(keyword in normalized_query for keyword in forbidden_keywords):
        return "Error: Query contains forbidden keyword."

    db = get_database()
    try:
        result = db._execute(query)
        return str([tuple(row.values()) for row in result])
    except Exception as exc:
        return f"SQL Error: {exc}"
