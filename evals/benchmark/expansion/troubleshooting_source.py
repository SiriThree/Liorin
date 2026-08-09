"""Deterministic Phase F0 troubleshooting SourceUnit extraction."""
from __future__ import annotations

import hashlib, re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .source_inventory import build_document_source_inventory
from .fact_inventory import extract_atomic_facts
from .troubleshooting_candidate import RequiredContextDraft, TroubleshootingSourceUnit, TroubleshootingStepDraft

ACTION_TERMS=("检查","确保","添加","清洗","清洁","更换","重启","重新","联系","停止","断开","拔掉","等待","拧紧","调整","设置","复位","取出","插入","打开","关闭","请勿","切勿","不得","不要","咨询","送至","移除","移动","调节","充电","安装")
SAFETY_TERMS=("立即停止","停止使用","断开电源","拔掉电源","切勿","请勿","不得","危险","火灾","触电","爆炸","烫伤","死亡","严重受伤")
ESCALATION_TERMS=("联系","服务中心","售后","经销商","专业人员","维修","电工","咨询医生","客户服务热线")
GENERIC_TITLES=("警告","注意","注","故障排除","操作须知","安装须知","维护保养","相机手册","售后服务","其他问题","问题","自诊断功能","自检功能")
DIRECTIVE_TERMS=("请立即","立即","切勿","请勿","不得","不要","应当","应该","应立即","应先","需要","必须")
DISCLAIMER_TERMS=("经济损失","员工时间损失","赔偿的不便","不适合您的需求","一般除外责任","损害免责")


def _hash(prefix: str, value: str, n: int=16) -> str:
    return f"{prefix}{hashlib.sha256(value.encode('utf-8')).hexdigest()[:n]}"


def _symptom_family(text: str) -> str:
    t=text.lower()
    rules=[
        (("无法启动","不能启动","无响应","不开机","无法开机"),"START_OR_RESPONSE_FAILURE"),
        (("无法充电","充电异常","充不","电池"),"CHARGING_OR_BATTERY"),
        (("无法行驶","不走","无法运行"),"MOTION_OR_OPERATION_FAILURE"),
        (("无法抽水","积水","排水","水泵"),"WATER_FLOW_OR_DRAINAGE"),
        (("无法关闭","门体","门无法","门"),"DOOR_OR_MECHANICAL"),
        (("异常声音","异响","噪音","声响"),"ABNORMAL_NOISE"),
        (("过热","发烫","烧焦味","冒烟","气味"),"HEAT_SMELL_OR_SMOKE"),
        (("指示灯","红灯","闪烁","显示","屏幕"),"INDICATOR_OR_DISPLAY"),
        (("蓝牙","连接","usb","网络"),"CONNECTIVITY_OR_INTERFACE"),
        (("无法对焦","拍摄","快门","存储卡","打印"),"CAMERA_CAPTURE_OR_STORAGE"),
        (("滤网","清洁","保养","维护"),"MAINTENANCE"),
        (("错误码","故障码","error code"),"ERROR_CODE"),
    ]
    for keys,label in rules:
        if any(k in t for k in keys): return label
    return "OTHER_TROUBLESHOOTING"


def _condition_phrase(text: str) -> str | None:
    txt=re.sub(r"^[A-Za-z0-9oO•·・\-]+\s*", "", text.strip()).strip()
    # Preserve only the condition when a heading/fact itself embeds an instruction.
    m=re.match(r"^(?:若|如果|当|如)(.+?)[，,](.+)$", txt)
    if m:
        return m.group(1).strip(" ：:，,")
    m=re.match(r"^(.+?)[，,](?:需|需要|必须|建议|请|应当|应该)(.+)$", txt)
    if m and any(k in m.group(1) for k in ("无法","异常","故障","不工作","没反应","无响应")):
        return m.group(1).strip(" ：:，,")
    for marker in DIRECTIVE_TERMS:
        idx=txt.find(marker)
        if idx > 3:
            left=txt[:idx].strip(" ：:，,。；;")
            if any(k in left for k in ("异常","故障","无法","发热","冒烟","烧焦味","过热","湿度","门窗","问题")):
                return left
    return None

def _symptom(title: str, facts: list[Any]) -> str:
    title=re.sub(r"^[\d.、\s]+","",title).strip("：: ")
    cond=_condition_phrase(title)
    if cond:
        return cond
    broad_topic=any(x in title for x in ("维护","保养","清洁")) and not any(x in title for x in ("无法","异常","故障","无响应"))
    if title and title not in GENERIC_TITLES and len(title) <= 60 and not broad_topic and not any(x in title for x in ("保修","声明","规则第","训练","使用与操作")):
        return title
    for f in facts:
        txt=f.normalized_value
        if "若发生故障" in txt and "指示灯" in txt and "闪烁" in txt:
            m_diag=re.search(r"(室内机指示灯[^，,。；;]{0,40}闪烁)", txt)
            if m_diag:
                return m_diag.group(1).strip()
        cond=_condition_phrase(txt)
        if cond:
            return cond
        m=re.search(r"(?:问题[：:]?)?([^。；]{1,35}(?:无法|异常|故障|无响应|过热|发烫|闪烁|积水|异响)[^。；]{0,20})",txt)
        if m: return m.group(1).strip(" ：:")
    return title or "设备出现异常"


def _condition_action(text: str) -> tuple[str|None,str]:
    txt=re.sub(r"^[A-Za-z0-9oO•·・\-]+\s*", "", text.strip()).strip()
    m=re.match(r"^(若|如果|当|如)(.+?)[，,；;](.+)$",txt)
    if m: return m.group(2).strip(), m.group(3).strip()
    m=re.match(r"^(若|如果|如)(.+?)(请|则)(.+)$",txt)
    if m: return m.group(2).strip(), (m.group(3)+m.group(4)).strip()
    m=re.search(r"若(.+?)[，,](.+?)[，,](出现此情况|此时)(请.+)$", txt)
    if m:
        return (m.group(1)+"，"+m.group(2)).strip(), (m.group(3)+m.group(4)).strip()
    # Troubleshooting tables often encode cause -> action with an ellipsis rather than IF syntax.
    m=re.match(r"^(.{2,36}?)(?:……|…{2,}|\.{3,})(.+)$", txt)
    if m and any(k in m.group(2) for k in ACTION_TERMS):
        return m.group(1).strip(" ：:，,。；;"), m.group(2).strip()
    if txt.startswith("若问题依旧") or txt.startswith("如果问题依旧"):
        return "问题依旧", txt.split("，",1)[-1] if "，" in txt else txt
    return None, txt


def _looks_actionable(raw: str, action: str, condition: str | None) -> bool:
    raw=re.sub(r"^[A-Za-z0-9oO•·・\-]+\s*", "", raw.strip()).strip()
    action=action.strip()
    if condition:
        return any(k in action for k in ACTION_TERMS) or any(action.startswith(k) for k in ("说明","表示","意味着","则"))
    if any(raw.startswith(k) for k in ACTION_TERMS):
        return True
    if re.search(r"(?:请|应当|应该|应立即|应先|需|需要|必须|建议|切勿|请勿|不得|不要).{0,18}(?:"+"|".join(map(re.escape,ACTION_TERMS))+r")", raw):
        return True
    return False

def _preventive_only(facts: list[Any], conditions: list[dict[str, Any]]) -> bool:
    texts=[str(f.normalized_value) for f in facts]
    if not texts:
        return False
    preventive_markers=("否则可能导致","以免导致","以免门体","防止设备出现故障","防止产品故障","避免发生","以防")
    preventive=sum(any(m in t for m in preventive_markers) for t in texts)
    active_condition=any(any(k in str(c.get("condition") or "") for k in ("无法","异常","故障","问题依旧","仍无法","不发热","冒烟","烧焦味","过热")) for c in conditions)
    return (not active_condition) and preventive >= max(1, (len(texts)+1)//2)


def build_troubleshooting_source_units(root: Path) -> tuple[list[TroubleshootingSourceUnit], dict[str, Any]]:
    docs, sections=build_document_source_inventory(root)
    facts=extract_atomic_facts(sections)
    secmap={s["section_id"]:s for s in sections}
    by=defaultdict(list)
    for f in facts:
        if f.fact_type in {"TROUBLESHOOTING_STEP","ERROR_CODE"} and f.benchmark_usable:
            by[f.section_id].append(f)
    units=[]
    for sid, fs in sorted(by.items()):
        sec=secmap[sid]; title=sec.get("title") or ""; text=sec.get("text") or ""
        product_id=sec.get("product_id"); product_name=sec.get("product_name")
        symptom=_symptom(title,fs); sfam=_symptom_family(symptom)
        error=None
        mm=re.search(r"(?:错误码|故障码|error\s*code)\s*[:：]?\s*([A-Za-z0-9_-]+)",text,re.I)
        if mm: error=mm.group(1)
        has_error_code_context = any(f.fact_type == "ERROR_CODE" for f in fs) or "错误码" in title or "故障码" in title
        steps=[]; conditions=[]; safety=[]; stop=[]; escal=[]
        for i,f in enumerate(fs):
            ft=f.normalized_value
            cond,action=_condition_action(ft)
            is_disclaimer=any(k in ft for k in DISCLAIMER_TERMS)
            is_action=_looks_actionable(ft, action, cond) and not is_disclaimer
            is_safety=any(k in ft for k in SAFETY_TERMS) and not is_disclaimer
            is_escal=any(k in ft for k in ESCALATION_TERMS) and not is_disclaimer
            if cond: conditions.append({"condition":cond,"action":action,"source_fact_id":f.fact_id})
            if is_safety: safety.append(f.fact_id)
            if any(k in ft for k in ("立即停止","停止使用","切勿自行","不得继续","断开电源")): stop.append(f.fact_id)
            if is_escal: escal.append(f.fact_id)
            if is_action:
                steps.append(TroubleshootingStepDraft(
                    step_id=_hash("step:",f"{sid}|{f.fact_id}"), action=action, precondition=cond,
                    order_required=bool(cond or re.search(r"(?:首先|然后|之后|下一步|第[一二三四五六七八九十0-9]+)",ft)),
                    safety_critical=is_safety, terminal=is_escal or any(k in ft for k in ("立即停止","不得继续")),
                    escalation=is_escal, source_fact_id=f.fact_id,
                ))
        bullet_count=len(re.findall(r"(?:^|\n)\s*(?:\d+[.、)]|[-●·•])",text))
        if bullet_count>=2 and len(steps)>=2: order="PARTIALLY_ORDERED"
        elif sum(1 for x in steps if x.order_required)>=2: order="ORDERED"
        else: order="UNORDERED"
        required=[]
        # Product context is required for selecting a product-specific manual, but candidates may provide it.
        if product_id:
            required.append(RequiredContextDraft("product_name_or_model",True,"product-specific manual selection",(sid,),True,False,False,False))
        if any(x.get("condition") for x in conditions):
            required.append(RequiredContextDraft("condition_or_previous_result",False,"conditional branch may depend on current condition/result",tuple(x["source_fact_id"] for x in conditions[:3]),True,False,False,False))
        flags=[]
        generic=title.strip(" ：:") in GENERIC_TITLES
        if generic: flags.append("GENERIC_SECTION_TITLE")
        if has_error_code_context and not error: flags.append("ERROR_CODE_CONTEXT_WITHOUT_CONCRETE_CODE")
        if not steps: flags.append("NO_ACTIONABLE_STEP")
        if len(fs)==1 and not steps: flags.append("SOURCE_FRAGMENT_LACKS_ACTION")
        non_trouble=any(x in title or x in text for x in ("FCC","声明","保修问答","一般除外责任","装配说明","保修期内","购买后")) or any(x in text for x in DISCLAIMER_TERMS)
        preventive=_preventive_only(fs, conditions)
        if non_trouble: flags.append("NON_TROUBLESHOOTING_CONTEXT")
        if preventive: flags.append("PREVENTIVE_ONLY_CONTEXT")
        active_terms=("故障","无法","异常","问题依旧","无响应","积水","发热","冒烟","烧焦味","过热","闪烁","空白","不工作","不能")
        active_scope = any(x in symptom for x in active_terms) or any(any(x in str(c.get("condition") or "") for x in active_terms) for c in conditions) or bool(stop)
        specific_scope = sfam != "OTHER_TROUBLESHOOTING" or any(x in symptom for x in ("故障","无法","异常","问题","无响应","自诊断","自检","发热","冒烟","烧焦味","过热")) or bool(stop)
        benchmark=bool(product_id and steps and not non_trouble and not preventive and specific_scope and active_scope)
        units.append(TroubleshootingSourceUnit(
            source_unit_id=_hash("tsu:",sid),document_id=sec["document_id"],section_id=sid,product_id=product_id,
            product_name=product_name,symptom=symptom,symptom_family=sfam,error_code=error,
            required_context=tuple(required),diagnostic_steps=tuple(steps),conditional_branches=tuple(conditions),
            safety_prerequisites=tuple(safety),stop_conditions=tuple(stop),escalation_conditions=tuple(escal),
            manual_fact_ids=tuple(f.fact_id for f in fs),source_text_refs=(sid,),step_order=order,
            benchmark_usable=benchmark,quality_flags=tuple(flags),
        ))
    report={
        "source_units":len(units),
        "benchmark_usable":sum(u.benchmark_usable for u in units),
        "with_required_context":sum(bool(u.required_context) for u in units),
        "with_multi_step":sum(len(u.diagnostic_steps)>=2 for u in units),
        "with_conditional_branch":sum(bool(u.conditional_branches) for u in units),
        "with_safety_condition":sum(bool(u.safety_prerequisites) for u in units),
        "with_escalation":sum(bool(u.escalation_conditions) for u in units),
        "with_error_code":sum(bool(u.error_code) for u in units),
        "with_error_code_context":sum("ERROR_CODE_CONTEXT_WITHOUT_CONCRETE_CODE" in u.quality_flags or bool(u.error_code) for u in units),
    }
    return units, report
