"""Small deterministic reporting helpers for Phase E1-R."""
from __future__ import annotations
from collections import Counter
from typing import Any, Iterable, Mapping


def count_by(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(r.get(key) or "UNKNOWN") for r in rows).items()))


def family_status(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    nested: dict[str, Counter[str]] = {}
    for r in rows:
        nested.setdefault(str(r["mixed_family_id"]), Counter())[str(r["repair_status"])] += 1
    return {k: dict(sorted(v.items())) for k, v in sorted(nested.items())}


def concentration(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, Any]:
    c = Counter(str(r.get(key) or "UNKNOWN") for r in rows)
    return {"unique": len(c), "max_count": max(c.values(), default=0), "counts": dict(sorted(c.items()))}
