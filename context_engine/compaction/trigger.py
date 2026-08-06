"""Configurable trigger policy for context compaction."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from context_engine.models import ContextItem, ContextItemType
from context_engine.compaction.models import CompactionDecision


_COMPACTABLE_TYPES = {
    ContextItemType.USER_MESSAGE,
    ContextItemType.ASSISTANT_MESSAGE,
    ContextItemType.ARTIFACT_REFERENCE,
}


def is_compactable_history(item: ContextItem) -> bool:
    """Return whether an item is historical context eligible for compaction."""

    if item.type not in _COMPACTABLE_TYPES:
        return False
    if item.required or item.metadata.get("is_current"):
        return False
    if item.type is ContextItemType.ARTIFACT_REFERENCE:
        # Only historical tool observations are eligible. Explicit artifact
        # references produced by other systems remain untouched.
        return item.source == "messages_state" or item.metadata.get("role") == "tool"
    return True


@dataclass(frozen=True, slots=True)
class CompactionTrigger:
    """Trigger on token pressure or context item count."""

    token_threshold: int
    item_threshold: int | None = None
    enabled: bool = True
    minimum_compactable_items: int = 2

    def __post_init__(self) -> None:
        if self.token_threshold <= 0:
            raise ValueError("token_threshold must be greater than zero")
        if self.item_threshold is not None and self.item_threshold <= 0:
            raise ValueError("item_threshold must be greater than zero when configured")
        if self.minimum_compactable_items <= 0:
            raise ValueError("minimum_compactable_items must be greater than zero")

    def evaluate(self, items: Iterable[ContextItem]) -> CompactionDecision:
        materialized = list(items)
        input_tokens = sum(int(item.token_cost or 0) for item in materialized)
        compactable_count = sum(is_compactable_history(item) for item in materialized)
        token_exceeded = input_tokens > self.token_threshold
        item_exceeded = (
            self.item_threshold is not None
            and len(materialized) > self.item_threshold
        )
        enough_history = compactable_count >= self.minimum_compactable_items

        if not self.enabled:
            should_compact = False
            reason = "disabled"
        elif not enough_history:
            should_compact = False
            reason = "insufficient_compactable_history"
        elif token_exceeded:
            should_compact = True
            reason = "token_threshold_exceeded"
        elif item_exceeded:
            should_compact = True
            reason = "item_threshold_exceeded"
        else:
            should_compact = False
            reason = "below_threshold"

        return CompactionDecision(
            should_compact=should_compact,
            reason=reason,
            input_tokens=input_tokens,
            item_count=len(materialized),
            compactable_item_count=compactable_count,
            token_threshold=self.token_threshold,
            item_threshold=self.item_threshold,
        )
