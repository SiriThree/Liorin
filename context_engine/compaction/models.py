"""Models for auditable, identity-bound context compaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from context_engine.models import SummaryMetadata, _json_safe
from identity import IdentityContext


_COMPACTION_SECTIONS = (
    "task_progress",
    "important_decisions",
    "confirmed_information",
    "pending_questions",
    "failed_attempts",
)


@dataclass(frozen=True, slots=True)
class CompactionSummary:
    """Structured summary produced from model-visible historical context.

    The summary is not memory and does not own the source history.  It is an
    ephemeral, auditable representation whose source items continue to exist in
    LangGraph state/checkpoints.
    """

    summary_content: Mapping[str, tuple[str, ...] | list[str]]
    summary_metadata: SummaryMetadata
    identity_context: IdentityContext

    def __post_init__(self) -> None:
        if not isinstance(self.summary_metadata, SummaryMetadata):
            if not isinstance(self.summary_metadata, Mapping):
                raise TypeError("CompactionSummary.summary_metadata must be SummaryMetadata or mapping")
            object.__setattr__(
                self,
                "summary_metadata",
                SummaryMetadata.from_state(self.summary_metadata),
            )

        if not isinstance(self.identity_context, IdentityContext):
            if not isinstance(self.identity_context, Mapping):
                raise TypeError("CompactionSummary.identity_context must be IdentityContext or mapping")
            object.__setattr__(
                self,
                "identity_context",
                IdentityContext.from_state(self.identity_context),
            )

        metadata_identity = self.summary_metadata.identity_context
        if metadata_identity is None:
            raise ValueError("CompactionSummary requires identity-bound SummaryMetadata")
        if metadata_identity != self.identity_context:
            raise ValueError("CompactionSummary identity must match SummaryMetadata.identity_context")

        if not isinstance(self.summary_content, Mapping):
            raise TypeError("CompactionSummary.summary_content must be a mapping")
        normalized: dict[str, tuple[str, ...]] = {}
        for section in _COMPACTION_SECTIONS:
            raw_values = self.summary_content.get(section, ())
            if isinstance(raw_values, str):
                raw_values = (raw_values,)
            values = tuple(
                value
                for value in (str(item).strip() for item in raw_values or ())
                if value
            )
            normalized[section] = values
        unknown_sections = set(self.summary_content) - set(_COMPACTION_SECTIONS)
        if unknown_sections:
            raise ValueError(
                "CompactionSummary contains unsupported sections: "
                + ", ".join(sorted(str(section) for section in unknown_sections))
            )
        object.__setattr__(self, "summary_content", normalized)

    def to_state(self) -> dict[str, Any]:
        return {
            "summary_content": {
                key: list(values) for key, values in self.summary_content.items()
            },
            "summary_metadata": self.summary_metadata.to_state(),
            "identity_context": self.identity_context.to_state(),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "CompactionSummary":
        return cls(
            summary_content=value.get("summary_content") or {},
            summary_metadata=SummaryMetadata.from_state(
                value.get("summary_metadata") or {}
            ),
            identity_context=IdentityContext.from_state(
                value.get("identity_context") or {}
            ),
        )


@dataclass(frozen=True, slots=True)
class CompactionDecision:
    """Result of the configurable trigger evaluation."""

    should_compact: bool
    reason: str
    input_tokens: int
    item_count: int
    compactable_item_count: int
    token_threshold: int
    item_threshold: int | None

    def to_state(self) -> dict[str, Any]:
        return _json_safe({
            "should_compact": self.should_compact,
            "reason": self.reason,
            "input_tokens": self.input_tokens,
            "item_count": self.item_count,
            "compactable_item_count": self.compactable_item_count,
            "token_threshold": self.token_threshold,
            "item_threshold": self.item_threshold,
        })


@dataclass(frozen=True, slots=True)
class CompactionValidationResult:
    """Auditable validation outcome for one compaction attempt."""

    valid: bool
    errors: tuple[str, ...] = ()
    working_memory_preserved: bool = False
    identity_preserved: bool = False
    summary_metadata_valid: bool = False

    def to_state(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "working_memory_preserved": self.working_memory_preserved,
            "identity_preserved": self.identity_preserved,
            "summary_metadata_valid": self.summary_metadata_valid,
        }


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """Compacted item view and its audit information."""

    items: tuple[Any, ...]
    summary: CompactionSummary
    compacted_item_ids: tuple[str, ...]
    preserved_item_ids: tuple[str, ...]
    validation: CompactionValidationResult | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def with_validation(
        self, validation: CompactionValidationResult
    ) -> "CompactionResult":
        return CompactionResult(
            items=self.items,
            summary=self.summary,
            compacted_item_ids=self.compacted_item_ids,
            preserved_item_ids=self.preserved_item_ids,
            validation=validation,
            attributes=self.attributes,
        )

    def to_manifest(self) -> dict[str, Any]:
        metadata = self.summary.summary_metadata
        return _json_safe({
            "applied": True,
            "compacted_item_count": len(self.compacted_item_ids),
            "compacted_item_ids": list(self.compacted_item_ids),
            "preserved_item_count": len(self.preserved_item_ids),
            "summary": {
                "generated_by": metadata.generated_by,
                "confidence": metadata.confidence,
                "original_token_cost": metadata.original_token_cost,
                "compressed_token_cost": metadata.compressed_token_cost,
                "tokens_saved": metadata.tokens_saved,
                "compression_ratio": metadata.compression_ratio,
                "source_range": metadata.source_range.to_state(),
                "identity_context": self.summary.identity_context.to_state(),
            },
            "validation": self.validation.to_state() if self.validation else None,
            **dict(self.attributes),
        })
