"""Policy-based context selection for Liorin."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from context_engine.models import ContextItem, ContextItemType


_TYPE_ORDER = {
    ContextItemType.SYSTEM: 0,
    ContextItemType.MEMORY: 1,
    ContextItemType.USER_PROFILE: 1,
    ContextItemType.WORKFLOW_STATE: 2,
    ContextItemType.SUMMARY: 3,
    ContextItemType.MEMORY_SUMMARY: 3,
    ContextItemType.EVIDENCE_REFERENCE: 4,
    ContextItemType.RETRIEVAL_REFERENCE: 5,
    ContextItemType.ARTIFACT_REFERENCE: 6,
    # Historical dialogue is rendered after structured state and shares one
    # bucket so user/assistant chronology is preserved by sequence.
    ContextItemType.USER_MESSAGE: 7,
    ContextItemType.ASSISTANT_MESSAGE: 7,
}


class ContextSelector:
    """Remove redundant/noisy context before token budgeting.

    Selection is deterministic and intentionally rule-based in Phase 1.  It
    preserves required items, keeps the newest/highest-priority duplicate and
    lowers historical messages, old retrieval records and repeated tool
    results without deleting their source/trace metadata from state.
    """

    def select(self, items: Iterable[ContextItem]) -> list[ContextItem]:
        materialized = list(items)
        if not materialized:
            return []

        deduplicated: dict[str, ContextItem] = {}
        for item in materialized:
            key = str(item.metadata.get("dedupe_key") or self._default_key(item))
            existing = deduplicated.get(key)
            if existing is None or self._prefer(item, existing):
                deduplicated[key] = item

        selected = list(deduplicated.values())
        selected.sort(key=self._presentation_key)
        return selected

    @staticmethod
    def _default_key(item: ContextItem) -> str:
        normalized = " ".join(item.content.split()).casefold()
        return f"{item.type.value}:{item.source}:{normalized}"

    @staticmethod
    def _prefer(candidate: ContextItem, existing: ContextItem) -> bool:
        candidate_key = (
            int(candidate.required),
            candidate.priority,
            candidate.timestamp,
        )
        existing_key = (
            int(existing.required),
            existing.priority,
            existing.timestamp,
        )
        return candidate_key > existing_key

    @staticmethod
    def _presentation_key(item: ContextItem) -> tuple[int, int, datetime, str]:
        sequence = int(item.metadata.get("sequence", 0))
        return (
            _TYPE_ORDER.get(item.type, 99),
            sequence,
            item.timestamp,
            item.id,
        )
