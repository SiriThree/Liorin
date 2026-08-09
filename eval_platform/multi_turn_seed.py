"""Representative Phase-4 multi-turn session candidates.

These cases are schema/annotation candidates only.  They are intentionally
MODEL_GENERATED_UNREVIEWED and therefore ineligible for formal metrics until a
human review records the required context/memory Gold against real corpus/data.
"""
from __future__ import annotations

from eval_platform.context_memory import (
    ArtifactExpectation, CanonicalEvaluationSession, CanonicalEvaluationTurn,
    ContextUnitType, MemoryExpectation, RequiredContextUnit,
    SessionTaskSuccessContract,
)
from eval_platform.contracts import (
    AnnotationMetadata, AnnotationStatus, DatasetSplit, Difficulty, ExpectedBehavior,
    IdentitySpec, ResponseType, SuccessCriterion, TaskCategory, TaskSuccessContract,
)


def _identity(name: str, *, user: str = "user:phase4", tenant: str = "tenant:phase4") -> IdentitySpec:
    return IdentitySpec(
        tenant_id=tenant, user_id=user, conversation_id=f"conversation:{name}",
        thread_id=f"thread:{name}", session_id=f"session:{name}", region="CN",
    )


def _contract(*criteria: SuccessCriterion) -> TaskSuccessContract:
    return TaskSuccessContract(tuple(criteria or (SuccessCriterion.RESPONSE_TYPE_CORRECT,)))


def _turn(
    turn_id: str, index: int, text: str, *, response: ResponseType = ResponseType.ANSWER,
    context_units=(), memory: MemoryExpectation | None = None, artifact: ArtifactExpectation | None = None,
) -> CanonicalEvaluationTurn:
    return CanonicalEvaluationTurn(
        turn_id=turn_id, turn_index=index, user_input=text,
        expected_behavior=ExpectedBehavior(response_type=response),
        task_success_contract=_contract(SuccessCriterion.RESPONSE_TYPE_CORRECT),
        required_context_units=tuple(context_units),
        memory_expectations=memory or MemoryExpectation(),
        artifact_expectations=artifact or ArtifactExpectation(),
        annotation_status=AnnotationStatus.MODEL_GENERATED_UNREVIEWED,
    )


def _unit(unit_id: str, kind: ContextUnitType, description: str, source_ref: str) -> RequiredContextUnit:
    return RequiredContextUnit(unit_id, kind, description, source_ref=source_ref)


def build_phase4_candidate_sessions() -> tuple[CanonicalEvaluationSession, ...]:
    ann = AnnotationMetadata(
        annotation_status=AnnotationStatus.MODEL_GENERATED_UNREVIEWED,
        annotated_by=("phase4_seed_builder",), annotation_version="phase4-seed-v1",
        review_notes="Candidate only; must be human-reviewed before formal Quality-Cost metrics.",
    )
    common = dict(schema_version="1.0", split=DatasetSplit.DEVELOPMENT, difficulty=Difficulty.MEDIUM, annotation_metadata=ann)
    sessions = [
        CanonicalEvaluationSession(
            session_id="p4_entity_carry", category=TaskCategory.TROUBLESHOOTING, subcategory="MULTI_STEP",
            tags=("ENTITY_CARRY_OVER", "SLOT_CARRY_OVER", "FOLLOW_UP_QUERY"), initial_identity=_identity("p4_entity_carry"),
            turns=(
                _turn("t1",0,"我的冰箱 FR-200 出现 E12。"),
                _turn("t2",1,"这个问题严重吗？", context_units=(
                    _unit("product_model",ContextUnitType.ENTITY,"active product model FR-200","turn:t1:product_model"),
                    _unit("error_code",ContextUnitType.SLOT,"error code E12","turn:t1:error_code"),)),
                _turn("t3",2,"这种情况保修吗？", context_units=(
                    _unit("product_model",ContextUnitType.ENTITY,"active product model FR-200","turn:t1:product_model"),
                    _unit("error_code",ContextUnitType.SLOT,"error code E12","turn:t1:error_code"),)),
            ), session_success_contract=SessionTaskSuccessContract(required_turn_ids=("t2","t3")), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_user_correction", category=TaskCategory.KNOWLEDGE_QA, subcategory="EXACT_SPEC",
            tags=("USER_CORRECTION", "FACT_SUPERSESSION", "STALE_MEMORY_RESISTANCE"), initial_identity=_identity("p4_user_correction"),
            turns=(
                _turn("t1",0,"我的型号是 FR-100。"),
                _turn("t2",1,"等等，我看错了，是 FR-200。"),
                _turn("t3",2,"这个型号的保修期多久？", context_units=(
                    _unit("active_model",ContextUnitType.ENTITY,"corrected active model FR-200","turn:t2:product_model"),),
                    memory=MemoryExpectation(memory_dependent=True, superseded_fact_ids=("model:FR-100",), allowed_fact_ids=("model:FR-200",))),
            ), session_success_contract=SessionTaskSuccessContract(require_no_memory_contamination=True), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_topic_switch", category=TaskCategory.TROUBLESHOOTING, subcategory="MULTI_STEP",
            tags=("TOPIC_SWITCH", "RETURN_TO_PREVIOUS_TOPIC"), initial_identity=_identity("p4_topic_switch"),
            turns=(
                _turn("t1",0,"我的冰箱 E12 怎么处理？"),
                _turn("t2",1,"我这个订单是什么时候买的？"),
                _turn("t3",2,"顺便问一下之前那个 E12 还需要维修吗？", context_units=(
                    _unit("previous_issue",ContextUnitType.SLOT,"return to previous E12 troubleshooting topic","turn:t1:error_code"),)),
            ), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_private_policy", category=TaskCategory.MIXED_KNOWLEDGE_STRUCTURED, subcategory="ORDER_POLICY",
            tags=("PRIVATE_IDENTITY_CONTINUITY", "WORKING_MEMORY_REUSE", "STRUCTURED_PLUS_DOCUMENT"), initial_identity=_identity("p4_private_policy"),
            turns=(
                _turn("t1",0,"我的订单 ORD-001 是什么时候买的？"),
                _turn("t2",1,"那我现在还能退吗？", context_units=(
                    _unit("order_id",ContextUnitType.PREVIOUS_TOOL_RESULT_REF,"previous order identity","record:order:ORD-001"),),
                    memory=MemoryExpectation(memory_dependent=True)),
            ), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_region_supersession", category=TaskCategory.KNOWLEDGE_QA, subcategory="REGION_POLICY",
            tags=("FACT_SUPERSESSION", "STALE_MEMORY_RESISTANCE"), initial_identity=_identity("p4_region_supersession"),
            turns=(
                _turn("t1",0,"我在上海使用。"),
                _turn("t2",1,"我现在已经搬到北京了。"),
                _turn("t3",2,"这个政策现在适用吗？", context_units=(
                    _unit("active_region",ContextUnitType.SLOT,"latest region Beijing","turn:t2:region"),),
                    memory=MemoryExpectation(memory_dependent=True, superseded_fact_ids=("region:Shanghai",), allowed_fact_ids=("region:Beijing",))),
            ), session_success_contract=SessionTaskSuccessContract(require_no_memory_contamination=True), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_irrelevant_old_context", category=TaskCategory.KNOWLEDGE_QA, subcategory="FAQ",
            tags=("IRRELEVANT_OLD_CONTEXT", "OVER_CONTEXT"), initial_identity=_identity("p4_irrelevant_old_context"),
            turns=(
                _turn("t1",0,"之前我问过洗衣机 WM-100 的滤芯。"),
                _turn("t2",1,"现在只看冰箱 FR-200，E12 是什么意思？", context_units=(
                    _unit("current_model",ContextUnitType.ENTITY,"current entity FR-200","turn:t2:product_model"),)),
                _turn("t3",2,"需要立刻停机吗？", context_units=(
                    _unit("current_model",ContextUnitType.ENTITY,"current entity FR-200","turn:t2:product_model"),)),
            ), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_long_term_reuse", category=TaskCategory.KNOWLEDGE_QA, subcategory="REGION_POLICY",
            tags=("LONG_TERM_MEMORY_REUSE",), initial_identity=_identity("p4_long_term_reuse"),
            turns=(
                _turn("t1",0,"以后售后政策请按北京地区回答。"),
                _turn("t2",1,"退货政策是什么？", context_units=(
                    _unit("region_memory",ContextUnitType.MEMORY_FACT,"remembered preferred region","memory:region:beijing"),),
                    memory=MemoryExpectation(memory_dependent=True, required_fact_ids=("memory:region:beijing",), allowed_fact_ids=("memory:region:beijing",))),
            ), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_artifact_reuse", category=TaskCategory.KNOWLEDGE_QA, subcategory="MULTI_DOCUMENT",
            tags=("ARTIFACT_REUSE",), initial_identity=_identity("p4_artifact_reuse"),
            turns=(
                _turn("t1",0,"请先帮我整理这次检索结果。"),
                _turn("t2",1,"继续基于刚才的结果比较两条政策。", context_units=(
                    _unit("prior_artifact",ContextUnitType.ARTIFACT_REF,"previous retrieval artifact","artifact:phase4:policy"),),
                    artifact=ArtifactExpectation(required_artifact_ids=("artifact:phase4:policy",))),
            ), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_pronoun_reference", category=TaskCategory.TROUBLESHOOTING, subcategory="MISSING_INFORMATION",
            tags=("PRONOUN_REFERENCE", "ENTITY_CARRY_OVER"), initial_identity=_identity("p4_pronoun_reference"),
            turns=(
                _turn("t1",0,"FR-200 的压缩机声音突然变大。"),
                _turn("t2",1,"它正常吗？", context_units=(
                    _unit("pronoun_entity",ContextUnitType.ENTITY,"pronoun refers to FR-200","turn:t1:product_model"),)),
            ), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_cross_session_guard", category=TaskCategory.SAFETY_GOVERNANCE, subcategory="USER_ISOLATION",
            tags=("CROSS_SESSION_ISOLATION", "WORKING_MEMORY_REUSE"), initial_identity=_identity("p4_cross_session_guard"),
            turns=(
                _turn("t1",0,"这是一个新的会话，我现在谈 WM-100。"),
                _turn("t2",1,"它的状态是什么？", memory=MemoryExpectation(memory_dependent=True, disallow_cross_session_working_memory=True)),
            ), session_success_contract=SessionTaskSuccessContract(require_no_memory_contamination=True), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_cross_user_guard", category=TaskCategory.SAFETY_GOVERNANCE, subcategory="USER_ISOLATION",
            tags=("CROSS_USER_ISOLATION",), initial_identity=_identity("p4_cross_user_guard", user="user:phase4-a"),
            turns=(
                _turn("t1",0,"只使用属于我自己的历史信息。"),
                _turn("t2",1,"我之前的产品型号是什么？", memory=MemoryExpectation(memory_dependent=True)),
            ), session_success_contract=SessionTaskSuccessContract(require_no_memory_contamination=True), **common,
        ),
        CanonicalEvaluationSession(
            session_id="p4_cross_tenant_guard", category=TaskCategory.SAFETY_GOVERNANCE, subcategory="TENANT_ISOLATION",
            tags=("CROSS_TENANT_ISOLATION",), initial_identity=_identity("p4_cross_tenant_guard", tenant="tenant:phase4-a"),
            turns=(
                _turn("t1",0,"查询我这个租户自己的历史信息。"),
                _turn("t2",1,"之前记录的型号是什么？", memory=MemoryExpectation(memory_dependent=True)),
            ), session_success_contract=SessionTaskSuccessContract(require_no_memory_contamination=True), **common,
        ),
    ]
    return tuple(sessions)


__all__ = ["build_phase4_candidate_sessions"]
