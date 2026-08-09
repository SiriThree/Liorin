"""Phase F0 deterministic task-plan and candidate construction."""
from __future__ import annotations

import hashlib, re
from collections import Counter, defaultdict
from typing import Iterable

from .troubleshooting_candidate import RecoveryEligibilityDraft, TroubleshootingCandidate, TroubleshootingSourceUnit

FAMILY_PHRASE={
    "START_OR_RESPONSE_FAILURE":"设备无法启动或没有响应",
    "CHARGING_OR_BATTERY":"设备充电或电池状态异常",
    "MOTION_OR_OPERATION_FAILURE":"设备无法正常运行",
    "WATER_FLOW_OR_DRAINAGE":"设备抽水或排水异常",
    "DOOR_OR_MECHANICAL":"门体或机械部件异常",
    "ABNORMAL_NOISE":"设备出现异常噪音",
    "HEAT_SMELL_OR_SMOKE":"设备出现过热、异味或冒烟",
    "INDICATOR_OR_DISPLAY":"指示灯或显示状态异常",
    "CONNECTIVITY_OR_INTERFACE":"连接或接口无法正常工作",
    "CAMERA_CAPTURE_OR_STORAGE":"拍摄或存储功能异常",
    "MAINTENANCE":"维护或清洁相关异常",
    "ERROR_CODE":"设备显示错误码",
    "OTHER_TROUBLESHOOTING":"设备出现异常",
}
BROAD_MARKERS=("相关要点","介绍一下","有哪些注意事项","怎么排查？","这个故障怎么办？")


def _sha(value: str, n: int=16) -> str: return hashlib.sha256(value.encode()).hexdigest()[:n]
def _cid(unit: TroubleshootingSourceUnit, task: str, context: str) -> str: return f"TRBL-{_sha(unit.source_unit_id+'|'+task+'|'+context).upper()}"
def _scenario(unit: TroubleshootingSourceUnit, key: str) -> str: return f"SCN-{_sha(unit.source_unit_id+'|'+key,12).upper()}"
def _procedure(unit: TroubleshootingSourceUnit) -> str: return f"PROC-{_sha(unit.source_unit_id,12).upper()}"
def _dedup(unit: TroubleshootingSourceUnit, task: str, context: tuple[str,...], steps: tuple[str,...], trigger: str|None) -> str:
    return _sha("|".join([unit.symptom_family,unit.source_unit_id,task,",".join(sorted(context)),",".join(steps),trigger or ""]),32)


def _balanced(units: list[TroubleshootingSourceUnit], n: int, predicate=lambda u: True, usage: Counter|None=None) -> list[TroubleshootingSourceUnit]:
    usage=usage or Counter()
    pool=[u for u in units if predicate(u)]
    # round-robin by product, then favor under-used source units and products
    by=defaultdict(list)
    for u in pool: by[u.product_id or "NONE"].append(u)
    for rows in by.values(): rows.sort(key=lambda u:(usage[u.source_unit_id],-len(u.diagnostic_steps),u.source_unit_id))
    product_use=Counter(); out=[]
    while len(out)<n:
        choices=[]
        for p,rows in by.items():
            cand=next((u for u in rows if u not in out),None)
            if cand: choices.append((product_use[p],usage[cand.source_unit_id],p,cand))
        if not choices: break
        _,_,p,u=min(choices,key=lambda x:(x[0],x[1],x[2],x[3].source_unit_id))
        out.append(u); product_use[p]+=1
    return out


def _self_service_steps(unit: TroubleshootingSourceUnit):
    return tuple(s for s in unit.diagnostic_steps if not s.escalation)

def _step_ids(unit: TroubleshootingSourceUnit, count: int=1) -> tuple[str,...]:
    steps=_self_service_steps(unit)
    return tuple(s.step_id for s in steps[:count])

def _first_condition(unit: TroubleshootingSourceUnit) -> str|None:
    escalation_facts={s.source_fact_id for s in unit.diagnostic_steps if s.escalation}
    for b in unit.conditional_branches:
        if b.get("source_fact_id") in escalation_facts:
            continue
        c=str(b.get("condition") or "").strip()
        if any(g in c for g in ("任何问题","其他问题","有问题")) and "问题依旧" not in c:
            continue
        if c: return c
    return None


def _query_symptom(unit: TroubleshootingSourceUnit) -> str:
    text=(unit.symptom or "").strip()
    text=re.sub(r"^问题[：:]?\s*", "", text)
    text=re.sub(r"^认为(.+?出现故障)$", r"\1", text)
    explicit=("无法","异常","故障","无响应","积水","过热","发热","冒烟","烧焦味","闪烁","不工作","不能","未响应","没反应")
    if any(k in text for k in explicit):
        return text
    if unit.symptom_family != "OTHER_TROUBLESHOOTING":
        return FAMILY_PHRASE.get(unit.symptom_family,text or "设备出现异常")
    return text or "设备出现异常"

def _condition_step(unit: TroubleshootingSourceUnit, source_fact_id: str) -> tuple[str,...]:
    return tuple(s.step_id for s in unit.diagnostic_steps if s.source_fact_id == source_fact_id)[:1]

def _context_clarification_spec(unit: TroubleshootingSourceUnit):
    """Return a natural missing-context/control pair for a source-backed branch, if one exists."""
    for branch in unit.conditional_branches:
        cond=str(branch.get("condition") or "").strip()
        fid=str(branch.get("source_fact_id") or "")
        step_ids=_condition_step(unit,fid)
        if not cond or not step_ids:
            continue
        p=unit.product_name
        symptom=_query_symptom(unit)
        if "问题依旧" in cond or "仍无法解决" in cond or "无法解决" == cond:
            return ("previous_action_result",
                    f"我的{p}出现“{symptom}”。我已经按手册做过前一步，但没有说明处理后问题是否仍然存在。现在应该继续怎么处理？",
                    f"我的{p}出现“{symptom}”。我按手册做过前一步后问题仍然存在，下一步应该怎么处理？",step_ids,cond)
        if "新电池组" in cond:
            return ("new_battery_test_result",
                    f"我的{p}充电指示异常，我已经换一块新电池测试过，但没有说明新电池的充电表现。下一步应该怎么判断？",
                    f"我的{p}充电指示异常；测试结果是“{cond}”。根据手册下一步应该怎么处理？",step_ids,cond)
        if "不发热" in cond:
            return ("charger_temperature_state",
                    f"我的{p}电池充不上电，但没有说明充电器工作时是否发热。下一步应该先确认什么？",
                    f"我的{p}电池充不上电，并且已经确认充电器“{cond}”。根据手册下一步应该怎么处理？",step_ids,cond)
        if any(k in cond for k in ("发热","冒烟","烧焦味","过热")):
            return ("safety_symptom_presence",
                    f"我的{p}状态异常，但没有说明是否伴随发热、冒烟、烧焦味或过热。继续处理前需要先确认什么？",
                    f"我的{p}出现“{cond}”。根据手册现在应该怎么处理？",step_ids,cond)
        if any(k in cond for k in ("便携式电源","直流转交流","发电机")):
            return ("power_source_type",
                    f"我的{p}充电器出现异常指示，但没有说明它是否接在发电机、便携式电源或直流转交流电源上。下一步应该先确认什么？",
                    f"我的{p}充电器出现异常指示，并且当前“{cond}”。根据手册该怎么判断？",step_ids,cond)
        if "指示灯上下移动" in cond:
            return ("indicator_movement_pattern",
                    f"我的{p}在自检时指示灯在变化，但我没看清具体移动方式。现在能直接判断是否故障吗？",
                    f"我的{p}自检时已经确认“{cond}”。根据手册这表示什么？",step_ids,cond)
        if "无法排水" in cond:
            return ("drainage_state",
                    f"我的{p}清洁时排水状态不正常，但没有说明现在是否完全无法排水。下一步应该先确认什么？",
                    f"我的{p}清洁时已经确认“{cond}”。根据手册下一步应该怎么处理？",step_ids,cond)
    return None

def _meaningful_handoff_step(unit: TroubleshootingSourceUnit):
    generic=("其他问题需要进一步协助","任何问题")
    candidates=[s for s in unit.diagnostic_steps if s.escalation and not any(g in (s.precondition or "") for g in generic)]
    with_cond=[s for s in candidates if s.precondition and len(s.precondition.strip()) >= 3]
    if with_cond:
        return with_cond[0]
    if unit.stop_conditions and candidates:
        return candidates[0]
    return None


def _handoff_query(unit: TroubleshootingSourceUnit, step) -> tuple[str, tuple[str,...]]:
    cond=(step.precondition or "").strip()
    p=unit.product_name
    if cond:
        if "健康问题或症状" in cond:
            return f"我或孩子在使用{p}时出现了手册所列的健康问题或症状。根据手册现在应该怎么处理？", ("product_name_or_model","escalation_precondition")
        if cond == "需维修":
            return f"我的{p}经过检查后已经确认需要维修。根据手册接下来应该怎么处理？", ("product_name_or_model","escalation_precondition")
        if "按照本章节说明仍无法解决问题" in cond:
            return f"我的{p}已经按本章节的排查步骤处理过，但问题仍未解决。根据手册下一步应该怎么处理？", ("product_name_or_model","previous_action_result")
        if cond == "无法解决":
            return f"我的{p}按手册完成排查后故障仍无法解决。下一步应该怎么处理？", ("product_name_or_model","previous_action_result")
        if "新电池组充电正常" in cond:
            return f"我的{p}充电异常；换一块新电池测试后，新电池可以正常充电。根据手册下一步应该怎么处理？", ("product_name_or_model","escalation_precondition")
        return f"我的{p}已经确认“{cond}”。根据手册下一步应该怎么处理？", ("product_name_or_model","escalation_precondition")
    return f"我的{p}出现“{_query_symptom(unit)}”。根据手册，这种情况下是否应该停止自行处理并寻求专业支持？", ("product_name_or_model","symptom")


def _candidate(unit: TroubleshootingSourceUnit, task_type: str, query: str, *, behavior_labels: tuple[str,...],
               expected_response: str="ANSWER", hidden: tuple[str,...]=(), known: tuple[str,...]=(), steps: tuple[str,...]=(),
               safety: tuple[str,...]=(), escalation: str|None=None, recovery_trigger: str|None=None,
               recovery_actions: tuple[str,...]=(), recovery_signals: tuple[str,...]=(), difficulty: str="MEDIUM",
               scenario_key: str|None=None, flags: tuple[str,...]=(), rejection: tuple[str,...]=()) -> TroubleshootingCandidate:
    scenario_key=scenario_key or task_type
    rec=RecoveryEligibilityDraft(bool(recovery_trigger),recovery_trigger,recovery_trigger,
        recovery_actions, tuple(a for a in ("CLARIFY","REWRITE","SUPPLEMENT","RELAX_FILTERS","HANDOFF") if a not in recovery_actions),
        "recover required source-backed step/context and preserve safety/handoff behavior" if recovery_trigger else None,
        False,False,recovery_signals)
    cid=_cid(unit,task_type,"|".join(hidden+known+steps)+(recovery_trigger or ""))
    expected={"response_type":expected_response,"clarification_required":expected_response=="CLARIFICATION",
              "required_clarification_slots":list(hidden) if expected_response=="CLARIFICATION" else [],
              "acceptable_clarification_slots":list(hidden) if expected_response=="CLARIFICATION" else [],
              "forbidden_assumptions":["do_not_guess_missing_context"] if expected_response=="CLARIFICATION" else [],
              "handoff_required":expected_response=="HANDOFF","handoff_reason":escalation if expected_response=="HANDOFF" else None,
              "answer_before_clarification_allowed":False if expected_response=="CLARIFICATION" else True}
    return TroubleshootingCandidate(
        candidate_id=cid,status="CANDIDATE",source_unit_id=unit.source_unit_id,product_id=unit.product_id,product_name=unit.product_name,
        semantic_family_id=unit.symptom_family,task_type=task_type,behavior_labels=behavior_labels,symptom=unit.symptom,
        user_known_context=known,hidden_required_context=hidden,expected_behavior_draft=expected,required_steps=steps,
        conditional_logic=tuple(str(x.get("condition")) for x in unit.conditional_branches[:3] if x.get("condition")),
        safety_requirements=safety,escalation_condition=escalation,recovery_eligibility=rec,candidate_query=query,
        source_fact_ids=unit.manual_fact_ids,source_section_ids=(unit.section_id,),difficulty=difficulty,
        procedure_family_id=_procedure(unit),scenario_family_id=_scenario(unit,scenario_key),
        split_group_keys={"document_family":unit.document_id,"product_family":unit.product_id or "NONE","source_unit_id":unit.source_unit_id,
                          "procedure_family_id":_procedure(unit),"scenario_family_id":_scenario(unit,scenario_key),"semantic_family_id":unit.symptom_family},
        dedup_signature=_dedup(unit,task_type,hidden+known,steps,recovery_trigger),quality_flags=flags,rejection_reasons=rejection)


def build_candidates(units: list[TroubleshootingSourceUnit]) -> list[TroubleshootingCandidate]:
    usable=[u for u in units if u.benchmark_usable]
    usage=Counter(); rows=[]; seen_query=set()
    def add(c):
        q=re.sub(r"\s+","",c.candidate_query).lower()
        if q in seen_query: return False
        seen_query.add(q); rows.append(c); usage[c.source_unit_id]+=1; return True

    # 18 direct controls: sufficient context and a single explicit first action.
    for u in _balanced(usable,40,lambda x:len(_self_service_steps(x))>=1 and not x.stop_conditions and x.symptom_family!="OTHER_TROUBLESHOOTING",usage):
        if len([r for r in rows if r.task_type=="DIRECT_TROUBLESHOOTING"])>=18: break
        q=f"我的{u.product_name}出现“{_query_symptom(u)}”。根据对应手册，第一步应该检查或处理什么？"
        add(_candidate(u,"DIRECT_TROUBLESHOOTING",q,behavior_labels=("DIRECT",),known=("product_name_or_model","symptom"),steps=_step_ids(u,1),difficulty="EASY"))

    # 14 multi-step / conditional cases.
    targets=_balanced(usable,40,lambda x:(len(_self_service_steps(x))>=2 or bool(_first_condition(x))) and x.symptom_family!="OTHER_TROUBLESHOOTING",usage)
    for u in targets:
        if sum(r.task_type in {"MULTI_STEP_TROUBLESHOOTING","CONDITIONAL_TROUBLESHOOTING"} for r in rows)>=14: break
        cond=_first_condition(u)
        if cond:
            qs=_query_symptom(u)
            if cond in qs or qs in cond:
                q=f"我的{u.product_name}出现“{cond}”。根据手册下一步应该怎么处理？"
            else:
                q=f"我的{u.product_name}出现“{qs}”。如果{cond}，下一步应该怎么处理？"
            task="CONDITIONAL_TROUBLESHOOTING"; labels=("CONDITIONAL",); n=1
        else:
            if u.step_order in {"ORDERED","PARTIALLY_ORDERED"}:
                q=f"我的{u.product_name}出现“{_query_symptom(u)}”。请按手册告诉我前两项关键排查步骤。"
            else:
                q=f"我的{u.product_name}出现“{_query_symptom(u)}”。请列出两项手册明确的检查或处理项，顺序不限。"
            task="MULTI_STEP_TROUBLESHOOTING"; labels=("MULTI_STEP",); n=2
        add(_candidate(u,task,q,behavior_labels=labels,known=("product_name_or_model","symptom","condition") if cond else ("product_name_or_model","symptom"),steps=_step_ids(u,n),difficulty="MEDIUM"))

    # Build cross-product ambiguity candidates. Use at most one product-missing case per symptom family
    # to avoid turning paraphrases into fake semantic diversity. Pair nine with full-context controls.
    fam_products=defaultdict(set)
    for u in usable: fam_products[u.symptom_family].add(u.product_id)
    amb=[u for u in usable if len(fam_products[u.symptom_family])>=2 and u.symptom_family!="OTHER_TROUBLESHOOTING"]
    chosen=[]; seen_fam=set()
    for u in _balanced(amb,40,lambda x:True,usage):
        if u.symptom_family in seen_fam: continue
        chosen.append(u); seen_fam.add(u.symptom_family)
        if len(chosen)>=9: break
    for pair_count,u in enumerate(chosen):
        phrase=FAMILY_PHRASE[u.symptom_family]
        sk=f"clarify-product-{u.symptom_family}"
        q1=f"设备出现“{phrase}”，我应该怎么处理？"
        add(_candidate(u,"CLARIFICATION_REQUIRED",q1,behavior_labels=("CLARIFICATION_REQUIRED",)+(('RECOVERY_ORIENTED',) if pair_count<6 else ()),
            expected_response="CLARIFICATION",hidden=("product_name_or_model",),known=("symptom",),steps=(),
            recovery_trigger="MISSING_REQUIRED_CONTEXT",recovery_actions=("CLARIFY",),recovery_signals=("CROSS_PRODUCT_AMBIGUITY",),difficulty="HARD",scenario_key=sk))
        q2=f"我的{u.product_name}出现“{phrase}”。请按对应手册告诉我第一步怎么处理。"
        add(_candidate(u,"SUFFICIENT_CONTEXT_NO_CLARIFICATION",q2,behavior_labels=("NO_CLARIFICATION_CONTROL",),known=("product_name_or_model","symptom"),steps=_step_ids(u,1),difficulty="MEDIUM",scenario_key=sk))

    # Source-backed missing-context clarification pairs from real conditional branches.
    # Each missing-context variant is paired with a sufficient-context control under the same scenario family.
    context_pairs=0
    for u in _balanced(usable,50,lambda x:bool(x.conditional_branches),usage):
        if context_pairs>=8:
            break
        spec=_context_clarification_spec(u)
        if not spec:
            continue
        slot,q_missing,q_full,target_steps,cond=spec
        sk=f"clarify-context-{u.source_unit_id}-{slot}"
        added=add(_candidate(u,"CLARIFICATION_REQUIRED",q_missing,behavior_labels=("CLARIFICATION_REQUIRED","RECOVERY_ORIENTED"),expected_response="CLARIFICATION",
            hidden=(slot,),known=("product_name_or_model","symptom"),steps=(),recovery_trigger="MISSING_REQUIRED_CONTEXT",
            recovery_actions=("CLARIFY",),recovery_signals=("SOURCE_BACKED_CONDITIONAL_CONTEXT",),difficulty="HARD",scenario_key=sk))
        if added:
            add(_candidate(u,"SUFFICIENT_CONTEXT_NO_CLARIFICATION",q_full,behavior_labels=("NO_CLARIFICATION_CONTROL","CONDITIONAL"),
                known=("product_name_or_model","symptom",slot),steps=target_steps,difficulty="MEDIUM",scenario_key=sk))
            context_pairs+=1

    # Additional sufficient-context controls so over-clarification is tested beyond paired product-missing cases.
    for u in _balanced(usable,20,lambda x:len(_self_service_steps(x))>=1 and x.symptom_family!="OTHER_TROUBLESHOOTING",usage):
        if sum(r.task_type=="SUFFICIENT_CONTEXT_NO_CLARIFICATION" for r in rows)>=12: break
        q=f"我的{u.product_name}出现“{_query_symptom(u)}”，具体产品和现象都已明确。请按手册直接给出首个处理动作。"
        add(_candidate(u,"SUFFICIENT_CONTEXT_NO_CLARIFICATION",q,behavior_labels=("NO_CLARIFICATION_CONTROL",),known=("product_name_or_model","symptom"),steps=_step_ids(u,1),difficulty="MEDIUM"))

    # 10 source-grounded handoff/escalation cases.
    for u in _balanced(usable,35,lambda x:bool(x.escalation_conditions),usage):
        if sum(r.task_type=="ESCALATION_HANDOFF" for r in rows)>=10: break
        esc_step=_meaningful_handoff_step(u)
        if not esc_step:
            continue
        q,known=_handoff_query(u,esc_step)
        add(_candidate(u,"ESCALATION_HANDOFF",q,behavior_labels=("HANDOFF",),expected_response="HANDOFF",known=known,
            steps=(),safety=u.safety_prerequisites,escalation=esc_step.source_fact_id,difficulty="HARD"))

    # 14 recovery-oriented challenge structures: rewrite for lexical mismatch, supplement for partial procedure.
    rewrite_map={
        "START_OR_RESPONSE_FAILURE":"按了开机但机器完全没反应",
        "CHARGING_OR_BATTERY":"怎么都充不进去电",
        "MOTION_OR_OPERATION_FAILURE":"设备有电但就是不工作",
        "WATER_FLOW_OR_DRAINAGE":"水路一直不正常",
        "DOOR_OR_MECHANICAL":"门或机械结构卡住了",
        "ABNORMAL_NOISE":"机器发出不正常的响声",
        "INDICATOR_OR_DISPLAY":"灯一直异常闪或者显示不对",
        "CONNECTIVITY_OR_INTERFACE":"怎么都连不上",
        "CAMERA_CAPTURE_OR_STORAGE":"拍不了或者存不下来",
        "MAINTENANCE":"保养后状态还是不正常",
        "HEAT_SMELL_OR_SMOKE":"机器发热并且味道不对",
        "OTHER_TROUBLESHOOTING":"设备状态不对但我不知道手册里叫什么",
    }
    rec_units=_balanced(usable,75,lambda x:len(_self_service_steps(x))>=1 and x.symptom_family!="OTHER_TROUBLESHOOTING",usage)
    rcount=0
    for u in rec_units:
        if rcount>=24: break
        if rcount%2==0 and u.symptom_family!="OTHER_TROUBLESHOOTING":
            phr=rewrite_map[u.symptom_family]
            q=f"我的{u.product_name}{phr}，应该怎么处理？"
            c=_candidate(u,"RECOVERY_ORIENTED_REWRITE",q,behavior_labels=("RECOVERY_ORIENTED",),known=("product_name_or_model","symptom"),steps=_step_ids(u,1),
                recovery_trigger="WRONG_SCOPE_RETRIEVAL",recovery_actions=("REWRITE","SUPPLEMENT"),recovery_signals=("MANUAL_TERMINOLOGY_MISMATCH",),difficulty="MEDIUM")
        else:
            if len(_self_service_steps(u))<2: continue
            q=f"我的{u.product_name}出现“{_query_symptom(u)}”。我已经按第一项建议处理过但问题还在，下一步应该怎么办？"
            c=_candidate(u,"RECOVERY_ORIENTED_SUPPLEMENT",q,behavior_labels=("RECOVERY_ORIENTED","CONDITIONAL"),known=("product_name_or_model","symptom","previous_action_result"),steps=_step_ids(u,2)[1:],
                recovery_trigger="PARTIAL_PROCEDURE",recovery_actions=("SUPPLEMENT","REWRITE"),recovery_signals=("MULTI_STAGE_PROCEDURE",),difficulty="HARD")
        if add(c): rcount+=1

    # Add deterministic raw attempts from non-usable/generic source units. These are genuine source-grounded attempts that must fail closed.
    rejected_units=[u for u in units if not u.benchmark_usable][:]
    rejected_units.sort(key=lambda u:(u.product_id or "ZZ",u.source_unit_id))
    for u in rejected_units:
        if len(rows)>=100: break
        pname=u.product_name or "这个设备"
        q=f"我的{pname}好像有点异常，请介绍一下这个部分相关的排查要点。"
        add(_candidate(u,"DIRECT_TROUBLESHOOTING",q,behavior_labels=("DIRECT",),known=(("product_name_or_model",) if u.product_id else ()),steps=_step_ids(u,1),difficulty="MEDIUM",flags=("RAW_SCOPE_REVIEW",)))

    # If dedup eliminated rows, fill with additional valid direct/conditional variants without changing source facts.
    if len(rows)<100:
        for u in _balanced(usable,75,lambda x:len(_self_service_steps(x))>=1 and x.symptom_family!="OTHER_TROUBLESHOOTING",usage):
            if len(rows)>=100: break
            cond=_first_condition(u)
            q=(f"关于我的{u.product_name}，手册里“{u.symptom}”这一情况如果{cond}，应执行哪个明确的下一步？" if cond
               else f"我的{u.product_name}遇到“{u.symptom}”，只告诉我手册中的首个明确处理动作是什么。")
            add(_candidate(u,"CONDITIONAL_TROUBLESHOOTING" if cond else "DIRECT_TROUBLESHOOTING",q,
                behavior_labels=(("CONDITIONAL",) if cond else ("DIRECT",)),known=("product_name_or_model","symptom")+(('condition',) if cond else ()),
                steps=_step_ids(u,1),difficulty="MEDIUM"))
    return rows[:100]
