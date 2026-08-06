"""Serialization and model-visible rendering for Working Memory."""

from __future__ import annotations

import json
from typing import Any, Mapping

from identity import IdentityContext
from memory.working.models import WorkingMemory


class WorkingMemorySerializer:
    """Keep checkpoint state and prompt rendering deterministic and compact."""

    _FIELD_LABELS = (
        ("task_goal", "当前目标"),
        ("current_intent", "当前意图"),
        ("confirmed_facts", "已确认事实"),
        ("open_questions", "未解决问题"),
        ("constraints", "约束"),
        ("decisions", "已做决策"),
        ("failed_attempts", "失败尝试"),
        ("next_actions", "下一步行动"),
    )

    @staticmethod
    def to_state(memory: WorkingMemory) -> dict[str, Any]:
        return memory.to_state()

    @staticmethod
    def from_state(value: WorkingMemory | Mapping[str, Any]) -> WorkingMemory:
        if isinstance(value, WorkingMemory):
            return value
        return WorkingMemory.from_state(value)

    def to_context_content(self, memory: WorkingMemory | Mapping[str, Any]) -> str:
        memory = self.from_state(memory)
        lines = [f"session_id={memory.session_id}"]
        for field_name, label in self._FIELD_LABELS:
            value = getattr(memory, field_name)
            if not value:
                continue
            if isinstance(value, tuple):
                lines.append(f"{label}：" + "；".join(value))
            else:
                lines.append(f"{label}：{value}")
        return "\n".join(lines)

    @staticmethod
    def checkpoint_payload(
        memory: WorkingMemory,
        *,
        lifecycle_records: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
        identity_context: IdentityContext | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "session_id": memory.session_id,
            "working_memory": memory.to_state(),
            "working_memory_lifecycle_records": [dict(record) for record in lifecycle_records],
        }
        if identity_context is not None:
            identity = (
                identity_context
                if isinstance(identity_context, IdentityContext)
                else IdentityContext.from_state(identity_context)
            )
            if identity.session_id != memory.session_id:
                raise ValueError(
                    "IdentityContext.session_id must match WorkingMemory.session_id"
                )
            payload["identity_context"] = identity.to_state()
        return payload

    @staticmethod
    def json_round_trip(payload: Mapping[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))
