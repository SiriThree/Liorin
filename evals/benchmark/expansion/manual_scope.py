"""Phase E1-R source-preserving Manual Fact Scope contracts and repair registry.

The registry is intentionally deterministic and corpus-bound.  It narrows the
query around the AtomicFact selected by E0; it never swaps entity/product/manual/
section/source fact and never uses Production or a Judge to choose the question.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping


class FactGranularity(StrEnum):
    ATOMIC_ACTION = "ATOMIC_ACTION"
    ATOMIC_FACT = "ATOMIC_FACT"
    CONDITIONAL_ACTION = "CONDITIONAL_ACTION"
    TROUBLESHOOTING_STEP = "TROUBLESHOOTING_STEP"
    PROCEDURE_STEP = "PROCEDURE_STEP"
    FEATURE = "FEATURE"
    COMPATIBILITY = "COMPATIBILITY"
    LIMITATION = "LIMITATION"
    SAFETY_INSTRUCTION = "SAFETY_INSTRUCTION"
    MULTI_FACT_DEPENDENT = "MULTI_FACT_DEPENDENT"
    FRAGMENT_ONLY = "FRAGMENT_ONLY"


class RepairType(StrEnum):
    SINGLE_FACT_TARGETING = "SINGLE_FACT_TARGETING"
    CONDITION_ACTION_TARGETING = "CONDITION_ACTION_TARGETING"
    SYMPTOM_STEP_TARGETING = "SYMPTOM_STEP_TARGETING"
    SPECIFIC_OPERATION_TARGETING = "SPECIFIC_OPERATION_TARGETING"
    MINIMAL_FACT_GROUP = "MINIMAL_FACT_GROUP"
    NOT_REPAIRABLE_DETERMINISTICALLY = "NOT_REPAIRABLE_DETERMINISTICALLY"


@dataclass(frozen=True)
class ManualFactScope:
    candidate_id: str
    document_id: str
    section_id: str
    selected_fact_id: str
    selected_fact_text: str
    source_fact_type: str
    fact_granularity: str
    independently_askable: bool
    required_context: tuple[str, ...]
    condition: str | None
    action: str | None
    symptom: str | None
    object: str | None
    constraint: str | None
    step_order: str | None
    related_fact_ids: tuple[str, ...]
    coherent_group_required: bool
    coherent_group_fact_ids: tuple[str, ...]
    repairable: bool
    repair_reason: str
    repair_type: str
    intent_id: str
    question_body: str

    def to_state(self) -> dict[str, Any]:
        row = asdict(self)
        for key in ("required_context", "related_fact_ids", "coherent_group_fact_ids"):
            row[key] = list(row[key])
        return row


# The keys are the exact E0-selected AtomicFact IDs.  Question bodies contain no
# product/model identity and no answer value; the Structured source therefore
# remains necessary for routing to the correct manual.
_REPAIR_SPECS: dict[str, dict[str, Any]] = {
    "af:4df72d7f8b0bbd0c": dict(
        granularity="FRAGMENT_ONLY", repair_type="MINIMAL_FACT_GROUP", intent="DISASSEMBLY_SAFETY_RISK",
        question="如果我自行拆卸或改装这台设备，手册提示会带来哪些安全风险？",
        context=("未经授权的拆卸或改装",), related=("af:03dd5fba6e61d2f3",), group=("af:03dd5fba6e61d2f3",),
        condition="用户考虑未经授权拆卸或改装", action=None, symptom=None, object="设备", constraint="安全风险",
        independently=False, reason="Selected sentence is a pronoun-dependent consequence; pair with the immediately preceding no-disassembly context only.",
    ),
    "af:0c067480b5b45bc4": dict(
        granularity="PROCEDURE_STEP", repair_type="SPECIFIC_OPERATION_TARGETING", intent="CONNECTOR_INSTALL_LOCATION",
        question="安装过程中，连接件应该装在什么位置？", context=(), related=(), group=(),
        condition=None, action="安装连接件", symptom=None, object="连接件", constraint="安装位置", independently=True,
        reason="The selected installation step has one deterministic location answer.",
    ),
    "af:871807f11ccf667a": dict(
        granularity="CONDITIONAL_ACTION", repair_type="CONDITION_ACTION_TARGETING", intent="SEAT_TOO_HIGH_ADJUSTMENT",
        question="如果使用时腿伸得太直，或者脚踩不到踏板，座椅应该往哪个方向调？", context=(), related=(), group=(),
        condition="腿部过直或脚无法踩到脚踏板", action="调节座椅", symptom="骑行姿势不合适", object="座椅", constraint="调节方向", independently=True,
        reason="Condition and corrective direction are fully contained in the selected fact.",
    ),
    "af:29716995e876eb51": dict(
        granularity="CONDITIONAL_ACTION", repair_type="CONDITION_ACTION_TARGETING", intent="LOW_POWER_FEATURE_RECOVERY",
        question="如果语音助手或快捷回复因为电量过低暂时不能用，怎样恢复这些功能？", context=("低电量限制功能",), related=(), group=(),
        condition="语音助手或快捷回复因电量过低不可用", action="恢复功能", symptom="功能不可用", object="语音助手或快捷回复", constraint=None, independently=True,
        reason="The selected fact directly states the recovery action for the two unavailable low-power features.",
    ),
    "af:6665c7729797e2a4": dict(
        granularity="LIMITATION", repair_type="SINGLE_FACT_TARGETING", intent="FAIL_SAFE_SUITABILITY",
        question="如果我的使用场景要求设备发生故障时仍保持故障安全运行，这台设备适合这种场景吗？", context=(), related=(), group=(),
        condition="场景要求故障安全运行", action=None, symptom=None, object="设备", constraint="适用性", independently=True,
        reason="The selected limitation is independently decidable from a concrete user requirement.",
    ),
    "af:1f4652da8ea48b5e": dict(
        granularity="CONDITIONAL_ACTION", repair_type="MINIMAL_FACT_GROUP", intent="UNSTABLE_FLOOR_DOOR_ADJUSTMENT",
        question="如果设备的门关不上，而且安装地面不平或放置不稳，应该怎样调整底脚？", context=("安装地面不平或放置不稳",), related=("af:597fee9b44836804",), group=("af:597fee9b44836804",),
        condition="门无法正常关闭且设备放置不稳", action="调节底脚", symptom="门无法正常关闭", object="底脚", constraint="调整方式", independently=False,
        reason="The corrective action needs the immediately paired cause fact to distinguish it from another door-closing cause in the same section.",
    ),
    "af:88323694257671dd": dict(
        granularity="CONDITIONAL_ACTION", repair_type="CONDITION_ACTION_TARGETING", intent="WARRANTY_RETURN_DEALER_UNAVAILABLE",
        question="如果我所在地区属于手册所述的北美、欧洲及澳新以外地区，产品仍在保修期但无法退回经销商，下一步应该联系谁？", context=("手册明确的区域条件", "产品仍在保修期且无法退回经销商"), related=(), group=(),
        condition="适用该手册区域条件且保修期内无法退回经销商", action="寻求协助", symptom=None, object="售后渠道", constraint="下一联系人", independently=True,
        reason="The source explicitly scopes this instruction by region; the repaired query carries that source-defined condition instead of inventing region metadata.",
    ),
    "af:9553641a3bb85c10": dict(
        granularity="FRAGMENT_ONLY", repair_type="MINIMAL_FACT_GROUP", intent="TRANSFER_SWITCH_PURPOSE",
        question="如果这台设备要接入建筑物电气系统，安装隔离（转换）开关主要是为了防止什么？", context=("接入建筑物电气系统前安装隔离开关",), related=("af:b3865d8b1c39e97d",), group=("af:b3865d8b1c39e97d",),
        condition="设备接入建筑物电气系统", action=None, symptom=None, object="隔离（转换）开关", constraint="主要防护目的", independently=False,
        reason="The selected 'this prevents' sentence requires the preceding switch-installation context, but only that local fact is necessary.",
    ),
    "af:2a8c3607157d3621": dict(
        granularity="TROUBLESHOOTING_STEP", repair_type="SYMPTOM_STEP_TARGETING", intent="HVAC_NO_RESPONSE_FINAL_STEP",
        question="供暖或制冷系统无响应时，手册要求如何处理炉门，并等待多长时间观察响应？", context=(), related=(), group=(),
        condition="供暖或制冷系统无响应", action="确认炉门并等待", symptom="系统无响应", object="炉门", constraint="等待时间", independently=True,
        reason="The selected step contains both the door check and the bounded wait time.",
    ),
    "af:88e6a7c9892493a6": dict(
        granularity="CONDITIONAL_ACTION", repair_type="CONDITION_ACTION_TARGETING", intent="ENGINE_IDLE_T_SCREW",
        question="如果这台设备的发动机无法怠速运转，T 螺钉应该怎样调到正常怠速？", context=(), related=(), group=(),
        condition="发动机无法怠速运转", action="调节 T 螺钉", symptom="无法怠速", object="T 螺钉", constraint="旋转方向和终点", independently=True,
        reason="The selected fact is a complete condition-to-adjustment rule.",
    ),
    "af:7b78d2023ae42834": dict(
        granularity="LIMITATION", repair_type="SINGLE_FACT_TARGETING", intent="STARTER_PRESS_DURATION_RISK",
        question="为什么单次连续按启动开关不应该超过 5 秒？", context=(), related=(), group=(),
        condition="连续启动超过 5 秒", action=None, symptom=None, object="启动开关", constraint="超过时限的后果", independently=True,
        reason="The selected fact directly states the consequence of exceeding the five-second start duration.",
    ),
    "af:7ea51bcd56db9e7d": dict(
        granularity="MULTI_FACT_DEPENDENT", repair_type="MINIMAL_FACT_GROUP", intent="LOW_OIL_RESTART_CONSEQUENCE",
        question="如果机油油位过低已经导致发动机停机，但还没有补充机油，会发生什么？", context=("机油油位过低会触发停机",), related=("af:8cf38b2c301664ce",), group=("af:8cf38b2c301664ce",),
        condition="低机油触发停机且未补充机油", action=None, symptom="发动机已停机", object="发动机", constraint="能否再次启动", independently=False,
        reason="The selected consequence needs the preceding low-oil shutdown condition; the two-fact context is minimal.",
    ),
    "af:91599d5e7eb87f50": dict(
        granularity="SAFETY_INSTRUCTION", repair_type="SPECIFIC_OPERATION_TARGETING", intent="DISPOSAL_CHILD_SAFETY",
        question="处理废旧设备前，为了儿童安全，电源线和机门锁扣分别应该怎么处理？", context=(), related=(), group=(),
        condition="处理废旧设备前", action="儿童安全处理", symptom=None, object="电源线和机门锁扣", constraint="两项处理动作", independently=True,
        reason="The selected safety instruction is a complete two-action disposal requirement.",
    ),
    "af:632976dcb665fc3b": dict(
        granularity="TROUBLESHOOTING_STEP", repair_type="SYMPTOM_STEP_TARGETING", intent="PRE_SERVICE_POWER_CYCLE",
        question="联系售后前，完成基础排查后，还可以做哪一步来确认故障是否仍存在？", context=("已完成基础故障排查",), related=(), group=(),
        condition="联系售后前且基础排查已完成", action="再次确认故障", symptom="故障仍可能存在", object="设备电源", constraint="确认步骤", independently=True,
        reason="The selected power-cycle check is an independently askable next action before service escalation.",
    ),
    "af:11979fccc4d0dc5e": dict(
        granularity="CONDITIONAL_ACTION", repair_type="CONDITION_ACTION_TARGETING", intent="CHARGER_SECOND_BATTERY_SAME_ERROR",
        question="如果换上另一块电池后仍出现和原电池相同的故障提示，下一步应该怎么处理？", context=(), related=(), group=(),
        condition="新电池与原电池出现相同故障提示", action="下一步处理", symptom="相同故障提示", object="充电器和电池组", constraint=None, independently=True,
        reason="The selected troubleshooting branch contains a complete condition and escalation action.",
    ),
    "af:7e51d3a075700150": dict(
        granularity="LIMITATION", repair_type="SINGLE_FACT_TARGETING", intent="BATTERY_CHARGE_LOW_TEMP_THRESHOLD",
        question="环境温度低到多少时，电池会无法充电？", context=(), related=(), group=(),
        condition="低温充电", action=None, symptom="电池无法充电", object="电池", constraint="最低温度阈值", independently=True,
        reason="The selected fact provides one explicit charge-blocking temperature threshold.",
    ),
    "af:21e5b38c4df4e0e9": dict(
        granularity="CONDITIONAL_ACTION", repair_type="MINIMAL_FACT_GROUP", intent="POLARIZED_PLUG_STILL_NOT_INSERTING",
        question="如果插头无法完全插入插座，翻转插头重试后仍然插不进去，下一步应该怎么办？", context=("先翻转插头重试",), related=("af:466944f6f2267475",), group=("af:466944f6f2267475",),
        condition="翻转极性插头后仍无法插入", action="下一步处理", symptom="插头无法插入", object="插头/插座", constraint=None, independently=False,
        reason="The escalation fact depends on the immediately preceding retry step; the two-fact context is minimal.",
    ),
    "af:1cbe5f5d056da473": dict(
        granularity="ATOMIC_ACTION", repair_type="SPECIFIC_OPERATION_TARGETING", intent="ROUTINE_CLEANING_MAINTENANCE",
        question="为了保持运行性能并减少故障，应该定期做什么维护？", context=(), related=(), group=(),
        condition="日常维护", action="维护动作", symptom=None, object="设备", constraint="保持性能并减少故障", independently=True,
        reason="The selected maintenance instruction has one clear recommended action.",
    ),
    "af:a33997d4c04f4929": dict(
        granularity="SAFETY_INSTRUCTION", repair_type="SPECIFIC_OPERATION_TARGETING", intent="UNPLUG_BEFORE_MAINTENANCE",
        question="设备不使用、进行保养或故障排查前，电源方面必须先做什么？", context=(), related=(), group=(),
        condition="不使用、保养或排障前", action="电源安全操作", symptom=None, object="电源", constraint="必须先做的动作", independently=True,
        reason="The selected safety prerequisite is explicit and independently askable.",
    ),
    "af:1dd8c5a1f085ced2": dict(
        granularity="TROUBLESHOOTING_STEP", repair_type="SYMPTOM_STEP_TARGETING", intent="BIOS_USB_MOUSE_CHECK",
        question="这台设备无法工作时，手册建议在系统 BIOS 里检查哪项功能是否启用？", context=(), related=(), group=(),
        condition="设备无法工作", action="检查 BIOS 设置", symptom="设备无法工作", object="系统 BIOS 功能", constraint="要检查的功能", independently=True,
        reason="The selected troubleshooting step maps one symptom to one BIOS setting check without revealing the product identity.",
    ),
}


def repair_spec(selected_fact_id: str) -> Mapping[str, Any] | None:
    return _REPAIR_SPECS.get(str(selected_fact_id))


def build_fact_scope(candidate_id: str, fact: Mapping[str, Any], *, document_id: str, section_id: str) -> ManualFactScope:
    spec = repair_spec(str(fact["fact_id"]))
    if spec is None:
        return ManualFactScope(
            candidate_id=candidate_id, document_id=document_id, section_id=section_id,
            selected_fact_id=str(fact["fact_id"]), selected_fact_text=str(fact["normalized_value"]),
            source_fact_type=str(fact.get("fact_type") or "UNKNOWN"), fact_granularity=FactGranularity.FRAGMENT_ONLY.value,
            independently_askable=False, required_context=(), condition=None, action=None, symptom=None, object=None,
            constraint=None, step_order=None, related_fact_ids=(), coherent_group_required=False,
            coherent_group_fact_ids=(), repairable=False, repair_reason="No deterministic source-preserving repair rule is frozen for this selected AtomicFact.",
            repair_type=RepairType.NOT_REPAIRABLE_DETERMINISTICALLY.value, intent_id="UNRESOLVED_SCOPE", question_body="",
        )
    gran = str(spec["granularity"])
    return ManualFactScope(
        candidate_id=candidate_id, document_id=document_id, section_id=section_id,
        selected_fact_id=str(fact["fact_id"]), selected_fact_text=str(fact["normalized_value"]),
        source_fact_type=str(fact.get("fact_type") or "UNKNOWN"), fact_granularity=gran,
        independently_askable=bool(spec.get("independently", True)), required_context=tuple(spec.get("context") or ()),
        condition=spec.get("condition"), action=spec.get("action"), symptom=spec.get("symptom"), object=spec.get("object"),
        constraint=spec.get("constraint"), step_order=spec.get("step_order"), related_fact_ids=tuple(spec.get("related") or ()),
        coherent_group_required=bool(spec.get("group")), coherent_group_fact_ids=tuple(spec.get("group") or ()),
        repairable=True, repair_reason=str(spec["reason"]), repair_type=str(spec["repair_type"]), intent_id=str(spec["intent"]),
        question_body=str(spec["question"]),
    )
