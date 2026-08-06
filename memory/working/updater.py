"""Candidate -> Policy -> Persist lifecycle for Working Memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterable, Mapping

from context_engine.models import (
    MemoryLifecycleEvent, MemoryLifecycleHook, MemoryLifecycleRecord,
    MemoryLifecycleState, MemoryMetadata, estimate_token_cost,
)
from identity import IdentityContext
from memory.delta import MemoryDeltaDetector, MemoryUpdate
from memory.working.extractor import WorkingMemoryExtractor
from memory.working.models import WorkingMemory
from memory.working.serializer import WorkingMemorySerializer


@dataclass(frozen=True, slots=True)
class WorkingMemoryPolicyDecision:
    approved: bool
    reason: str


class WorkingMemoryPolicy:
    """Deterministic policy preventing large-payload contamination."""

    def __init__(self, *, max_context_tokens: int = 1200):
        if max_context_tokens <= 0:
            raise ValueError("max_context_tokens must be greater than zero")
        self.max_context_tokens = int(max_context_tokens)
        self.serializer = WorkingMemorySerializer()

    def evaluate(self, candidate: WorkingMemory) -> WorkingMemoryPolicyDecision:
        rendered = self.serializer.to_context_content(candidate)
        if estimate_token_cost(rendered) > self.max_context_tokens:
            return WorkingMemoryPolicyDecision(False, "working memory exceeds policy token limit")
        lowered = rendered.casefold()
        forbidden_markers = (
            "page_content=", "<tool_output>", "trace_events=",
            "candidate_documents=", "verified_evidences=",
        )
        if any(marker in lowered for marker in forbidden_markers):
            return WorkingMemoryPolicyDecision(False, "working memory contains artifact payload marker")
        if not candidate.has_task_state:
            return WorkingMemoryPolicyDecision(False, "working memory contains no task state")
        return WorkingMemoryPolicyDecision(True, "structured task state accepted")


@dataclass(frozen=True, slots=True)
class WorkingMemoryUpdate:
    memory: WorkingMemory
    lifecycle_records: tuple[MemoryLifecycleRecord, ...]
    policy: WorkingMemoryPolicyDecision | None
    persisted: bool
    delta: MemoryUpdate

    @property
    def noop(self) -> bool:
        return self.delta.is_noop

    def records_to_state(self) -> list[dict[str, Any]]:
        return [record.to_state() for record in self.lifecycle_records]


class InMemoryWorkingMemoryLifecycleAdapter:
    """Process-local lifecycle adapter; LangGraph state remains source of truth."""

    def __init__(self, *, hook: MemoryLifecycleHook | None = None):
        self._hook = hook
        self._memories: dict[str, WorkingMemory] = {}
        self._metadata: dict[str, MemoryMetadata] = {}
        self._records: dict[str, list[MemoryLifecycleRecord]] = {}
        self._lock = Lock()

    def persist(
        self,
        candidate: WorkingMemory,
        *,
        policy: WorkingMemoryPolicyDecision,
        delta: MemoryUpdate,
        actor: str,
        reason: str,
        existing_records: Iterable[MemoryLifecycleRecord | Mapping[str, Any]] = (),
        previous_memory: WorkingMemory | None = None,
        identity_context: IdentityContext | Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WorkingMemoryUpdate:
        now = now or datetime.now(timezone.utc)
        memory_id = f"working-memory:{candidate.session_id}"
        restored_records = tuple(_restore_records(existing_records))
        existing_metadata = _latest_metadata(restored_records, memory_id=memory_id)
        normalized_identity = _restore_identity(identity_context)

        with self._lock:
            previous = self._memories.get(candidate.session_id) or previous_memory
            created_at = (
                self._metadata.get(memory_id).created_at
                if memory_id in self._metadata
                else existing_metadata.created_at if existing_metadata else now
            )
            candidate_metadata = MemoryMetadata(
                id=memory_id, created_at=created_at, updated_at=now,
                source="memory.working.extractor", confidence=1.0,
                lifecycle_state=MemoryLifecycleState.CANDIDATE,
            )
            candidate_event = MemoryLifecycleEvent.UPDATED if previous is not None else MemoryLifecycleEvent.CREATED
            delta_attributes = _delta_attributes(delta)
            emitted = [MemoryLifecycleRecord(
                event=candidate_event, memory=candidate_metadata, occurred_at=now,
                actor=actor, reason=f"Working memory candidate: {reason}",
                attributes=delta_attributes,
                identity_context=normalized_identity,
            )]

            policy_state = MemoryLifecycleState.POLICY_APPROVED if policy.approved else MemoryLifecycleState.POLICY_REJECTED
            policy_metadata = MemoryMetadata(
                id=memory_id, created_at=created_at, updated_at=now,
                source="memory.working.policy", confidence=1.0,
                lifecycle_state=policy_state,
            )
            emitted.append(MemoryLifecycleRecord(
                event=MemoryLifecycleEvent.UPDATED, memory=policy_metadata,
                occurred_at=now, actor="memory.working.policy", reason=policy.reason,
                attributes={"approved": policy.approved, **delta_attributes},
                identity_context=normalized_identity,
            ))

            if not policy.approved:
                memory = previous or candidate
                self._publish(emitted)
                self._records.setdefault(candidate.session_id, []).extend(emitted)
                return WorkingMemoryUpdate(memory, tuple(emitted), policy, False, delta)

            persisted_metadata = MemoryMetadata(
                id=memory_id, created_at=created_at, updated_at=now,
                source="memory.working.lifecycle_adapter", confidence=1.0,
                lifecycle_state=MemoryLifecycleState.PERSISTED,
            )
            persisted_event = MemoryLifecycleEvent.UPDATED if previous is not None else MemoryLifecycleEvent.CREATED
            emitted.append(MemoryLifecycleRecord(
                event=persisted_event, memory=persisted_metadata, occurred_at=now,
                actor="memory.working.lifecycle_adapter",
                reason="Persist checkpoint-safe working memory state",
                attributes=delta_attributes,
                identity_context=normalized_identity,
            ))
            self._memories[candidate.session_id] = candidate
            self._metadata[memory_id] = persisted_metadata
            self._records.setdefault(candidate.session_id, []).extend(emitted)
            self._publish(emitted)
            return WorkingMemoryUpdate(candidate, tuple(emitted), policy, True, delta)

    def retrieve(self, session_id: str) -> WorkingMemory | None:
        with self._lock:
            return self._memories.get(session_id)

    def records(self, session_id: str) -> tuple[MemoryLifecycleRecord, ...]:
        with self._lock:
            return tuple(self._records.get(session_id, ()))

    def observe(self, record: MemoryLifecycleRecord) -> None:
        memory_id = record.memory.id
        prefix = "working-memory:"
        session_id = memory_id[len(prefix):] if memory_id.startswith(prefix) else memory_id
        with self._lock:
            self._records.setdefault(session_id, []).append(record)
        self._publish((record,))

    def _publish(self, records: Iterable[MemoryLifecycleRecord]) -> None:
        if self._hook is None:
            return
        for record in records:
            self._hook(record)


DEFAULT_WORKING_MEMORY_LIFECYCLE_ADAPTER = InMemoryWorkingMemoryLifecycleAdapter()


class WorkingMemoryUpdater:
    """Orchestrate structured extraction, policy and lifecycle persistence."""

    def __init__(
        self,
        *,
        extractor: WorkingMemoryExtractor | None = None,
        policy: WorkingMemoryPolicy | None = None,
        adapter: InMemoryWorkingMemoryLifecycleAdapter | None = None,
        delta_detector: MemoryDeltaDetector | None = None,
    ):
        self.extractor = extractor or WorkingMemoryExtractor()
        self.policy = policy or WorkingMemoryPolicy()
        self.adapter = adapter or DEFAULT_WORKING_MEMORY_LIFECYCLE_ADAPTER
        self.delta_detector = delta_detector or MemoryDeltaDetector()

    def update(
        self,
        state: Mapping[str, Any],
        *,
        actor: str,
        reason: str,
        previous: WorkingMemory | Mapping[str, Any] | None = None,
        existing_records: Iterable[MemoryLifecycleRecord | Mapping[str, Any]] = (),
        session_id: str | None = None,
        identity_context: IdentityContext | Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WorkingMemoryUpdate:
        previous_memory = (
            previous
            if isinstance(previous, WorkingMemory)
            else WorkingMemory.from_state(previous) if previous is not None else None
        )
        candidate = self.extractor.extract(
            state, previous=previous_memory, session_id=session_id, now=now,
        )
        delta = self.delta_detector.detect(previous_memory, candidate, reason=reason)
        if previous_memory is not None and delta.is_noop:
            return WorkingMemoryUpdate(
                memory=previous_memory, lifecycle_records=(), policy=None,
                persisted=False, delta=delta,
            )

        decision = self.policy.evaluate(candidate)
        return self.adapter.persist(
            candidate, policy=decision, delta=delta, actor=actor, reason=reason,
            existing_records=existing_records, previous_memory=previous_memory,
            identity_context=identity_context, now=now,
        )


def working_memory_retrieval_record(
    memory: WorkingMemory,
    *,
    lifecycle_records: Iterable[MemoryLifecycleRecord | Mapping[str, Any]] = (),
    actor: str = "context_engine.builder",
    reason: str = "Inject working memory into bounded model context",
    identity_context: IdentityContext | Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> MemoryLifecycleRecord:
    now = now or datetime.now(timezone.utc)
    restored = tuple(_restore_records(lifecycle_records))
    memory_id = f"working-memory:{memory.session_id}"
    metadata = _latest_metadata(restored, memory_id=memory_id)
    if metadata is None:
        metadata = MemoryMetadata(
            id=memory_id, created_at=memory.last_updated, updated_at=memory.last_updated,
            source="working_memory_checkpoint", confidence=1.0,
            lifecycle_state=MemoryLifecycleState.PERSISTED,
        )
    record = MemoryLifecycleRecord(
        event=MemoryLifecycleEvent.RETRIEVED, memory=metadata,
        occurred_at=max(now, metadata.created_at), actor=actor, reason=reason,
        identity_context=_restore_identity(identity_context),
    )
    DEFAULT_WORKING_MEMORY_LIFECYCLE_ADAPTER.observe(record)
    return record



def _delta_attributes(delta: MemoryUpdate) -> dict[str, Any]:
    """Flatten the explainable delta into lifecycle audit attributes."""

    state = delta.to_state()
    return {
        "changed_fields": state["changed_fields"],
        "reason": state["reason"],
        "previous_fingerprint": state["previous_fingerprint"],
        "candidate_fingerprint": state["candidate_fingerprint"],
        "additions": state["additions"],
        "removals": state["removals"],
    }


def _restore_identity(
    value: IdentityContext | Mapping[str, Any] | None,
) -> IdentityContext | None:
    if value is None or isinstance(value, IdentityContext):
        return value
    if isinstance(value, Mapping):
        return IdentityContext.from_state(value)
    raise TypeError("identity_context must be IdentityContext, mapping, or None")


def _restore_records(values: Iterable[MemoryLifecycleRecord | Mapping[str, Any]]) -> list[MemoryLifecycleRecord]:
    records: list[MemoryLifecycleRecord] = []
    for value in values:
        if isinstance(value, MemoryLifecycleRecord):
            records.append(value)
        elif isinstance(value, Mapping):
            try:
                records.append(MemoryLifecycleRecord.from_state(value))
            except (TypeError, ValueError):
                continue
    return records


def _latest_metadata(records: Iterable[MemoryLifecycleRecord], *, memory_id: str) -> MemoryMetadata | None:
    candidates = [record.memory for record in records if record.memory.id == memory_id]
    if not candidates:
        return None
    persisted = [item for item in candidates if item.lifecycle_state is MemoryLifecycleState.PERSISTED]
    return max(persisted or candidates, key=lambda item: item.updated_at)
