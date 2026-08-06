"""Governed Candidate -> Delta -> Policy -> Persist -> Retrieval runtime."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from math import ceil
from time import perf_counter
from threading import RLock
from typing import Any

from governance.acl import (
    MemoryAccessAction,
    MemoryAccessDenied,
    MemoryAccessPolicy,
)
from governance.audit import SafeMemoryAuditHook, get_default_memory_audit_log
from identity import IdentityContext
from memory.delta import MemoryUpdate
from memory.facts.delta import MemoryFactDeltaDetector, memory_fact_fingerprint
from memory.facts.extractor import MemoryCandidateExtractor
from memory.facts.models import MemoryFact, MemoryFactCandidate, display_value
from memory.facts.policy import MemoryPolicyDecision
from memory.facts.retriever import MemoryRetrievalResult, MemoryRetriever
from memory.facts.store import (
    InMemoryMemoryFactStore,
    MemoryFactStore,
    get_default_memory_fact_store,
    reset_default_memory_fact_store,
)
from metrics import MemoryMetricsRegistry, get_default_memory_metrics
from observability import RuntimeEventType, get_default_metrics, get_default_trace_recorder


def _lifecycle_contracts():
    from context_engine.models import (
        MemoryLifecycleEvent,
        MemoryLifecycleRecord,
        MemoryLifecycleState,
        MemoryMetadata,
    )
    return MemoryLifecycleEvent, MemoryLifecycleRecord, MemoryLifecycleState, MemoryMetadata


def deterministic_memory_fact_id(identity_context: IdentityContext, key: str) -> str:
    payload = "|".join(
        (
            identity_context.tenant_id,
            identity_context.user_id,
            str(key).strip().casefold(),
        )
    )
    return "memory-fact:" + sha256(payload.encode("utf-8")).hexdigest()[:32]


def _delta_attributes(delta: MemoryUpdate) -> dict[str, Any]:
    state = delta.to_state()
    return {
        "changed_fields": state["changed_fields"],
        "reason": state["reason"],
        "previous_fingerprint": state["previous_fingerprint"],
        "candidate_fingerprint": state["candidate_fingerprint"],
        "additions": state["additions"],
        "removals": state["removals"],
    }


def _estimated_tokens(value: Any) -> int:
    return max(1, ceil(len(display_value(value).encode("utf-8")) / 4))


@dataclass(frozen=True, slots=True)
class MemoryPromotionItemResult:
    candidate: MemoryFactCandidate
    fact: MemoryFact | None
    policy: MemoryPolicyDecision | None
    delta: MemoryUpdate
    persisted: bool
    lifecycle_records: tuple[Any, ...] = ()
    error: str | None = None

    @property
    def noop(self) -> bool:
        return self.delta.is_noop


@dataclass(frozen=True, slots=True)
class MemoryPromotionResult:
    items: tuple[MemoryPromotionItemResult, ...]

    @property
    def persisted_facts(self) -> tuple[MemoryFact, ...]:
        return tuple(item.fact for item in self.items if item.persisted and item.fact is not None)

    @property
    def lifecycle_records(self) -> tuple[Any, ...]:
        return tuple(record for item in self.items for record in item.lifecycle_records)

    @property
    def noop_count(self) -> int:
        return sum(1 for item in self.items if item.noop)

    @property
    def rejected_count(self) -> int:
        return sum(1 for item in self.items if item.policy is not None and not item.policy.approved)

    @property
    def failure_count(self) -> int:
        return sum(1 for item in self.items if item.error)

    def records_to_state(self) -> list[dict[str, Any]]:
        return [record.to_state() for record in self.lifecycle_records]


class LongTermMemoryRuntime:
    """Governed long-term memory runtime behind backend-neutral interfaces.

    Agent-facing promotion and retrieval fail soft: backend/policy/audit outages
    do not crash the support workflow. Explicit governance operations such as a
    user-requested delete remain fail-loud so operators can retry safely.
    """

    def __init__(
        self,
        *,
        store: MemoryFactStore | None = None,
        extractor: MemoryCandidateExtractor | None = None,
        policy: Any = None,
        delta_detector: MemoryFactDeltaDetector | None = None,
        access_policy: MemoryAccessPolicy | None = None,
        metrics: MemoryMetricsRegistry | None = None,
        hook: Any = None,
    ) -> None:
        self.store = store or get_default_memory_fact_store()
        self.extractor = extractor or MemoryCandidateExtractor()
        if policy is None:
            from governance.policy import GovernedMemoryPolicy
            policy = GovernedMemoryPolicy()
        self.policy = policy
        self.delta_detector = delta_detector or MemoryFactDeltaDetector()
        self.access_policy = access_policy or MemoryAccessPolicy()
        self.metrics = metrics or get_default_memory_metrics()
        if hook is None:
            hook = SafeMemoryAuditHook(
                get_default_memory_audit_log(),
                on_failure=lambda _exc: self.metrics.increment("audit_failure_count"),
            )
        self.hook = hook
        self._records: list[Any] = []
        self._expired_recorded: set[str] = set()
        self._rejected_fingerprints: set[tuple[str, str]] = set()
        self._lock = RLock()
        self.retriever = MemoryRetriever(
            self.store,
            access_policy=self.access_policy,
            on_retrieved=self._record_retrieved,
            on_expired=self._record_expired,
            on_denied=self._record_denied_retrieval,
        )

    def promote_from_state(
        self,
        state: Mapping[str, Any],
        *,
        identity_context: IdentityContext,
        actor: str,
        reason: str,
        working_memory: Any = None,
        now: datetime | None = None,
    ) -> MemoryPromotionResult:
        now = now or datetime.now(timezone.utc)
        try:
            candidates = self.extractor.extract(
                state,
                identity_context=identity_context,
                working_memory=working_memory,
                now=now,
            )
        except Exception:
            self.metrics.increment("policy_failure_count")
            return MemoryPromotionResult(())
        results = tuple(
            self.promote_candidate(candidate, actor=actor, reason=reason, now=now)
            for candidate in candidates
        )
        return MemoryPromotionResult(results)

    def promote_candidate(
        self,
        candidate: MemoryFactCandidate,
        *,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> MemoryPromotionItemResult:
        self.metrics.increment("memory_candidate_count")
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("LongTermMemoryRuntime requires timezone-aware now")
        effective_now = max(now, candidate.observed_at)
        fact_id = deterministic_memory_fact_id(candidate.identity_context, candidate.key)

        try:
            self.access_policy.assert_allowed(
                requester=candidate.identity_context,
                action=MemoryAccessAction.WRITE,
                resource_owner=candidate.identity_context,
            )
        except MemoryAccessDenied as exc:
            self.metrics.increment("acl_denied_count")
            return self._fail_closed_result(candidate, fact_id, reason, effective_now, str(exc), actor)

        try:
            previous = self.store.get_fact(
                fact_id,
                identity_context=candidate.identity_context,
            )
        except KeyError:
            previous = None
        except Exception as exc:
            self.metrics.increment("backend_failure_count")
            return self._fail_closed_result(
                candidate,
                fact_id,
                reason,
                effective_now,
                f"backend read failure: {type(exc).__name__}",
                actor,
            )

        fact = candidate.to_fact(fact_id=fact_id, previous=previous, now=effective_now)
        delta = self.delta_detector.detect(previous, fact, reason=reason)
        if previous is not None and delta.is_noop:
            self.metrics.increment("memory_noop_count")
            return MemoryPromotionItemResult(candidate, previous, None, delta, False, ())

        candidate_fp = memory_fact_fingerprint(fact)
        rejected_key = (fact_id, candidate_fp)
        if previous is None and rejected_key in self._rejected_fingerprints:
            self.metrics.increment("memory_noop_count")
            empty = self.delta_detector.detect(fact, fact, reason=reason)
            return MemoryPromotionItemResult(candidate, None, None, empty, False, ())

        emitted = self._candidate_record(candidate, fact, previous, delta, actor)
        try:
            decision = self.policy.evaluate(candidate, now=effective_now)
        except Exception as exc:
            self.metrics.increment("policy_failure_count")
            decision = MemoryPolicyDecision(
                False,
                "memory policy failure; fail-closed rejection",
                {"policy_error": type(exc).__name__},
            )
        if decision.approved:
            self.metrics.increment("memory_policy_accept_count")
        else:
            self.metrics.increment("memory_policy_reject_count")
        emitted.append(self._policy_record(candidate, fact, decision, delta))

        if not decision.approved:
            self._rejected_fingerprints.add(rejected_key)
            self._publish(emitted)
            return MemoryPromotionItemResult(candidate, previous, decision, delta, False, tuple(emitted))

        persisted_event = "CREATED" if previous is None else "UPDATED"
        persisted_record = self._persisted_record(candidate, fact, delta, persisted_event)
        persist_started = perf_counter()
        try:
            if previous is None:
                transactional = getattr(self.store, "save_fact_with_audit", None)
                persisted = transactional(fact, persisted_record) if callable(transactional) else self.store.save_fact(fact)
            else:
                transactional = getattr(self.store, "update_fact_with_audit", None)
                persisted = transactional(fact, persisted_record) if callable(transactional) else self.store.update_fact(fact)
        except Exception as exc:
            self.metrics.increment("backend_failure_count")
            get_default_metrics().increment("backend_failure_count")
            get_default_trace_recorder().emit(
                RuntimeEventType.BACKEND_FAILURE,
                attributes={"component": "memory", "operation": "persist", "error": type(exc).__name__},
            )
            self._publish(emitted)
            return MemoryPromotionItemResult(
                candidate,
                previous,
                decision,
                delta,
                False,
                tuple(emitted),
                error=f"backend persist failure: {type(exc).__name__}",
            )

        latency_ms = (perf_counter() - persist_started) * 1000
        self.metrics.increment("memory_update_count")
        unified = get_default_metrics()
        unified.increment("backend_operation_count")
        unified.increment("memory_write" if previous is None else "memory_update")
        unified.observe("memory_latency_ms", latency_ms)
        get_default_trace_recorder().emit(
            RuntimeEventType.MEMORY_WRITE if previous is None else RuntimeEventType.MEMORY_UPDATE,
            attributes={"fact_id": fact.fact_id, "fact_key": fact.key, "latency_ms": latency_ms, "transactional_audit": callable(transactional)},
        )
        emitted.append(persisted_record)
        self._publish(emitted)
        return MemoryPromotionItemResult(candidate, persisted, decision, delta, True, tuple(emitted))

    def retrieve_for_context(
        self,
        current_context: Mapping[str, Any] | str,
        *,
        identity_context: IdentityContext,
        limit: int = 6,
        now: datetime | None = None,
    ) -> MemoryRetrievalResult:
        retrieval_started = perf_counter()
        self.metrics.increment("memory_retrieval_count")
        if identity_context.is_anonymous:
            self.metrics.increment("acl_denied_count")
            return MemoryRetrievalResult((), "", ())
        try:
            self.access_policy.assert_allowed(
                requester=identity_context,
                action=MemoryAccessAction.READ,
                resource_owner=identity_context,
            )
            result = self.retriever.retrieve(
                current_context,
                identity_context=identity_context,
                limit=limit,
                now=now,
            )
        except MemoryAccessDenied:
            self.metrics.increment("acl_denied_count")
            return MemoryRetrievalResult((), "", ())
        except Exception as exc:
            self.metrics.increment("backend_failure_count")
            unified = get_default_metrics()
            unified.increment("backend_failure_count")
            unified.increment("backend_operation_count")
            get_default_trace_recorder().emit(
                RuntimeEventType.BACKEND_FAILURE,
                attributes={
                    "component": "memory",
                    "operation": "retrieve",
                    "error": type(exc).__name__,
                    "graceful_degradation": True,
                },
            )
            return MemoryRetrievalResult((), "", ())

        if result.facts:
            self.metrics.increment("memory_retrieval_hit_count")
            self.metrics.increment("memory_retrieved_fact_count", len(result.facts))
            self.metrics.increment(
                "memory_context_tokens",
                sum(_estimated_tokens(fact.value) for fact in result.facts),
            )
        if result.expired_fact_ids:
            self.metrics.increment("stale_memory_block_count", len(result.expired_fact_ids))
        if result.denied_fact_ids:
            self.metrics.increment("wrong_injection_count", len(result.denied_fact_ids))
        retrieval_latency_ms = (perf_counter() - retrieval_started) * 1000
        unified = get_default_metrics()
        unified.increment("backend_operation_count")
        unified.increment("memory_read")
        unified.observe("memory_latency_ms", retrieval_latency_ms)
        unified.increment("memory_hit", 1.0 if result.facts else 0.0)
        get_default_trace_recorder().emit(
            RuntimeEventType.MEMORY_READ,
            attributes={
                "fact_ids": [fact.fact_id for fact in result.facts],
                "hit_count": len(result.facts),
                "expired_count": len(result.expired_fact_ids),
                "denied_count": len(result.denied_fact_ids),
                "latency_ms": retrieval_latency_ms,
            },
        )
        return result

    def get(self, fact_id: str, *, identity_context: IdentityContext) -> MemoryFact:
        fact = self.store.get_fact(fact_id, identity_context=identity_context)
        self.access_policy.assert_allowed(
            requester=identity_context,
            action=MemoryAccessAction.READ,
            resource_owner=fact.identity_context,
        )
        return fact

    def delete(
        self,
        fact_id: str,
        *,
        identity_context: IdentityContext,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> MemoryFact:
        fact = self.store.get_fact(fact_id, identity_context=identity_context)
        self.access_policy.assert_allowed(
            requester=identity_context,
            action=MemoryAccessAction.DELETE,
            resource_owner=fact.identity_context,
        )
        return self._delete_owned_fact(
            fact,
            requester=identity_context,
            actor=actor,
            reason=reason,
            now=now,
        )

    def _delete_owned_fact(
        self,
        fact: MemoryFact,
        *,
        requester: IdentityContext,
        actor: str,
        reason: str,
        now: datetime | None = None,
        tenant_admin: bool = False,
    ) -> MemoryFact:
        if not tenant_admin:
            self.access_policy.assert_allowed(
                requester=requester,
                action=MemoryAccessAction.DELETE,
                resource_owner=fact.identity_context,
            )
        now = now or datetime.now(timezone.utc)
        MemoryLifecycleEvent, MemoryLifecycleRecord, MemoryLifecycleState, MemoryMetadata = _lifecycle_contracts()
        metadata = MemoryMetadata(
            id=fact.fact_id,
            created_at=fact.created_at,
            updated_at=max(now, fact.created_at),
            source=fact.source,
            confidence=fact.confidence,
            lifecycle_state=MemoryLifecycleState.DELETED,
        )
        delete_record = MemoryLifecycleRecord(
            event=MemoryLifecycleEvent.DELETED,
            memory=metadata,
            occurred_at=max(now, fact.created_at),
            actor=actor,
            reason=reason,
            attributes={"fact_key": fact.key, "fact_source": fact.source},
            identity_context=fact.identity_context,
        )
        transactional = getattr(self.store, "delete_fact_with_audit", None)
        deleted = (
            transactional(fact.fact_id, identity_context=fact.identity_context, audit_record=delete_record)
            if callable(transactional)
            else self.store.delete_fact(fact.fact_id, identity_context=fact.identity_context)
        )
        self._publish([delete_record])
        get_default_metrics().increment("memory_delete")
        return deleted

    def lifecycle_records(
        self,
        *,
        fact_id: str | None = None,
        identity_context: IdentityContext | None = None,
    ) -> tuple[Any, ...]:
        with self._lock:
            return tuple(
                record
                for record in self._records
                if (fact_id is None or record.memory.id == fact_id)
                and (
                    identity_context is None
                    or (
                        record.identity_context is not None
                        and record.identity_context.tenant_id == identity_context.tenant_id
                        and record.identity_context.user_id == identity_context.user_id
                    )
                )
            )

    def _candidate_record(
        self,
        candidate: MemoryFactCandidate,
        fact: MemoryFact,
        previous: MemoryFact | None,
        delta: MemoryUpdate,
        actor: str,
    ) -> list[Any]:
        MemoryLifecycleEvent, MemoryLifecycleRecord, MemoryLifecycleState, MemoryMetadata = _lifecycle_contracts()
        metadata = MemoryMetadata(
            id=fact.fact_id,
            created_at=fact.created_at,
            updated_at=fact.updated_at,
            source=fact.source,
            confidence=fact.confidence,
            lifecycle_state=MemoryLifecycleState.CANDIDATE,
        )
        attributes = {
            "fact_key": fact.key,
            "fact_source": fact.source,
            "verified": fact.verified,
            **_delta_attributes(delta),
        }
        return [MemoryLifecycleRecord(
            event=(MemoryLifecycleEvent.CREATED if previous is None else MemoryLifecycleEvent.UPDATED),
            memory=metadata,
            occurred_at=fact.updated_at,
            actor=actor,
            reason=f"Memory fact candidate: {candidate.reason}",
            attributes=attributes,
            identity_context=candidate.identity_context,
        )]

    def _policy_record(
        self,
        candidate: MemoryFactCandidate,
        fact: MemoryFact,
        decision: MemoryPolicyDecision,
        delta: MemoryUpdate,
    ) -> Any:
        MemoryLifecycleEvent, MemoryLifecycleRecord, MemoryLifecycleState, MemoryMetadata = _lifecycle_contracts()
        state = MemoryLifecycleState.POLICY_APPROVED if decision.approved else MemoryLifecycleState.POLICY_REJECTED
        metadata = MemoryMetadata(
            id=fact.fact_id,
            created_at=fact.created_at,
            updated_at=fact.updated_at,
            source="governance.memory_policy",
            confidence=fact.confidence,
            lifecycle_state=state,
        )
        return MemoryLifecycleRecord(
            event=MemoryLifecycleEvent.UPDATED,
            memory=metadata,
            occurred_at=fact.updated_at,
            actor="governance.memory_policy",
            reason=decision.reason,
            attributes={
                "approved": decision.approved,
                "criteria": dict(decision.criteria),
                "fact_key": fact.key,
                "fact_source": fact.source,
                **_delta_attributes(delta),
            },
            identity_context=candidate.identity_context,
        )

    def _persisted_record(
        self,
        candidate: MemoryFactCandidate,
        fact: MemoryFact,
        delta: MemoryUpdate,
        event_name: str,
    ) -> Any:
        MemoryLifecycleEvent, MemoryLifecycleRecord, MemoryLifecycleState, MemoryMetadata = _lifecycle_contracts()
        metadata = MemoryMetadata(
            id=fact.fact_id,
            created_at=fact.created_at,
            updated_at=fact.updated_at,
            source=fact.source,
            confidence=fact.confidence,
            lifecycle_state=MemoryLifecycleState.PERSISTED,
        )
        return MemoryLifecycleRecord(
            event=MemoryLifecycleEvent(event_name),
            memory=metadata,
            occurred_at=fact.updated_at,
            actor="memory.facts.runtime",
            reason="Persist approved long-term MemoryFact",
            attributes={"fact_key": fact.key, "fact_source": fact.source, **_delta_attributes(delta)},
            identity_context=candidate.identity_context,
        )

    def _fail_closed_result(
        self,
        candidate: MemoryFactCandidate,
        fact_id: str,
        reason: str,
        now: datetime,
        error: str,
        actor: str,
    ) -> MemoryPromotionItemResult:
        fact = candidate.to_fact(fact_id=fact_id, now=max(now, candidate.observed_at))
        delta = self.delta_detector.detect(None, fact, reason=reason)
        decision = MemoryPolicyDecision(False, error, {"fail_closed": True})
        self.metrics.increment("memory_policy_reject_count")
        records = self._candidate_record(candidate, fact, None, delta, actor)
        records.append(self._policy_record(candidate, fact, decision, delta))
        self._publish(records)
        return MemoryPromotionItemResult(candidate, None, decision, delta, False, tuple(records), error=error)

    def _record_retrieved(self, fact: MemoryFact, identity_context: IdentityContext, query: str) -> None:
        now = datetime.now(timezone.utc)
        MemoryLifecycleEvent, MemoryLifecycleRecord, MemoryLifecycleState, MemoryMetadata = _lifecycle_contracts()
        metadata = MemoryMetadata(
            id=fact.fact_id,
            created_at=fact.created_at,
            updated_at=fact.updated_at,
            source=fact.source,
            confidence=fact.confidence,
            lifecycle_state=MemoryLifecycleState.PERSISTED,
        )
        self._publish([MemoryLifecycleRecord(
            event=MemoryLifecycleEvent.RETRIEVED,
            memory=metadata,
            occurred_at=max(now, fact.created_at),
            actor="memory.facts.retriever",
            reason="Inject relevant long-term MemoryFact into Context Runtime",
            attributes={
                "fact_key": fact.key,
                "fact_source": fact.source,
                "verified": fact.verified,
                "query": query[:500],
            },
            identity_context=identity_context,
        )])

    def _record_expired(self, fact: MemoryFact, identity_context: IdentityContext) -> None:
        with self._lock:
            if fact.fact_id in self._expired_recorded:
                return
            self._expired_recorded.add(fact.fact_id)
        now = datetime.now(timezone.utc)
        MemoryLifecycleEvent, MemoryLifecycleRecord, MemoryLifecycleState, MemoryMetadata = _lifecycle_contracts()
        metadata = MemoryMetadata(
            id=fact.fact_id,
            created_at=fact.created_at,
            updated_at=max(now, fact.created_at),
            source=fact.source,
            confidence=fact.confidence,
            lifecycle_state=MemoryLifecycleState.EXPIRED,
        )
        self._publish([MemoryLifecycleRecord(
            event=MemoryLifecycleEvent.EXPIRED,
            memory=metadata,
            occurred_at=max(now, fact.created_at),
            actor="memory.facts.retriever",
            reason="Expired long-term MemoryFact excluded from Context Runtime",
            attributes={"fact_key": fact.key, "expires_at": fact.expires_at.isoformat() if fact.expires_at else None},
            identity_context=identity_context,
        )])

    def _record_denied_retrieval(self, fact: MemoryFact, identity_context: IdentityContext) -> None:
        self.metrics.increment("wrong_injection_count")
        self.metrics.increment("acl_denied_count")
        get_default_metrics().increment("wrong_injection_count")
        get_default_trace_recorder().emit(
            RuntimeEventType.MEMORY_BLOCK,
            attributes={"fact_id": fact.fact_id, "reason": "identity_acl"},
        )

    def _publish(self, records: Iterable[Any]) -> None:
        materialized = tuple(records)
        with self._lock:
            self._records.extend(materialized)
        if self.hook is not None:
            for record in materialized:
                try:
                    self.hook(record)
                except Exception:
                    self.metrics.increment("audit_failure_count")


_DEFAULT_RUNTIME: LongTermMemoryRuntime | None = None
_DEFAULT_RUNTIME_LOCK = RLock()


def get_default_long_term_memory_runtime() -> LongTermMemoryRuntime:
    global _DEFAULT_RUNTIME
    with _DEFAULT_RUNTIME_LOCK:
        if _DEFAULT_RUNTIME is None:
            _DEFAULT_RUNTIME = LongTermMemoryRuntime()
        return _DEFAULT_RUNTIME



def set_default_long_term_memory_runtime(runtime: LongTermMemoryRuntime) -> LongTermMemoryRuntime:
    global _DEFAULT_RUNTIME
    with _DEFAULT_RUNTIME_LOCK:
        _DEFAULT_RUNTIME = runtime
        return _DEFAULT_RUNTIME


def reset_default_long_term_memory_runtime() -> LongTermMemoryRuntime:
    global _DEFAULT_RUNTIME
    with _DEFAULT_RUNTIME_LOCK:
        store: InMemoryMemoryFactStore = reset_default_memory_fact_store()
        _DEFAULT_RUNTIME = LongTermMemoryRuntime(store=store)
        return _DEFAULT_RUNTIME


__all__ = [
    "LongTermMemoryRuntime",
    "MemoryPromotionItemResult",
    "MemoryPromotionResult",
    "deterministic_memory_fact_id",
    "get_default_long_term_memory_runtime",
    "reset_default_long_term_memory_runtime",
    "set_default_long_term_memory_runtime",
]
