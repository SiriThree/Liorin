from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agents.feature_flags import AgentFeatureConfig
from eval_platform.ablation import (
    AblationFeature, AblationRunStatus, FullSystemConfig, check_ablation_fairness,
    compare_paired_metric, default_addition_configs, default_removal_configs, removal_config,
)


def test_full_config_fingerprint_is_stable_and_canonical():
    a=FullSystemConfig(model="m",retrieval={"top_k":5,"mode":"hybrid"})
    b=FullSystemConfig(model="m",retrieval={"mode":"hybrid","top_k":5})
    assert a.fingerprint == b.fingerprint


def test_single_feature_removal_has_only_expected_diff():
    cfg=removal_config(AblationFeature.EVIDENCE_VERIFIER)
    result=check_ablation_fairness(cfg)
    assert result.valid
    assert result.expected_differences == ("features.evidence_verifier_enabled",)
    assert cfg.target_config.feature_config.evidence_verifier_enabled is False
    assert cfg.base_config.feature_config.evidence_verifier_enabled is True


def test_ablation_fairness_rejects_unrelated_model_drift():
    cfg=removal_config(AblationFeature.RERANKER)
    invalid=replace(cfg,target_config=replace(cfg.target_config,model="different-model"))
    result=check_ablation_fairness(invalid)
    assert not result.valid
    assert "model" in result.unexpected_differences


def test_default_addition_and_removal_configs_have_unique_ids():
    configs=(*default_removal_configs(),*default_addition_configs())
    assert len({c.ablation_id for c in configs}) == len(configs)
    assert len(default_removal_configs()) == len(AblationFeature)


def test_paired_ablation_uses_same_case_ids_and_percentage_points():
    result=compare_paired_metric({"a":True,"b":True,"c":False},{"a":True,"b":False,"c":False,"extra":True})
    assert result["paired_cases"] == 3
    assert round(result["delta_pp"],5) == round((1/3-2/3)*100,5)
    assert result["status"] == AblationRunStatus.EXPLORATORY.value


def test_zero_paired_cases_is_not_run_not_zero_delta():
    result=compare_paired_metric({"a":True},{"b":False})
    assert result["status"] == "NOT_RUN"
    assert result["delta_pp"] is None


def test_production_ablation_wiring_is_real_not_report_only():
    root=Path(__file__).resolve().parents[2]
    deployment=(root/"deployments/support_agent_graph.py").read_text(encoding="utf-8")
    knowledge=(root/"agents/knowledge_agent.py").read_text(encoding="utf-8")
    hybrid=(root/"retrieval/hybrid_retriever.py").read_text(encoding="utf-8")
    assert "feature_config=feature_config" in deployment
    assert "if feature_config.evidence_verifier_enabled" in knowledge
    assert 'graph.add_edge("execute_retrieval", "generate_answer")' in knowledge
    assert "not feature_config.query_rewrite_enabled" in knowledge
    assert "not feature_config.supplement_enabled" in knowledge
    assert "not feature_config.clarification_recovery_enabled" in knowledge
    assert "if reranker_enabled" in hybrid
    assert "if parent_expansion_enabled" in hybrid
