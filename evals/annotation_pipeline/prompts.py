from __future__ import annotations

import json
from typing import Any

from .models import (
    AdjudicationResponse,
    AnnotationEnvelope,
    QueryUnderstandingAnnotation,
    RoutingAnnotation,
    RetrievalAnnotation,
    AnswerGenerationAnnotation,
    AgentBehaviorAnnotation,
    EndToEndAnnotation,
)

_LAYER_MODELS = {
    "query_understanding": QueryUnderstandingAnnotation,
    "routing": RoutingAnnotation,
    "retrieval": RetrievalAnnotation,
    "answer_generation": AnswerGenerationAnnotation,
    "agent_behavior": AgentBehaviorAnnotation,
    "end_to_end": EndToEndAnnotation,
}

PROFILE_GUIDANCE = {
    "evidence_first": (
        "先逐项定位来源证据，再形成标签。对数字、否定、条件、主体和业务动作保持原样，"
        "无法从来源推出时必须标记 needs_correction、ambiguous 或 unanswerable。"
    ),
    "counterexample_first": (
        "先尝试寻找反例、歧义和其他同样合理的标签，再给出最终标注。不要因为问题看似自然就默认现有设定正确。"
    ),
    "risk_first": (
        "优先检查身份、权限、退款、取消、质保、维修、安全警告、数字和时间等高风险信息，"
        "对冲突来源给出明确质量问题。"
    ),
}

COMMON_SYSTEM = """你是 Liorin Agentic RAG 评测集的独立标注 Agent。

严格规则：
1. 你看不到、也不得猜测原评测集 Gold；只根据 sample input 和冻结来源 source_context 重新标注。
2. 不得利用常识补全来源没有支持的事实。来源不足时标记 ambiguous 或 unanswerable。
3. 手册和售后政策优先于 FAQ；数据库当前状态优先于历史工单旧状态。
4. 历史工单状态 resolved 只表示状态，不表示具体解决过程已知。
5. 数字、日期、金额、错误码、否定、条件和主体必须与来源一致。
6. 允许判定样本本身有问题，不要为了完成标注强行给唯一答案。
7. 只输出满足 JSON Schema 的 JSON，不输出 Markdown 或额外说明。
"""

LAYER_GUIDANCE = {
    "query_understanding": """重建查询理解标签。requirements 应是用户实际目标，不是任意相关章节。
若产品、型号、错误码或业务标识无法确定，保留 null；只有信息缺失会造成错误回答或越权查询时才要求澄清。""",
    "routing": """重建来源路由标签。required 是缺少就无法完成问题；conditional 是只有提供额外字段后才需要；
optional 只能增强回答；forbidden 是不相关、越权或会造成错误路径。四组必须互斥。""",
    "retrieval": """对 source_context 中每个候选 chunk 打 0-3 分：3=直接完整回答，2=必要组成部分，
1=背景相关但单独不足，0=不相关或误导。必须为每个候选 chunk_id 输出 qrel，不得遗漏候选；同时从 2/3 级证据中抽取回答所需原子事实。""",
    "answer_generation": """根据给定 evidences 重新标注答案 Gold。每个原子事实只包含一个主要主张，
必须绑定来源；区分 required 与 optional；不要把问题中的措辞或来源标题本身当成答案事实。""",
    "agent_behavior": """根据完整 state_fixture 选择下一步动作。区分 retry_same_tool、retry_with_corrected_query、
rewrite_query、retrieve_more、clarify、answer_with_limitation、handoff 等动作；不要仅凭问题描述忽略结构化状态。""",
    "end_to_end": """重建端到端期望。问题必须能支持 decision_code、来源和必要事实；若多个行为同样合理，
在 allowed_actions 中表达，或将样本标记 ambiguous。不得要求数据库查询无法定位的用户记录。""",
}


def schema_for_layer(layer: str) -> dict[str, Any]:
    model = _LAYER_MODELS[layer]
    return model.model_json_schema()


def build_annotation_messages(packet: dict[str, Any], prompt_profile: str) -> tuple[str, str, dict[str, Any]]:
    layer = packet["layer"]
    profile = PROFILE_GUIDANCE.get(prompt_profile, PROFILE_GUIDANCE["evidence_first"])
    system = COMMON_SYSTEM + "\n标注风格：" + profile + "\n\n" + LAYER_GUIDANCE[layer]
    schema = schema_for_layer(layer)
    user = json.dumps(
        {
            "task": "independent_annotation",
            "sample": packet,
            "required_output_schema": schema,
        },
        ensure_ascii=False,
        indent=2,
    )
    return system, user, schema


def build_adjudication_messages(
    packet: dict[str, Any],
    annotation_a: dict[str, Any],
    annotation_b: dict[str, Any],
    conflicts: list[dict[str, Any]],
    prompt_profile: str,
) -> tuple[str, str, dict[str, Any]]:
    profile = PROFILE_GUIDANCE.get(prompt_profile, PROFILE_GUIDANCE["risk_first"])
    system = """你是 Liorin 评测集的第三方仲裁 Agent。

严格规则：
1. 你只处理 A/B 已列出的分歧字段，不得改写双方一致字段。
2. 每个 resolution.path 必须来自 conflicts，且每个 conflict path 必须恰好裁决一次。
3. 以冻结来源和结构化状态为准，不以 A 或 B 的自信程度为准。
4. 如果来源无法唯一裁决，选择最保守的可验证值，并把 quality_status 标记为 ambiguous 或 unanswerable。
5. 允许判定原样本需要修订；不要强行制造唯一 Gold。
6. 只输出满足 JSON Schema 的 JSON。
""" + "\n仲裁风格：" + profile
    schema = AdjudicationResponse.model_json_schema()
    user = json.dumps(
        {
            "task": "adjudicate_disagreements_only",
            "sample": packet,
            "annotation_a": annotation_a,
            "annotation_b": annotation_b,
            "conflicts": conflicts,
            "required_output_schema": schema,
        },
        ensure_ascii=False,
        indent=2,
    )
    return system, user, schema
