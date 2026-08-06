from __future__ import annotations

from datetime import datetime, timezone

import pytest

from context_engine import (
    ContextBuilder,
    ContextItem,
    ContextItemType,
    SummaryMetadata,
    SummarySourceRange,
)


def test_memory_context_types_are_reserved_without_breaking_existing_values():
    assert ContextItemType.USER_MESSAGE.value == "USER_MESSAGE"
    assert ContextItemType.MEMORY.value == "MEMORY"
    assert ContextItemType.MEMORY_SUMMARY.value == "MEMORY_SUMMARY"
    assert ContextItemType.USER_PROFILE.value == "USER_PROFILE"

    # Accept future lower-case producer values while preserving the existing
    # upper-case checkpoint/API representation.
    item = ContextItem(
        id="memory-1",
        type="memory",
        content="用户偏好中文回答",
        source="future-memory-store",
        priority=70,
    )
    assert item.type is ContextItemType.MEMORY
    assert item.to_state()["type"] == "MEMORY"


def test_summary_metadata_is_serializable_and_exposes_compression_metrics():
    metadata = SummaryMetadata(
        source_range=SummarySourceRange(
            start_turn=1,
            end_turn=20,
            source_item_ids=("message-1", "message-20"),
        ),
        generated_by="context_compactor",
        confidence=0.92,
        created_at=datetime(2026, 8, 6, 3, 0, tzinfo=timezone.utc),
        original_token_cost=12_000,
        compressed_token_cost=1_500,
    )
    item = ContextItem(
        id="summary-1",
        type=ContextItemType.SUMMARY,
        content="已确认产品型号与故障现象；下一步核对压缩机状态。",
        source="context_compactor",
        priority=80,
        metadata={"summary_metadata": metadata},
    )

    restored = item.summary_metadata
    assert item.is_auditable_summary is True
    assert restored is not None
    assert restored.source_range.start_turn == 1
    assert restored.source_range.end_turn == 20
    assert restored.tokens_saved == 10_500
    assert restored.compression_ratio == pytest.approx(0.125)
    assert item.to_state()["metadata"]["summary_metadata"]["generated_by"] == (
        "context_compactor"
    )


def test_builder_marks_placeholder_summary_as_not_evaluable():
    [item] = [
        item
        for item in ContextBuilder().build(
            workflow_state={"context_summary": "旧版无来源摘要"}
        )
        if item.type is ContextItemType.SUMMARY
    ]

    assert item.is_auditable_summary is False
    assert item.metadata["summary_metadata_status"] == "missing"
    assert item.metadata["eligible_for_compaction_metrics"] is False


def test_builder_accepts_valid_summary_metadata_contract():
    metadata = SummaryMetadata(
        source_range=SummarySourceRange(start_turn=2, end_turn=8),
        generated_by="context_compactor",
        confidence=0.85,
        created_at=datetime.now(timezone.utc),
        original_token_cost=4_000,
        compressed_token_cost=600,
    )
    [item] = [
        item
        for item in ContextBuilder().build(
            workflow_state={
                "context_summary": "已确认事实与待办事项",
                "context_summary_metadata": metadata,
            }
        )
        if item.type is ContextItemType.SUMMARY
    ]

    assert item.is_auditable_summary is True
    assert item.metadata["summary_metadata_status"] == "validated"
    assert item.metadata["eligible_for_compaction_metrics"] is True


def test_summary_metadata_rejects_untraceable_or_invalid_values():
    with pytest.raises(ValueError, match="turn range or source_item_ids"):
        SummarySourceRange()

    with pytest.raises(ValueError, match="between 0 and 1"):
        SummaryMetadata(
            source_range=SummarySourceRange(start_turn=1, end_turn=2),
            generated_by="context_compactor",
            confidence=1.1,
            created_at=datetime.now(timezone.utc),
            original_token_cost=100,
            compressed_token_cost=20,
        )
