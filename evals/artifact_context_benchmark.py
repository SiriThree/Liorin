"""Deterministic Phase 4 benchmark for large Tool Result artifactization."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from artifact import ArtifactRegistry, ArtifactResolver, InMemoryArtifactStore
from context_engine import ContextBuilder, ContextItemType, estimate_token_cost
from identity import IdentityContext


def _identity() -> IdentityContext:
    return IdentityContext(
        tenant_id="tenant-benchmark",
        user_id="user-benchmark",
        conversation_id="conversation-artifact-benchmark",
        thread_id="thread-artifact-benchmark",
        session_id="session-artifact-benchmark",
    )


def _state(result_count: int = 100, payload_repeat: int = 1_200) -> tuple[dict, list[str]]:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "执行批量知识查询", "id": "user-start"}
    ]
    payloads: list[str] = []
    for index in range(result_count):
        payload = (
            f"TOOL_RESULT_{index}:"
            + ("产品手册证据、故障步骤、来源元数据、执行观察。" * payload_repeat)
        )
        payloads.append(payload)
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "id": f"assistant-{index}",
                    "tool_calls": [
                        {"id": f"call-{index}", "name": "knowledge_agent"}
                    ],
                },
                {
                    "role": "tool",
                    "name": "knowledge_agent",
                    "tool_call_id": f"call-{index}",
                    "content": payload,
                    "id": f"tool-{index}",
                },
            ]
        )
    messages.append(
        {"role": "user", "content": "根据已有产物给出最终方案", "id": "user-final"}
    )
    identity = _identity()
    return {
        "identity_context": identity.to_state(),
        "messages": messages,
    }, payloads


def run_benchmark(*, result_count: int = 100, payload_repeat: int = 1_200) -> dict[str, Any]:
    state, payloads = _state(result_count=result_count, payload_repeat=payload_repeat)
    original_state = deepcopy(state)
    identity = _identity()
    registry = ArtifactRegistry(store=InMemoryArtifactStore())
    builder = ContextBuilder(artifact_registry=registry)

    before_tokens = sum(estimate_token_cost(payload) for payload in payloads)
    items = builder.build(messages_state=state)
    references = [
        item
        for item in items
        if item.type is ContextItemType.ARTIFACT_REFERENCE
        and item.metadata.get("artifact_type") == "TOOL_RESULT"
    ]
    after_tokens = sum(item.token_cost for item in references)

    resolver = ArtifactResolver(registry)
    retrieval_success = 0
    reference_correct = 0
    for index, item in enumerate(references):
        artifact_id = str(item.metadata.get("artifact_id") or "")
        if artifact_id and artifact_id in item.content and "TOOL_RESULT_" not in item.content:
            reference_correct += 1
        payload = resolver.resolve(
            artifact_id,
            identity_context=identity,
            actor="evals.artifact_context_benchmark",
            reason="verify artifact lazy loading",
        )
        if payload.get("content") == payloads[index]:
            retrieval_success += 1

    token_reduction = 1.0 - (after_tokens / before_tokens if before_tokens else 0.0)
    return {
        "benchmark": "phase4_artifact_context",
        "tool_result_count": result_count,
        "before_context_tokens": before_tokens,
        "after_reference_tokens": after_tokens,
        "token_reduction_ratio": round(token_reduction, 6),
        "token_reduction_percent": round(token_reduction * 100, 4),
        "artifact_retrieval_success_count": retrieval_success,
        "artifact_retrieval_success_rate": round(retrieval_success / result_count, 6),
        "reference_correct_count": reference_correct,
        "reference_correct_rate": round(reference_correct / result_count, 6),
        "artifact_count": len(registry.list_artifacts(identity_context=identity)),
        "original_history_preserved": state == original_state,
        "artifact_payload_in_context": any(
            "TOOL_RESULT_" in item.content for item in references
        ),
        "measurement_scope": (
            "Deterministic ContextItem token estimate and exact payload recovery; "
            "not an LLM answer-quality evaluation."
        ),
    }


def main() -> None:
    result = run_benchmark()
    output_path = Path("artifacts/evals/ARTIFACT_CONTEXT_PHASE4_BENCHMARK.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
