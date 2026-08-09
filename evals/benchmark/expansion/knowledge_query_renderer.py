"""Deterministic controlled Chinese query renderer for Phase G0.3."""
from __future__ import annotations

import hashlib
import re
from typing import Any

RENDER_VERSION = "controlled-knowledge-query-g0.3-v1"

_GENERIC_HEADINGS = {
    "注意", "注意事项", "重要", "重要！", "目标：", "目标", "注", "说明",
    "提示", "警告", "其他", "其它", "概述", "一般信息",
}


def normalize_text(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"^[>・•\-\s]+", "", text)
    text = re.sub(r"^(注意|注|提示|警告|重要提示)\s*[:：]?\s*", "", text)
    text = re.sub(r"^\d+[\.、\s]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _stable_pick(seed: str, items: list[str]) -> str:
    h = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return items[h % len(items)]


def _product_name(plan: dict[str, Any], doc_map: dict[str, dict[str, Any]]) -> str:
    if not plan.get("product_ids"):
        return ""
    pid = plan["product_ids"][0]
    for d in doc_map.values():
        if d.get("product_id") == pid:
            return d.get("product_model") or d.get("title", "").replace("手册", "") or pid
    return pid


def _heading(plan: dict[str, Any], section_map: dict[str, dict[str, Any]]) -> str:
    heads = [str(section_map.get(s, {}).get("heading") or "").strip() for s in plan.get("section_ids", [])]
    heads = [re.sub(r"^(?:[A-Z]\.|\d+[\.、])\s*", "", h).strip() for h in heads]
    heads = [h for h in heads if h and h not in _GENERIC_HEADINGS]
    return heads[0] if heads else ""


def _facts(plan: dict[str, Any], fact_map: dict[str, dict[str, Any]]) -> list[str]:
    return [normalize_text(fact_map[f]["fact_text"]) for f in plan.get("required_fact_ids", []) if f in fact_map]


def _target_hint(fact: str, heading: str) -> str:
    # This returns the *dimension* being asked, not the answer value.
    checks = [
        (r"适用年龄", "适用年龄"),
        (r"不适用于|适用于", "适用范围"),
        (r"系统要求|Windows|BIOS|USB.*(?:鼠标|键盘)", "系统兼容要求"),
        (r"手机是否兼容", "手机兼容性"),
        (r"充电器.*电池组.*兼容", "充电器与电池组兼容性"),
        (r"端子", "接线端子兼容性"),
        (r"Wi[\-‑ ]?Fi", "Wi‑Fi 功能"),
        (r"蓝牙|Bluetooth", "蓝牙功能"),
        (r"电池", "电池规格或使用要求"),
        (r"滤网|滤芯", "滤网"),
        (r"脚轮", "脚轮安装"),
        (r"保修|质保", "保修规则"),
        (r"购物小票|购买日期|凭证", "购买凭证"),
        (r"电源线|插头|电源", "电源使用"),
        (r"清洁剂|清洁", "清洁操作"),
        (r"用户档案|档案名称", "用户档案"),
        (r"非接触式支付|NFC|信用卡|借记卡", "非接触式支付"),
        (r"软水|专用盐|水硬度", "软水系统和专用盐"),
        (r"出风方向|摆风", "出风方向调节"),
        (r"超强制冷|快速制冷", "超强制冷"),
        (r"门体换向|左开|右开", "门体换向"),
        (r"速度|方向", "速度或方向切换"),
        (r"标准|认证", "认证标准"),
        (r"重量", "重量"),
        (r"尺寸", "尺寸"),
        (r"容量", "容量"),
        (r"功率", "功率"),
        (r"接口", "接口"),
        (r"电压", "电压或供电要求"),
    ]
    combo = f"{heading} {fact}"
    if re.search(r"产品识别码", combo):
        return "产品识别码"
    for pat, label in checks:
        if re.search(pat, combo, re.I):
            return label
    if heading:
        return heading.strip("：:。！!")
    # Avoid using full answer text as hint; use a generic domain word.
    return "这项说明"


def _render_single(plan: dict[str, Any], facts: list[str], product: str, heading: str) -> tuple[str, str, dict[str, Any]]:
    fact = facts[0] if facts else ""
    typ = plan["primary_task_type"]
    target = _target_hint(fact, heading)
    p = f"{product}的" if product else ""
    seed = plan["task_plan_id"]

    if typ == "PRODUCT_SPEC":
        # Attribute-value / symbol-definition style.
        m = re.match(r"^([^=＝]{1,20})[=＝]\s*(.+)$", fact)
        if m:
            lhs = m.group(1).strip()
            q = f"{p}{target}里，{lhs}这个标记表示什么？"
            return q, "SPEC_SYMBOL_MEANING", {"targets": list(plan["required_fact_ids"]), "focus": lhs}
        if re.search(r"距离处测量|距离.*测量", fact):
            q = f"{p}{heading or target}相关数据是在什么测量距离下得到的？"
            return q, "SPEC_MEASUREMENT_CONDITION", {"targets": list(plan["required_fact_ids"]), "focus": heading or target}
        if re.search(r"标准|认证", fact):
            q = f"{product}符合哪项与{target}相关的标准或认证要求？"
            return q, "SPEC_STANDARD", {"targets": list(plan["required_fact_ids"]), "focus": target}
        q = _stable_pick(seed, [
            f"{p}{target}具体是什么规格？",
            f"想确认一下，{p}{target}的规格参数是什么？",
            f"{p}{target}在手册里标注的规格是什么？",
        ])
        return q, "SPEC_ATTRIBUTE", {"targets": list(plan["required_fact_ids"]), "focus": target}

    if typ == "COMPATIBILITY":
        if re.search(r"适用.*电池|电池型号", fact):
            q = f"{product or '这款设备'}的遥控器应该使用哪种电池规格？"
            return q, "COMPATIBILITY_REQUIRED_SPEC", {"targets": list(plan["required_fact_ids"]), "focus": "电池规格"}
        if re.search(r"适用年龄", fact):
            q = f"{product or '这款产品'}适合多大年龄的用户？"
            return q, "COMPATIBILITY_AGE_RANGE", {"targets": list(plan["required_fact_ids"]), "focus": "适用年龄"}
        if re.search(r"不适用于", fact):
            q = f"{product or '这款产品'}有哪些表面、对象或使用场景是不适用的？"
            return q, "COMPATIBILITY_UNSUPPORTED_SCOPE", {"targets": list(plan["required_fact_ids"]), "focus": "不适用范围"}
        if re.search(r"适用于", fact):
            q = f"{product or '这款产品'}适合哪些表面、对象或使用场景？"
            return q, "COMPATIBILITY_SUPPORTED_SCOPE", {"targets": list(plan["required_fact_ids"]), "focus": "适用范围"}
        if re.search(r"部分.*不支持|因机型不同", fact):
            q = f"{p}{target}在不同机型上的支持情况有什么限制？"
            return q, "COMPATIBILITY_MODEL_VARIANCE", {"targets": list(plan["required_fact_ids"]), "focus": target}
        if re.search(r"Windows|系统要求", fact, re.I):
            q = f"{product or '这款产品'}对电脑系统和输入设备支持有哪些要求？"
            return q, "COMPATIBILITY_OS_REQUIREMENTS", {"targets": list(plan["required_fact_ids"]), "focus": "系统兼容要求"}
        if re.search(r"兼容.*(?:v?\d|规范)|蓝牙.*规范", fact, re.I):
            q = f"{product or '这款产品'}兼容哪些蓝牙规范和设备类型？"
            return q, "COMPATIBILITY_PROTOCOL_REQUIREMENTS", {"targets": list(plan["required_fact_ids"]), "focus": "蓝牙兼容规范"}
        if re.search(r"USB.*(?:鼠标|键盘)", fact, re.I):
            q = f"{product or '这款产品'}对 USB 键盘或鼠标支持有哪些系统限制？"
            return q, "COMPATIBILITY_USB_REQUIREMENTS", {"targets": list(plan["required_fact_ids"]), "focus": "USB兼容要求"}
        if re.search(r"充电器.*电池组.*兼容", fact):
            q = f"{product or '这款产品'}的充电器和电池组兼容关系应该怎么确认？"
            return q, "COMPATIBILITY_CHARGER_BATTERY", {"targets": list(plan["required_fact_ids"]), "focus": "充电器与电池组兼容性"}
        if re.search(r"手机是否兼容", fact):
            q = f"设置{product or '这款设备'}前，应该怎样确认手机兼容性？"
            return q, "COMPATIBILITY_PHONE_CHECK", {"targets": list(plan["required_fact_ids"]), "focus": "手机兼容性"}
        if re.search(r"不支持.*端子|端子", fact):
            q = f"安装{product or '这款设备'}时，接线端子有哪些兼容限制？"
            return q, "COMPATIBILITY_TERMINAL", {"targets": list(plan["required_fact_ids"]), "focus": "接线端子兼容性"}
        if re.search(r"支持站立模式", fact):
            q = f"使用{product or '这款设备'}的站立模式应用时，适用范围和操作要求是什么？"
            return q, "COMPATIBILITY_MODE", {"targets": list(plan["required_fact_ids"]), "focus": "站立模式"}
        # Generic relation surface; validation may send semantically weak plans to review.
        q = f"{p}{target}的适用或支持范围是怎样的？"
        return q, "COMPATIBILITY_RELATION", {"targets": list(plan["required_fact_ids"]), "focus": target}

    if typ == "LIMITATION":
        if re.search(r"清洁", fact):
            q = f"清洁{product or '这款设备'}时，{target}方面有哪些限制？"
        elif re.search(r"不可|不得|禁止|限制|仅限|不能", fact):
            q = f"使用{product or '这款设备'}时，{target}方面有什么不能忽略的限制？"
        else:
            q = f"{p}{target}有哪些适用限制？"
        return q, "LIMITATION_TARGETED", {"targets": list(plan["required_fact_ids"]), "focus": target}

    if typ == "POLICY_OR_WARRANTY":
        if re.search(r"人工审批", heading):
            q = "售后流程中，哪些类型的操作需要人工审批？"; pat = "POLICY_APPROVAL_SCOPE"
        elif re.search(r"维修工单", heading):
            q = "创建维修工单时，通常需要包含哪些关键信息？"; pat = "POLICY_TICKET_FIELDS"
        elif re.search(r"合同.*地区法规|地区法规.*协议|企业客户协议", fact):
            q = "通用售后政策与具体合同、地区法规或企业客户协议不一致时，应如何判断适用规则？"; pat = "POLICY_PRECEDENCE"
        elif re.search(r"购物小票|凭证|购买日期", fact):
            q = f"{product or '产品'}申请保修时，购买凭证需要怎样保留或使用？"; pat = "POLICY_PURCHASE_PROOF"
        elif re.search(r"不在保修|不予保修|保修范围", fact):
            q = f"{product or '这款产品'}的保修规则里，哪些情况会影响保修适用？"; pat = "POLICY_COVERAGE_EXCLUSION"
        elif re.search(r"美国本土.*(?:2年|保修)", fact):
            q = f"{product or '这款产品'}的保修期限和适用条件是怎样规定的？"; pat = "POLICY_DURATION_WITH_CONDITIONS"
        elif re.search(r"一年|个月|期限|自购买", fact):
            q = f"{product or '这款产品'}的保修期限是如何规定的？"; pat = "POLICY_DURATION"
        else:
            q = f"关于{product or '该产品'}的{target}，相关规则是怎样规定的？"; pat = "POLICY_RULE"
        return q, pat, {"targets": list(plan["required_fact_ids"]), "focus": target, "qualification_sensitive": True}

    if typ == "FEATURE_OR_INSTRUCTION":
        if re.search(r"若|如果|如需|时|前|后", fact):
            q = f"在涉及{p}{target}的这个条件下，应该采取什么操作或处理？"
            pat = "INSTRUCTION_CONDITION_ACTION"
        elif re.search(r"安装|设置|开启|关闭|按下|选择|切换|更换|清洁|使用", fact):
            q = f"{p}{target}具体应该怎么操作？"
            pat = "INSTRUCTION_SPECIFIC_OPERATION"
        else:
            q = f"关于{p}{target}，手册给出的具体要求是什么？"
            pat = "INSTRUCTION_REQUIREMENT"
        return q, pat, {"targets": list(plan["required_fact_ids"]), "focus": target}

    # DIRECT_FACT
    if re.search(r"产品识别码", fact):
        q = f"{product or '这款产品'}的产品识别码是什么？"
        pat = "DIRECT_IDENTIFIER_LOOKUP"
    elif re.search(r"属正常|正常现象", fact):
        q = f"出现{heading or target}这种现象时，手册是怎么解释的？"
        pat = "DIRECT_EXPLANATION"
    elif re.search(r"^本练习|^本节|^本章|目标", fact):
        q = f"{product or '这份手册'}中“{heading or target}”这部分主要想让用户了解什么？"
        pat = "DIRECT_META_SECTION"
    else:
        q = _stable_pick(seed, [
            f"关于{p}{target}，手册给出的明确说明是什么？",
            f"想确认{p}{target}，手册具体怎么说明？",
            f"{p}{target}的具体说明是什么？",
        ])
        pat = "DIRECT_TARGETED"
    return q, pat, {"targets": list(plan["required_fact_ids"]), "focus": target}


def _render_multi_fact(plan: dict[str, Any], facts: list[str], product: str, heading: str) -> tuple[str, str, dict[str, Any]]:
    target = heading if heading and heading not in _GENERIC_HEADINGS else _target_hint(" ".join(facts), heading)
    p = product or "这款产品"
    topic = plan.get("semantic_topic") or ""
    if topic == "safety_usage" or sum(bool(re.search(r"请勿|不得|禁止|危险|安全", f)) for f in facts) >= 2:
        q = f"使用{p}的{target}时，需要同时遵守哪些安全操作要求？"
        pattern = "MULTIFACT_SAFETY_BOUNDED"
    elif topic in {"maintenance", "installation"}:
        q = f"进行{p}的{target}时，需要同时满足哪些操作和使用要求？"
        pattern = "MULTIFACT_OPERATION_BOUNDED"
    elif any(re.search(r"支持|不支持|兼容|适用", f) for f in facts) and any(re.search(r"限制|仅|条件|如果|若", f) for f in facts):
        q = f"{p}的{target}在能力和适用条件上分别有哪些明确要求？"
        pattern = "MULTIFACT_CAPABILITY_CONDITION"
    else:
        if not product and heading:
            clean = heading.rstrip("？?")
            if "错误码" in clean and "型号" in clean:
                q = "查询错误码时，为什么还需要确认产品型号或产品名称？"
                pattern = "MULTIFACT_FAQ_ERROR_CODE_CONTEXT"
            elif clean.startswith("如何"):
                q = f"关于“{clean}”，实际需要同时了解哪些关键信息？"
                pattern = "MULTIFACT_FAQ_PROCESS"
            else:
                q = f"关于“{clean}”，需要同时了解哪些相互关联的规则或信息？"
                pattern = "MULTIFACT_FAQ_BOUNDED"
        else:
            q = f"关于{p}的{target}，需要同时了解哪些相互关联的要求？"
            pattern = "MULTIFACT_BOUNDED_REQUIREMENTS"
    return q, pattern, {"targets": list(plan["required_fact_ids"]), "focus": target, "required_fact_count": len(facts)}


def _render_multi_section(plan: dict[str, Any], facts: list[str], product: str, section_map: dict[str, dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    rels = plan.get("composition_relation_evidence") or []
    anchor = (rels[0].get("anchor") if rels else "") or _heading(plan, section_map) or "相关功能"
    topic = plan.get("semantic_topic") or ""
    p = product or "这款产品"
    joined = " ".join(facts)
    heads=[re.sub(r"^(?:[A-Z]\.|\d+[\.、])\s*", "", str(section_map.get(s,{}).get("heading") or "")).strip() for s in plan.get("section_ids",[])]
    if topic == "feature_with_compatibility":
        if "设置健身追踪器" in joined or "配对权限" in joined:
            q = f"设置{p}时需要通过哪些手机平台，并完成哪些必要的配对权限操作？"
        else:
            q = f"使用{p}的{anchor}时，具体怎么操作，同时需要注意哪些机型或设备兼容限制？"
        pattern="MULTISECTION_FEATURE_COMPATIBILITY"
    elif topic == "capability_with_feature":
        q = f"{p}与安卓手机配对后可以实现什么功能，设置过程中还需要完成哪些必要权限操作？"; pattern="MULTISECTION_CAPABILITY_FEATURE"
    elif topic == "usage_with_compatibility":
        if "应用中设置" in joined:
            q = f"使用{p}进行非接触式支付前，需要具备什么设备能力，并在应用和商店侧满足哪些条件？"
        else:
            q = f"{p}进行非接触式支付需要具备什么设备能力，消费场所又需要满足什么条件？"
        pattern="MULTISECTION_USAGE_COMPATIBILITY"
    elif topic == "feature_with_limitation":
        q = f"编辑{p}的用户档案时，名称设置和退出编辑分别有什么规则？" if "用户档案" in joined else f"使用{p}的{anchor}时，具体操作方式和相关限制分别是什么？"
        pattern="MULTISECTION_FEATURE_LIMITATION"
    elif topic == "capability_with_warranty":
        q = f"{p}的{anchor}能否调整，进行这项操作时还需要注意什么保修限制？"; pattern="MULTISECTION_CAPABILITY_WARRANTY"
    elif topic == "usage_with_condition":
        if "专用盐" in joined:
            q = f"使用{p}的软水系统时，达到什么水硬度条件需要软化除垢，为什么还需要使用专用盐？"
        elif "调节软水系统" in joined or "正确调节" in joined:
            q = f"{p}在什么水硬度条件下需要软化除垢，正确调节软水系统会带来什么作用？"
        else:
            q = f"使用{p}的{anchor}时，什么条件会触发相关处理，随后还需要满足什么使用要求？"
        pattern="MULTISECTION_USAGE_CONDITION"
    elif topic == "feature_with_condition":
        if "提前停止" in joined:
            q = f"{p}的超强制冷适合在什么情况下开启，如果想提前停止又应该怎么操作？"
        elif re.search(r"运行约|自动恢复", joined):
            q = f"{p}的超强制冷适合在什么情况下开启，通常会运行多久并如何结束？"
        else:
            q = f"{p}的{anchor}在什么情况下使用，启动或停止这项功能时分别需要怎样操作？"
        pattern="MULTISECTION_FEATURE_CONDITION"
    elif topic == "installation_with_usage":
        q = f"首次给{p}添加专用盐时，前置准备和加盐后的处理分别有什么要求？" if "专用盐" in joined else f"首次使用{p}的{anchor}时，前置准备和后续处理分别有什么要求？"
        pattern="MULTISECTION_INSTALLATION_USAGE"
    elif topic == "compatibility_with_limitation":
        q = f"儿童使用{p}时有哪些年龄限制，家长或监护人还能配置哪些使用限制？"
        pattern="MULTISECTION_COMPATIBILITY_LIMITATION"
    else:
        q = f"关于{p}的{anchor}，结合两部分说明后应怎样理解它的使用方式和适用条件？"; pattern="MULTISECTION_SYNTHESIS"
    return q, pattern, {"targets": list(plan["required_fact_ids"]), "relation_anchor": anchor, "relation_evidence": rels, "required_sections": list(plan["section_ids"]), "section_headings": heads}


def render_query(plan: dict[str, Any], fact_map: dict[str, dict[str, Any]], section_map: dict[str, dict[str, Any]], doc_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    facts = _facts(plan, fact_map)
    product = _product_name(plan, doc_map)
    heading = _heading(plan, section_map)
    typ = plan["primary_task_type"]
    if typ == "MULTI_SECTION_SYNTHESIS":
        query, pattern, meta = _render_multi_section(plan, facts, product, section_map)
    elif typ in {"MULTI_FACT_SYNTHESIS", "FAQ_PROCESS"}:
        if typ == "FAQ_PROCESS":
            # FAQ is a bounded multi-fact user process, but should not copy canonical heading verbatim.
            target = heading or _target_hint(" ".join(facts), "")
            q_templates = [
                f"想了解一下“{target}”这种情况，实际处理时需要知道哪些关键信息？",
                f"遇到“{target}”相关问题时，应该怎样理解对应的处理规则？",
                f"关于“{target}”，客服通常需要说明哪些关键点？",
            ]
            query = _stable_pick(plan["task_plan_id"], q_templates)
            pattern = "FAQ_NATURALIZED_PROCESS"
            meta = {"targets": list(plan["required_fact_ids"]), "canonical_heading": heading, "focus": target, "faq_naturalized": query.strip("？") != heading.strip("？")}
        else:
            query, pattern, meta = _render_multi_fact(plan, facts, product, heading)
    else:
        query, pattern, meta = _render_single(plan, facts, product, heading)
    query = re.sub(r"\s+", " ", query).strip()
    if not query.endswith(("？", "?")):
        query += "？"
    return {"query": query, "pattern": pattern, "metadata": meta, "product_name": product, "heading": heading, "facts": facts, "render_version": RENDER_VERSION}
