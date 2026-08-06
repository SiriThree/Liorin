"""Validation guardrails for context compaction."""

from __future__ import annotations

from collections.abc import Iterable
import json

from context_engine.models import ContextItem, ContextItemType, SummaryMetadata
from context_engine.compaction.models import (
    CompactionSummary,
    CompactionValidationResult,
)


class CompactionValidationError(ValueError):
    """Raised when compaction would lose protected runtime state."""


class CompactionValidator:
    """Ensure Working Memory and identity remain unchanged after compaction."""

    @staticmethod
    def _working_memory_snapshots(items: Iterable[ContextItem]) -> tuple[str, ...]:
        snapshots: list[str] = []
        for item in items:
            if item.type is not ContextItemType.MEMORY:
                continue
            if item.metadata.get("memory_kind") != "working":
                continue
            identity = item.metadata.get("identity_context")
            payload = {
                "id": item.id,
                "content": item.content,
                "source": item.source,
                "session_id": item.metadata.get("session_id"),
                "identity_context": identity,
            }
            snapshots.append(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            )
        return tuple(sorted(snapshots))

    @staticmethod
    def _identity_snapshots(items: Iterable[ContextItem]) -> tuple[str, ...]:
        values = {
            json.dumps(
                item.metadata.get("identity_context"),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            for item in items
            if item.metadata.get("identity_context") is not None
        }
        return tuple(sorted(values))

    def validate(
        self,
        *,
        before_items: Iterable[ContextItem],
        after_items: Iterable[ContextItem],
        summary: CompactionSummary,
        raise_on_failure: bool = True,
    ) -> CompactionValidationResult:
        before = tuple(before_items)
        after = tuple(after_items)
        errors: list[str] = []

        working_memory_preserved = (
            self._working_memory_snapshots(before)
            == self._working_memory_snapshots(after)
        )
        if not working_memory_preserved:
            errors.append("working_memory_changed_or_missing")

        before_identities = self._identity_snapshots(before)
        after_identities = self._identity_snapshots(after)
        summary_identity = json.dumps(
            summary.identity_context.to_state(),
            ensure_ascii=False,
            sort_keys=True,
        )
        identity_preserved = (
            bool(before_identities)
            and before_identities == after_identities
            and before_identities == (summary_identity,)
        )
        if not identity_preserved:
            errors.append("identity_context_changed_or_missing")

        try:
            restored_metadata = SummaryMetadata.from_state(
                summary.summary_metadata.to_state()
            )
            summary_metadata_valid = (
                restored_metadata.identity_context == summary.identity_context
                and restored_metadata.original_token_cost
                >= restored_metadata.compressed_token_cost
                and restored_metadata.source_range.source_item_ids
            )
        except (TypeError, ValueError):
            summary_metadata_valid = False
        if not summary_metadata_valid:
            errors.append("summary_metadata_invalid")

        result = CompactionValidationResult(
            valid=not errors,
            errors=tuple(errors),
            working_memory_preserved=working_memory_preserved,
            identity_preserved=identity_preserved,
            summary_metadata_valid=bool(summary_metadata_valid),
        )
        if errors and raise_on_failure:
            raise CompactionValidationError(
                "Context compaction validation failed: " + ", ".join(errors)
            )
        return result
