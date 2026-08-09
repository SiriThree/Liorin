"""Thin production Evaluation adapter introduced by Phase 0.

The adapter enforces:

    ONE CASE -> ONE PRODUCTION EXECUTION -> ONE TRACE -> ONE PREDICTION RECORD

It never calls a specialist Agent, retrieval pipeline, verifier, or business
function a second time to fill diagnostics.  Diagnostics are read from the trace
created around the one deployment graph invocation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import uuid4

from agents.feature_flags import AgentFeatureConfig
from eval_platform.dataset import RuntimeCaseInput
from eval_platform.report import PredictionRecord
from evals.gold_isolation import assert_no_gold_leak
from observability import TraceRecorder, get_default_trace_recorder


def _load_production_graph() -> Any:
    # Lazy import keeps component-only evaluation usable without bootstrapping the
    # production graph and guarantees the formal path is the deployment entry.
    from deployments.support_agent_graph import graph

    return graph


def _load_production_graph_with_recovery(enabled: bool, *, use_checkpointer: bool = False, feature_config: AgentFeatureConfig | None = None) -> Any:
    if enabled and not use_checkpointer:
        return _load_production_graph()
    # The baseline is built by the same deployment module with only the recovery
    # policy disabled.  No alternative retriever/agent implementation is copied.
    from deployments.support_agent_graph import build_graph

    return build_graph(
        agentic_recovery_enabled=bool(enabled),
        use_checkpointer=use_checkpointer,
        feature_config=feature_config or AgentFeatureConfig(agentic_recovery_enabled=bool(enabled)),
    )


def _message_content(message: Any) -> str:
    if isinstance(message, Mapping):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


@dataclass(frozen=True, slots=True)
class PredictionDraft:
    final_response: str
    response_type: str
    trace_facts: Mapping[str, Any]
    runtime_metrics: Mapping[str, Any]


class TraceAdapter:
    """Read-only projection from one AgentExecutionTrace to evaluation facts."""

    @staticmethod
    def _normalise_source(value: Any) -> str | None:
        text = str(value or "").strip().lower()
        if not text:
            return None
        if text in {"structured_db", "database"}:
            return "database"
        if text in {"manual", "policy", "faq", "ticket_history"}:
            return text
        return None

    def adapt(self, trace: Mapping[str, Any]) -> dict[str, Any]:
        events = list(trace.get("events") or [])
        tool_names: list[str] = []
        agent_names: list[str] = []
        evidence_refs: list[str] = []
        structured_evidence_refs: list[str] = []
        used_sources: list[str] = []
        verifier_actions: list[str] = []
        recovery_actions: list[str] = []
        handoff_reasons: list[str] = []
        workflow_decisions: list[dict[str, Any]] = []
        authorization_decisions: list[dict[str, Any]] = []
        evidence_events: list[dict[str, Any]] = []
        verification_rounds: list[dict[str, Any]] = []
        retrieval_events: list[dict[str, Any]] = []
        recovery_events: list[dict[str, Any]] = []
        context_assemblies: list[dict[str, Any]] = []
        model_call_events: list[dict[str, Any]] = []
        memory_events: list[dict[str, Any]] = []
        artifact_events: list[dict[str, Any]] = []
        identity_events: list[dict[str, Any]] = []
        security_events: list[dict[str, Any]] = []
        tool_events: list[dict[str, Any]] = []
        model_calls = 0

        def stable_document_ref(document_id: str, section_id: str) -> str | None:
            if document_id and section_id:
                return f"doc:{document_id}#{section_id}"
            if section_id:
                return f"section:{section_id}"
            if document_id:
                return f"doc:{document_id}"
            return None

        def structured_ref(document_id: str, data: Mapping[str, Any]) -> str | None:
            record_type = str(data.get("record_type") or "")
            record_id = str(data.get("record_id") or "")
            field_path = str(data.get("field_path") or "")
            if record_type and record_id:
                return f"record:{record_type}:{record_id}" + (f"#{field_path}" if field_path else "")
            if document_id.startswith("db:"):
                parts = document_id.split(":", 2)
                if len(parts) == 3:
                    template_id, entity = parts[1], parts[2]
                    inferred = (
                        "order" if template_id.startswith("order_") else
                        "ticket" if template_id.startswith("ticket_") else
                        "warranty" if template_id.startswith("warranty_") else
                        "customer" if template_id.startswith("customer_") else None
                    )
                    if inferred:
                        return f"record:{inferred}:{entity}"
            return None

        for event_index, event in enumerate(events):
            event_type = str(event.get("event_type") or "")
            attrs = event.get("attributes") or {}
            trace_event_ref = f"{trace.get('request_id')}:event:{event_index}"
            if event_type == "MODEL_CALL":
                model_calls += 1
                model_call_events.append({
                    "model_call_id": str(attrs.get("model_call_id") or f"model-call:{model_calls}"),
                    "context_build_id": attrs.get("context_build_id"),
                    "input_tokens": int(attrs.get("input_tokens", attrs.get("prompt_tokens", 0)) or 0),
                    "context_estimated_tokens": int(attrs.get("context_estimated_tokens", 0) or 0),
                    "output_tokens": int(attrs.get("completion_tokens", 0) or 0),
                    "token_count_source": str(attrs.get("token_count_source") or "UNKNOWN"),
                    "message_count": int(attrs.get("message_count", 0) or 0),
                    "context_manifest": dict(attrs.get("context_manifest") or {}),
                    "context_strategy": dict(attrs.get("context_strategy") or {}),
                })
                continue
            if event_type == "CONTEXT_ASSEMBLED":
                context_assemblies.append({
                    "context_build_id": attrs.get("context_build_id"),
                    "cache_hit": bool(attrs.get("cache_hit")),
                    "strategy": dict(attrs.get("strategy") or {}),
                    "context_item_refs": list(attrs.get("context_item_refs") or ()),
                    "token_count": int(attrs.get("token_count", 0) or 0),
                    "input_tokens": int(attrs.get("input_tokens", 0) or 0),
                    "token_count_source": str(attrs.get("token_count_source") or "HEURISTIC_ESTIMATE"),
                    "dropped_item_ids": list(attrs.get("dropped_item_ids") or ()),
                    "truncated_item_ids": list(attrs.get("truncated_item_ids") or ()),
                    "compaction_result": dict(attrs.get("compaction_result") or {}),
                    "artifact_reference_count": int(attrs.get("artifact_reference_count", 0) or 0),
                    "memory_hits": int(attrs.get("memory_hits", 0) or 0),
                    "artifact_saved_tokens": int(attrs.get("artifact_saved_tokens", 0) or 0),
                })
                continue
            if event_type.startswith("MEMORY_"):
                memory_events.append({"event_type": event_type, **dict(attrs)})
                continue
            if event_type.startswith("ARTIFACT_"):
                artifact_events.append({"event_type": event_type, **dict(attrs)})
                continue
            if event_type in {"TOOL_STARTED", "TOOL_COMPLETED", "TOOL_FAILED"}:
                name = str(attrs.get("tool_name") or "")
                if event_type == "TOOL_STARTED" and name:
                    tool_names.append(name)
                    if name.endswith("_agent"):
                        agent_names.append(name)
                tool_events.append({
                    "trace_event_ref": trace_event_ref,
                    "event_type": event_type,
                    "tool_name": name or None,
                    "risk_level": attrs.get("risk_level"),
                    "arguments": dict(attrs.get("arguments") or {}) if isinstance(attrs.get("arguments"), Mapping) else {},
                    "side_effect": attrs.get("side_effect"),
                    "status": attrs.get("status"),
                    "error": attrs.get("error"),
                })
                continue
            if event_type == "IDENTITY_RESOLVED":
                identity_events.append({"trace_event_ref": trace_event_ref, **dict(attrs)})
                continue
            if event_type == "SECURITY_DECISION":
                security_events.append({"trace_event_ref": trace_event_ref, **dict(attrs)})
                continue
            if event_type == "WORKFLOW_DECISION":
                workflow_decisions.append(dict(attrs))
                continue
            if event_type == "AUTHORIZATION_DECISION":
                authorization_decisions.append(dict(attrs))
                continue
            if event_type != "RETRIEVAL_EVENT":
                continue

            step = str(attrs.get("step") or attrs.get("stage") or "")
            event_name = str(attrs.get("event") or "")
            status = str(attrs.get("status") or "")
            data = dict(attrs.get("data") or {})
            if step == "evidence":
                evidence_id = str(data.get("evidence_id") or "")
                document_id = str(data.get("document_id") or "")
                section_id = str(data.get("section_id") or "")
                stable_ref = stable_document_ref(document_id, section_id)
                structured = structured_ref(document_id, data)
                aliases = [value for value in (evidence_id, document_id, section_id, stable_ref, structured) if value]
                evidence_refs.extend(aliases)
                if structured:
                    structured_evidence_refs.append(structured)
                for contribution in data.get("retrieval_contributions") or []:
                    if isinstance(contribution, Mapping):
                        for key in ("source", "source_type"):
                            source = self._normalise_source(contribution.get(key))
                            if source:
                                used_sources.append(source)
                source = self._normalise_source(attrs.get("source") or data.get("source_type"))
                if source:
                    used_sources.append(source)
                evidence_events.append({
                    "event": event_name,
                    "status": status,
                    "round_id": data.get("round_id"),
                    "evidence_id": evidence_id or None,
                    "stable_ref": structured or stable_ref or evidence_id or None,
                    "document_id": document_id or None,
                    "section_id": section_id or None,
                    "record_type": data.get("record_type"),
                    "record_id": data.get("record_id"),
                    "field_path": data.get("field_path"),
                    "tool_name": data.get("tool_name"),
                    "result_ref": data.get("result_ref"),
                    "observed_value": data.get("observed_value"),
                    "selected_for_answer": bool(data.get("selected_for_answer")),
                    "fusion_rank": data.get("fusion_rank"),
                    "rerank_score": data.get("rerank_score"),
                    "requirement_coverage": list(data.get("requirement_coverage") or ()),
                    "authority": data.get("authority"),
                    "validity": data.get("validity"),
                    "conflict_status": data.get("conflict_status"),
                    "final_citation_usage": bool(data.get("final_citation_usage")),
                    "content_preview": data.get("content_preview"),
                    "tenant_ref": data.get("tenant_ref"),
                    "owner_ref": data.get("owner_ref"),
                    "allowed_user_refs": list(data.get("allowed_user_refs") or ()),
                    "required_permissions": list(data.get("required_permissions") or ()),
                    "classification": data.get("classification"),
                    "visibility": data.get("visibility"),
                    "security_status": data.get("security_status"),
                    "prompt_injection_risk": data.get("prompt_injection_risk"),
                    "trace_event_ref": trace_event_ref,
                    "aliases": list(dict.fromkeys(aliases)),
                })
                continue
            if step == "verify_evidence" and event_name == "complete":
                round_payload = {
                    "round_id": data.get("round_id"),
                    "action": str(data.get("action") or ""),
                    "coverage_before": data.get("coverage_before"),
                    "coverage_after": data.get("coverage_after"),
                    "coverage_change": data.get("coverage_change"),
                    "covered_requirements": list(data.get("covered_requirements") or ()),
                    "missing_requirements": list(data.get("missing_requirements") or ()),
                    "accepted_evidence_ids": list(data.get("accepted_evidence_ids") or ()),
                    "excluded_evidence_ids": list(data.get("excluded_evidence_ids") or ()),
                    "conflicts": list(data.get("conflicts") or ()),
                    "generated_subqueries": list(data.get("generated_subqueries") or ()),
                    "new_evidence_ids": list(data.get("new_evidence_ids") or ()),
                    "budget_before": dict(data.get("budget_before") or {}),
                    "budget_after": dict(data.get("budget_after") or {}),
                    "method": data.get("method"),
                    "policy_version": data.get("policy_version"),
                }
                verification_rounds.append(round_payload)
                action = round_payload["action"]
                if action:
                    verifier_actions.append(action)
                    if action in {"supplement", "rewrite", "relax", "relax_filters", "clarify", "handoff", "decompose"}:
                        recovery_actions.append(action)
                continue
            if step == "execute_retrieval" and event_name == "complete":
                retrieval_events.append({
                    "round_id": data.get("round_id"),
                    "status": status,
                    "latency_ms": data.get("latency_ms"),
                    "final_evidences": data.get("final_evidences"),
                    "subquery_statuses": list(data.get("subquery_statuses") or ()),
                    "budget_after": dict(data.get("budget_after") or {}),
                })
                continue
            if step in {"rewrite_query", "targeted_retrieve", "replan", "clarification", "handoff"}:
                recovery_events.append({"step": step, "event": event_name, "status": status, **data})
                if step == "handoff":
                    reason = str(data.get("reason") or "")
                    if reason:
                        handoff_reasons.append(reason)

        # Selected evidence has one stable semantic in Phase 3: the evidence set
        # accepted by the FINAL Evidence Verifier decision and therefore eligible
        # for answer-context gating. Earlier accepted evidence remains available
        # in ``evidence_events`` but does not define final selected precision.
        selected_evidence_ids = list(verification_rounds[-1].get("accepted_evidence_ids") or ()) if verification_rounds else []
        selected_semantics = "FINAL_VERIFIER_ACCEPTED_EVIDENCE_PASSED_TO_ANSWER_GATE"
        # Structured tool results are directly returned into the specialist LLM
        # context.  They therefore count as selected evidence independently of
        # the Knowledge-Agent verifier gate.
        selected_structured_ids = [
            str(item.get("stable_ref") or item.get("evidence_id"))
            for item in evidence_events
            if item.get("selected_for_answer") and (item.get("stable_ref") or item.get("evidence_id"))
        ]
        if selected_structured_ids:
            selected_evidence_ids.extend(selected_structured_ids)
            selected_semantics += "+STRUCTURED_TOOL_RESULT_PASSED_TO_SPECIALIST_CONTEXT"

        if not selected_evidence_ids:
            # Backward compatibility for Phase-0/2 traces that only marked each
            # evidence event accepted/excluded and did not persist the verifier's
            # accepted_evidence_ids array. Prefer the latest observed round when
            # available; otherwise preserve the old accepted-event semantics.
            round_values = [item.get("round_id") for item in evidence_events if isinstance(item.get("round_id"), int)]
            latest_round = max(round_values) if round_values else None
            selected_evidence_ids = [
                str(item.get("evidence_id")) for item in evidence_events
                if item.get("evidence_id") and str(item.get("status") or "").lower() == "accepted"
                and (latest_round is None or item.get("round_id") == latest_round)
            ]
            if selected_evidence_ids:
                selected_semantics = "LEGACY_ACCEPTED_EVIDENCE_EVENT_FALLBACK"
        retrieved_evidence_ids = [str(item.get("evidence_id")) for item in evidence_events if item.get("evidence_id") and item.get("event") != "cited"]
        round_ids = {int(item["round_id"]) for item in verification_rounds if isinstance(item.get("round_id"), int)}
        retrieval_rounds = len(round_ids) if round_ids else len(verification_rounds)

        return {
            "prediction_schema_version": "5.0",
            "trace_id": trace.get("request_id"),
            "tool_names": list(dict.fromkeys(tool_names)),
            "agent_names": list(dict.fromkeys(agent_names)),
            "retrieved_evidence_ids": list(dict.fromkeys(retrieved_evidence_ids)),
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "structured_evidence_refs": list(dict.fromkeys(structured_evidence_refs)),
            "selected_evidence_ids": list(dict.fromkeys(str(x) for x in selected_evidence_ids if x)),
            "selected_evidence_semantics": selected_semantics,
            "evidence_events": evidence_events,
            "verification_rounds": verification_rounds,
            "retrieval_events": retrieval_events,
            "recovery_events": recovery_events,
            "used_sources": sorted(set(used_sources)),
            "verifier_actions": verifier_actions,
            "recovery_actions": recovery_actions,
            "handoff_reasons": handoff_reasons,
            "workflow_decisions": workflow_decisions,
            "authorization_decisions": authorization_decisions,
            "identity_events": identity_events,
            "security_events": security_events,
            "tool_events": tool_events,
            "retrieval_rounds": retrieval_rounds,
            "first_pass_verifier_action": verifier_actions[0] if verifier_actions else None,
            "context_assemblies": context_assemblies,
            "model_call_events": model_call_events,
            "memory_events": memory_events,
            "artifact_events": artifact_events,
            "model_input_tokens_total": sum(int(item.get("input_tokens", 0) or 0) for item in model_call_events),
            "model_input_token_sources": sorted(set(str(item.get("token_count_source") or "UNKNOWN") for item in model_call_events)),
            "model_calls": model_calls,
            "tool_calls": len(tool_names),
            "event_count": len(events),
        }



class ProductionEvaluationAdapter:
    """Invoke the real deployment graph once and project only its resulting trace."""

    def __init__(
        self,
        *,
        graph: Any | None = None,
        graph_loader: Callable[[], Any] | None = None,
        trace_recorder: TraceRecorder | None = None,
        trace_adapter: TraceAdapter | None = None,
    ) -> None:
        if graph is not None and graph_loader is not None:
            raise ValueError("provide graph or graph_loader, not both")
        self._graph = graph
        self._graph_loader = graph_loader or _load_production_graph
        self.trace_recorder = trace_recorder or get_default_trace_recorder()
        self.trace_adapter = trace_adapter or TraceAdapter()

    @classmethod
    def for_agentic_recovery(
        cls,
        *,
        enabled: bool,
        trace_recorder: TraceRecorder | None = None,
        trace_adapter: TraceAdapter | None = None,
    ) -> "ProductionEvaluationAdapter":
        return cls(
            graph_loader=lambda: _load_production_graph_with_recovery(bool(enabled)),
            trace_recorder=trace_recorder,
            trace_adapter=trace_adapter,
        )

    @classmethod
    def for_context_strategy(
        cls,
        *,
        agentic_recovery_enabled: bool = True,
        use_checkpointer: bool = True,
        trace_recorder: TraceRecorder | None = None,
        trace_adapter: TraceAdapter | None = None,
    ) -> "ProductionEvaluationAdapter":
        """Build the same production graph for a multi-turn context experiment.

        Context policy itself travels through ``RuntimeCaseInput.context``; this
        factory only makes the real top-level conversation checkpoint explicit.
        """
        return cls(
            graph_loader=lambda: _load_production_graph_with_recovery(
                bool(agentic_recovery_enabled), use_checkpointer=bool(use_checkpointer)
            ),
            trace_recorder=trace_recorder,
            trace_adapter=trace_adapter,
        )


    @classmethod
    def for_feature_config(
        cls,
        feature_config: AgentFeatureConfig,
        *,
        use_checkpointer: bool = False,
        trace_recorder: TraceRecorder | None = None,
        trace_adapter: TraceAdapter | None = None,
    ) -> "ProductionEvaluationAdapter":
        """Build the same deployment graph with an explicit controlled feature configuration."""
        return cls(
            graph_loader=lambda: _load_production_graph_with_recovery(
                feature_config.agentic_recovery_enabled,
                use_checkpointer=use_checkpointer,
                feature_config=feature_config,
            ),
            trace_recorder=trace_recorder,
            trace_adapter=trace_adapter,
        )

    @staticmethod
    def _identity(case: RuntimeCaseInput) -> dict[str, str]:
        source = case.identity.to_runtime_mapping() if case.identity is not None else {}
        suffix = case.case_id
        return {
            "tenant_id": str(source.get("tenant_id") or "tenant:public"),
            "user_id": str(source.get("user_id") or "user:benchmark-public"),
            "conversation_id": str(source.get("conversation_id") or f"conversation:eval:{suffix}"),
            "thread_id": str(source.get("thread_id") or f"thread:eval:{suffix}"),
            "session_id": str(source.get("session_id") or f"session:eval:{suffix}"),
        }

    def _graph_instance(self) -> Any:
        if self._graph is None:
            self._graph = self._graph_loader()
        return self._graph

    def run(self, case: RuntimeCaseInput) -> PredictionRecord:
        if not isinstance(case, RuntimeCaseInput):
            raise TypeError("ProductionEvaluationAdapter accepts RuntimeCaseInput only; Gold-bearing samples are forbidden")
        packet = case.runtime_packet()
        assert_no_gold_leak(packet)
        identity = self._identity(case)

        config = dict(case.config)
        configurable = dict(config.get("configurable") or {})
        configurable.update(identity)
        config["configurable"] = configurable
        context = dict(case.context)
        state = {"messages": [item.to_state() for item in case.messages]}
        assert_no_gold_leak({"state": state, "config": config, "context": context})

        request_id = f"eval:{case.case_id}:{uuid4().hex[:12]}"
        output: Mapping[str, Any] = {}
        execution_error: str | None = None
        trace = None
        try:
            with self.trace_recorder.trace(
                request_id=request_id,
                conversation_id=identity["conversation_id"],
                thread_id=identity["thread_id"],
                agent_name="support_agent",
            ) as trace:
                # Exactly one production invocation. No fallback specialist execution is
                # permitted if this call fails.
                output = self._graph_instance().invoke(
                    state,
                    config=config,
                    context=context or None,
                )
        except Exception as exc:
            execution_error = f"{type(exc).__name__}: {exc}"

        if trace is None:
            raise RuntimeError("production evaluation trace was not created")
        trace_state = trace.to_state()
        facts = self.trace_adapter.adapt(trace_state)
        messages = list(output.get("messages") or []) if isinstance(output, Mapping) else []
        final_response = _message_content(messages[-1]) if messages else ""
        latest_action = (facts.get("verifier_actions") or [None])[-1]
        if latest_action == "clarify":
            response_type = "clarification"
        elif latest_action == "handoff":
            response_type = "handoff"
        else:
            response_type = "answer" if final_response else "error"
        draft = PredictionDraft(
            final_response=final_response,
            response_type=response_type,
            trace_facts=facts,
            runtime_metrics={
                "latency_ms": trace_state.get("duration_ms"),
                "model_calls": facts.get("model_calls", 0),
                "tool_calls": facts.get("tool_calls", 0),
                "retrieval_rounds": facts.get("retrieval_rounds", 0),
            },
        )
        record = PredictionRecord(
            case_id=case.case_id,
            trace_id=str(trace_state["request_id"]),
            final_response=draft.final_response,
            response_type=draft.response_type,
            trace_facts=draft.trace_facts,
            runtime_metrics=draft.runtime_metrics,
            execution_status=str(trace_state.get("status") or "UNKNOWN"),
            execution_error=execution_error or trace_state.get("error"),
            schema_version="5.0",
        )
        assert_no_gold_leak(record.to_state())
        return record
