"""Deployment configuration for the Liorin support agent.

Phase 3 exposes ``build_graph(agentic_recovery_enabled=False)`` as the fair
one-pass baseline switch. The default deployed graph remains recovery-enabled.
"""

from production import bootstrap_production_runtime

production_runtime = bootstrap_production_runtime()

from agents.feature_flags import AgentFeatureConfig
from agents.knowledge_agent import create_knowledge_agent
from agents.order_agent import create_order_agent
from agents.support_workflow import create_support_agent


def build_graph(*, agentic_recovery_enabled: bool = True, use_checkpointer: bool = False, feature_config: AgentFeatureConfig | None = None):
    # The deployed single-request graph keeps its historical no-checkpointer
    # behavior. Phase-4 multi-turn experiments enable ONLY the top-level
    # support checkpoint so successive user turns share the real workflow state;
    # specialist graphs still consume the state routed by the supervisor and do
    # not gain hidden extra executions.
    feature_config = feature_config or AgentFeatureConfig(agentic_recovery_enabled=agentic_recovery_enabled)
    order_agent = create_order_agent(use_checkpointer=False)
    knowledge_agent = create_knowledge_agent(
        use_checkpointer=False,
        recovery_enabled=feature_config.agentic_recovery_enabled,
        feature_config=feature_config,
    )
    return create_support_agent(
        order_agent=order_agent,
        knowledge_agent=knowledge_agent,
        use_checkpointer=use_checkpointer,
    )


graph = build_graph(agentic_recovery_enabled=True, feature_config=AgentFeatureConfig())
