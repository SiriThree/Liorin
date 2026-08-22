"""Deterministic structured-state extractor for Working Memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from memory.working.models import (
    FactStatus,
    MemoryAuthority,
    MemoryScope,
    ScopedMemoryFact,
    TaskMemory,
    TaskStatus,
    WorkingMemory,
    _stable_task_id,
)


_SENSITIVE_OR_LARGE_KEYS = {
    "messages", "candidate_documents", "evidences", "verified_evidences",
    "retrieval_response", "trace", "trace_events", "tool_output",
    "tool_outputs", "page_content", "parent_context",
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _message_value(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, Mapping):
        return message.get(key, default)
    return getattr(message, key, default)


def _message_role(message: Any) -> str:
    role = _message_value(message, "role") or _message_value(message, "type")
    role = str(role or "").casefold()
    return {"human": "user", "ai": "assistant"}.get(role, role)


def _latest_user_text(messages: Sequence[Any]) -> str:
    for message in reversed(messages):
        if _message_role(message) != "user":
            continue
        content = _message_value(message, "content", "")
        if isinstance(content, str):
            return content.strip()
    return ""


def _list_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [f"{key}={item}" for key, item in value.items() if item not in (None, "", [], {})]
    try:
        return [str(item) for item in value if item not in (None, "")]
    except TypeError:
        return [str(value)]


def _merge_unique(*groups: Sequence[str], max_items: int = 16) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            text = " ".join(str(raw).split()).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
            if len(result) >= max_items:
                return tuple(result)
    return tuple(result)


_TASK_ENTITY_KEYS = (
    "product_id",
    "product_model",
    "product_version",
    "error_code",
    "order_id",
    "ticket_id",
    "document_id",
    "policy_id",
    "region",
)


_BUSINESS_SYSTEM_KEYS = {"customer_id", "order_status", "ticket_status", "warranty_status"}
_USER_CORRECTION_MARKERS = (
    "说错", "看错", "改成", "不是", "应该是", "刚才.*错", "correction", "correct", "actually",
)
_TASK_SWITCH_MARKERS = ("另外", "还有一台", "另一个", "新的问题", "退货政策", "return policy", "another")


def _structured_entity_facts(
    state: Mapping[str, Any],
    *,
    task_id: str,
    now: datetime,
    previous_task: TaskMemory | None = None,
) -> tuple[ScopedMemoryFact, ...]:
    previous_active = {
        fact.key: fact
        for fact in (previous_task.structured_facts if previous_task else ())
        if fact.status == FactStatus.ACTIVE
    }
    facts: list[ScopedMemoryFact] = []
    for key in _TASK_ENTITY_KEYS:
        value = state.get(key)
        if value in (None, "", [], {}):
            continue
        authority = (
            MemoryAuthority.USER_CONFIRMED
            if bool(state.get("explicit_correction"))
            else MemoryAuthority.STRUCTURED_QUERY_UNDERSTANDING
        )
        old = previous_active.get(key)
        text = str(value).strip()
        if old is not None and old.value.casefold() != text.casefold():
            facts.append(old.superseded(by_value=text, now=now))
        facts.append(
            ScopedMemoryFact(
                key=key,
                value=text,
                scope=MemoryScope.TASK,
                task_id=task_id,
                status=FactStatus.ACTIVE,
                authority=authority,
                confidence=0.95 if authority == MemoryAuthority.USER_CONFIRMED else 0.85,
                source="support_workflow.structured_state",
                observed_at=now,
                updated_at=now,
                supersedes=old.value if old is not None and old.value.casefold() != text.casefold() else None,
            )
        )
    # Carry active previous task facts that were not mentioned this turn.
    for key, fact in previous_active.items():
        if key not in {item.key for item in facts if item.status == FactStatus.ACTIVE}:
            facts.append(fact)
    return tuple(facts)


def _fact_value(task: TaskMemory | None, key: str) -> str | None:
    if task is None:
        return None
    for fact in reversed(task.structured_facts):
        if fact.key == key and fact.status == FactStatus.ACTIVE:
            return fact.value
    return None


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(re.search(marker, folded, re.IGNORECASE) for marker in markers)


def _resolve_task(
    state: Mapping[str, Any],
    *,
    previous: WorkingMemory | None,
    task_goal: str,
    current_intent: str,
    latest_user: str,
    now: datetime,
) -> tuple[str, tuple[TaskMemory, ...], TaskMemory | None, bool]:
    if previous is None or not previous.tasks:
        task_id = _stable_task_id(task_goal, current_intent, state.get("product_model"), state.get("error_code"), now.isoformat())
        return task_id, (), None, False

    active = previous.active_task
    explicit_correction = bool(state.get("explicit_correction")) or _has_marker(latest_user, _USER_CORRECTION_MARKERS)
    explicit_switch = bool(state.get("new_task")) or _has_marker(latest_user, _TASK_SWITCH_MARKERS)
    entity_changed = any(
        state.get(key) not in (None, "", [], {})
        and _fact_value(active, key) is not None
        and str(state.get(key)).strip().casefold() != str(_fact_value(active, key)).casefold()
        for key in ("product_id", "product_model", "order_id", "ticket_id")
    )
    intent_changed = bool(current_intent and active.intent and current_intent != active.intent)

    if explicit_correction and entity_changed:
        return active.task_id, previous.tasks, active, True

    if explicit_switch or (entity_changed and intent_changed):
        new_task_id = _stable_task_id(task_goal, current_intent, state.get("product_model"), state.get("order_id"), now.isoformat())
        suspended = tuple(
            TaskMemory(
                **{**task.to_state(), "status": TaskStatus.SUSPENDED.value, "updated_at": now.isoformat()}
            )
            if task.task_id == active.task_id and task.status == TaskStatus.ACTIVE
            else task
            for task in previous.tasks
        )
        return new_task_id, suspended, None, False

    if entity_changed and not explicit_correction:
        return active.task_id, previous.tasks, active, False
    return active.task_id, previous.tasks, active, explicit_correction


class WorkingMemoryExtractor:
    """Build WorkingMemory from existing structured runtime state without an LLM."""

    def extract(
        self,
        state: Mapping[str, Any],
        *,
        previous: WorkingMemory | Mapping[str, Any] | None = None,
        session_id: str | None = None,
        now: datetime | None = None,
    ) -> WorkingMemory:
        previous_memory = self._previous(previous)
        workflow = _as_mapping(state.get("workflow_state"))
        now = now or datetime.now(timezone.utc)
        resolved_session_id = (
            str(session_id or state.get("session_id") or "").strip()
            or (previous_memory.session_id if previous_memory else "")
            or f"working-{uuid4().hex}"
        )

        latest_user = _latest_user_text(state.get("messages", []) or [])
        explicit_goal = str(
            state.get("task_goal")
            or state.get("original_question")
            or state.get("rewritten_question")
            or ""
        ).strip()
        task_goal = explicit_goal or (previous_memory.task_goal if previous_memory else "") or latest_user
        current_intent = str(
            state.get("current_intent")
            or state.get("task_type")
            or workflow.get("intent")
            or workflow.get("stage")
            or (previous_memory.current_intent if previous_memory else "")
            or ""
        )
        task_id, existing_tasks, previous_task, explicit_correction = _resolve_task(
            state,
            previous=previous_memory,
            task_goal=task_goal,
            current_intent=current_intent,
            latest_user=latest_user,
            now=now,
        )
        if explicit_correction:
            state = {**dict(state), "explicit_correction": True}

        previous_facts = previous_memory.confirmed_facts if previous_memory else ()
        structured_facts = _list_values(state.get("confirmed_facts"))
        for key in (
            "customer_id", "product_name", "product_id", "product_model",
            "product_version", "error_code", "order_id", "ticket_id",
            "document_id", "policy_id", "region",
        ):
            value = state.get(key)
            if value not in (None, ""):
                structured_facts.append(f"{key}={value}")
        if workflow.get("identity_status") == "verified":
            structured_facts.append("identity_status=verified")
        structured_facts.extend(
            f"covered_requirement={item}" for item in _list_values(state.get("covered_requirements"))
        )
        confirmed_facts = _merge_unique(previous_facts, structured_facts)
        active_structured = _structured_entity_facts(
            state,
            task_id=task_id,
            now=now,
            previous_task=previous_task,
        )
        active_confirmed_facts = tuple(
            f"{fact.key}={fact.value}"
            for fact in active_structured
            if fact.status == FactStatus.ACTIVE
        )
        confirmed_facts = _merge_unique(active_confirmed_facts, structured_facts)

        previous_questions = previous_task.open_questions if previous_task else ()
        open_questions: list[str] = []
        open_questions.extend(_list_values(state.get("open_questions")))
        open_questions.extend(f"需要补充：{slot}" for slot in _list_values(state.get("unresolved_slots")))
        open_questions.extend(f"尚未覆盖：{item}" for item in _list_values(state.get("missing_requirements")))
        clarification = state.get("clarification_question")
        if clarification:
            open_questions.append(str(clarification))
        questions_are_explicit = any(
            key in state for key in (
                "open_questions", "unresolved_slots", "missing_requirements", "clarification_question"
            )
        )
        normalized_questions = _merge_unique(open_questions)
        if not questions_are_explicit:
            normalized_questions = previous_questions

        previous_constraints = previous_task.constraints if previous_task else ()
        constraints = _merge_unique(
            previous_constraints,
            _list_values(state.get("constraints")),
            [f"requirement={item}" for item in _list_values(state.get("requirements"))],
        )

        previous_decisions = previous_task.decisions if previous_task else ()
        decisions = _list_values(state.get("decisions"))
        for key in ("verification_action", "answer_verification_action"):
            value = state.get(key)
            if value not in (None, ""):
                decisions.append(f"{key}={value}")
        if workflow.get("routing_reason"):
            decisions.append(f"routing_reason={workflow['routing_reason']}")
        normalized_decisions = _merge_unique(previous_decisions, decisions)

        previous_failures = previous_task.failed_attempts if previous_task else ()
        failures = _list_values(state.get("failed_attempts"))
        failures.extend(f"degraded={item}" for item in _list_values(state.get("degraded_reasons")))
        for error in state.get("verification_errors", []) or []:
            if isinstance(error, Mapping):
                code = error.get("code") or error.get("type") or "verification_error"
                reason = error.get("reason") or error.get("message") or ""
                failures.append(f"{code}: {reason}".strip())
            else:
                failures.append(str(error))
        normalized_failures = _merge_unique(previous_failures, failures)

        next_actions = _list_values(state.get("next_actions"))
        unresolved_slots = _list_values(state.get("unresolved_slots"))
        if unresolved_slots:
            next_actions.append("收集缺失信息：" + "、".join(unresolved_slots))
        stage = workflow.get("stage")
        if stage == "ready_for_supervisor":
            next_actions.append("由会话主管继续处理当前任务")
        elif stage == "identity_verification":
            next_actions.append("完成客户身份验证")
        for action_field in ("verification_action", "answer_verification_action"):
            action = state.get(action_field)
            if action == "retrieve_more":
                next_actions.append("执行补充检索")
            elif action == "handoff":
                next_actions.append("转人工复核")
        previous_actions = previous_task.next_actions if previous_task else ()
        actions_are_explicit = bool(next_actions) or any(
            key in state for key in (
                "next_actions", "workflow_state", "verification_action", "answer_verification_action"
            )
        )
        normalized_actions = _merge_unique(next_actions) if actions_are_explicit else previous_actions

        active_task = TaskMemory(
            task_id=task_id,
            task_goal=task_goal,
            intent=current_intent,
            status=TaskStatus.ACTIVE,
            created_at=previous_task.created_at if previous_task else now,
            updated_at=now,
            structured_facts=active_structured,
            confirmed_facts=confirmed_facts,
            open_questions=normalized_questions,
            constraints=constraints,
            decisions=normalized_decisions,
            failed_attempts=normalized_failures,
            next_actions=normalized_actions,
        )
        task_by_id = {task.task_id: task for task in existing_tasks}
        task_by_id[task_id] = active_task
        ordered_tasks = tuple(task_by_id[key] for key in task_by_id)

        return WorkingMemory(
            session_id=resolved_session_id,
            active_task_id=task_id,
            tasks=ordered_tasks,
            task_goal=task_goal,
            current_intent=current_intent,
            confirmed_facts=confirmed_facts,
            open_questions=normalized_questions,
            constraints=constraints,
            decisions=normalized_decisions,
            failed_attempts=normalized_failures,
            next_actions=normalized_actions,
            last_updated=now,
        )

    @staticmethod
    def ignored_payload_keys() -> frozenset[str]:
        return frozenset(_SENSITIVE_OR_LARGE_KEYS)

    @staticmethod
    def _previous(previous: WorkingMemory | Mapping[str, Any] | None) -> WorkingMemory | None:
        if previous is None:
            return None
        if isinstance(previous, WorkingMemory):
            return previous
        return WorkingMemory.from_state(previous)
