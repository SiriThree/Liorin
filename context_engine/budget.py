"""Token budget enforcement for normalized Liorin context."""

from __future__ import annotations

from collections.abc import Iterable

from context_engine.models import (
    ContextItem,
    ContextSelection,
    estimate_token_cost,
)


class ContextBudgetManager:
    """Fit ContextItems into a hard token budget.

    Required items are considered first.  When a required/high-priority item
    does not fit, its content is truncated rather than silently dropping the
    current request or task state.  The original state and audit/trace records
    remain untouched; only the ephemeral model-visible ContextItem is changed.
    """

    def __init__(self, max_tokens: int, *, minimum_partial_tokens: int = 16):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero")
        if minimum_partial_tokens <= 0:
            raise ValueError("minimum_partial_tokens must be greater than zero")
        self.max_tokens = int(max_tokens)
        self.minimum_partial_tokens = int(minimum_partial_tokens)

    def apply(self, items: Iterable[ContextItem]) -> ContextSelection:
        materialized = list(items)
        input_tokens = sum(int(item.token_cost or 0) for item in materialized)
        ranked = sorted(
            enumerate(materialized),
            key=lambda pair: (
                -int(pair[1].required),
                -pair[1].priority,
                -int(pair[1].metadata.get("is_current", False)),
                -pair[0],
            ),
        )

        remaining = self.max_tokens
        accepted: list[tuple[int, ContextItem]] = []
        dropped: list[str] = []
        truncated: list[str] = []

        required_remaining = sum(1 for _, item in ranked if item.required)
        for original_index, item in ranked:
            item_cost = int(item.token_cost or 0)
            if item.required:
                required_remaining -= 1

            if item_cost <= remaining:
                accepted.append((original_index, item))
                remaining -= item_cost
                continue

            reserve_for_required = required_remaining
            available = max(0, remaining - reserve_for_required)
            may_truncate = item.required or (
                item.priority >= 70 and available >= self.minimum_partial_tokens
            )
            if may_truncate and available > 0:
                compacted = self._truncate(item, available)
                compacted_cost = int(compacted.token_cost or 0)
                if compacted_cost <= remaining and compacted_cost > 0:
                    accepted.append((original_index, compacted))
                    remaining -= compacted_cost
                    truncated.append(item.id)
                    continue

            dropped.append(item.id)

        accepted.sort(key=lambda pair: pair[0])
        selected_items = tuple(item for _, item in accepted)
        selected_tokens = sum(int(item.token_cost or 0) for item in selected_items)
        return ContextSelection(
            items=selected_items,
            max_tokens=self.max_tokens,
            input_tokens=input_tokens,
            selected_tokens=selected_tokens,
            dropped_item_ids=tuple(dropped),
            truncated_item_ids=tuple(truncated),
        )

    @staticmethod
    def total_tokens(items: Iterable[ContextItem]) -> int:
        return sum(int(item.token_cost or 0) for item in items)

    @staticmethod
    def _truncate(item: ContextItem, max_tokens: int) -> ContextItem:
        if max_tokens <= 0:
            return item.with_content("", truncated=True, original_token_cost=item.token_cost)
        if int(item.token_cost or 0) <= max_tokens:
            return item

        suffix = "\n…[context truncated]"
        low, high = 0, len(item.content)
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate = item.content[:middle].rstrip()
            if middle < len(item.content):
                candidate += suffix
            if estimate_token_cost(candidate) <= max_tokens:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1

        if not best:
            # Tiny budgets still retain a visible marker for a required item.
            marker = "…"
            best = marker if estimate_token_cost(marker) <= max_tokens else ""
        return item.with_content(
            best,
            truncated=True,
            original_token_cost=item.token_cost,
        )
