"""Shared tools for the Liorin support agent."""

__all__ = [
    "execute_sql",
    "get_database",
    "search_manuals",
    "search_support_policies",
]


def __getattr__(name: str):
    if name in {"execute_sql", "get_database"}:
        from tools.database import execute_sql, get_database

        return {"execute_sql": execute_sql, "get_database": get_database}[name]
    if name in {"search_manuals", "search_support_policies"}:
        from tools.documents import search_manuals, search_support_policies

        return {
            "search_manuals": search_manuals,
            "search_support_policies": search_support_policies,
        }[name]
    raise AttributeError(name)
