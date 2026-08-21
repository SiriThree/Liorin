"""Controlled Phase-6 ablation contracts and paired result aggregation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from agents.feature_flags import AgentFeatureConfig


ABLATION_SCHEMA_VERSION = "1.0"


class AblationStudyType(StrEnum):
    ADDITION = "ADDITION"
    REMOVAL = "REMOVAL"


class AblationRunStatus(StrEnum):
    READY = "READY"
    NOT_RUN = "NOT_RUN"
    BLOCKED = "BLOCKED"
    INVALID = "INVALID"
    EXPLORATORY = "EXPLORATORY"


class AblationFeature(StrEnum):
    AGENTIC_RECOVERY = "agentic_recovery_enabled"
    EVIDENCE_VERIFIER = "evidence_verifier_enabled"
    QUERY_REWRITE = "query_rewrite_enabled"
    SUPPLEMENT = "supplement_enabled"
    CLARIFICATION = "clarification_recovery_enabled"
    RERANKER = "reranker_enabled"
    PARENT_EXPANSION = "parent_expansion_enabled"
    ENTITY_SCOPED_ROUTING = "entity_scoped_routing_enabled"
    SEMANTIC_VERIFIER = "semantic_verifier_enabled"


@dataclass(frozen=True, slots=True)
class FullSystemConfig:
    feature_config: AgentFeatureConfig = field(default_factory=AgentFeatureConfig)
    context_strategy: str = "LIORIN_CONTEXT_MEMORY_ARTIFACT"
    model: str | None = None
    embedding: str | None = None
    retrieval: Mapping[str, Any] = field(default_factory=dict)
    budget: Mapping[str, Any] = field(default_factory=dict)
    governance: Mapping[str, Any] = field(default_factory=dict)
    tool_configuration: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        return {
            "features": self.feature_config.to_state(),
            "context_strategy": self.context_strategy,
            "model": self.model,
            "embedding": self.embedding,
            "retrieval": dict(self.retrieval),
            "budget": dict(self.budget),
            "governance": dict(self.governance),
            "tool_configuration": dict(self.tool_configuration),
        }

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.to_state(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AblationConfig:
    ablation_id: str
    study_type: AblationStudyType
    base_config: FullSystemConfig
    target_config: FullSystemConfig
    disabled_features: tuple[AblationFeature, ...] = ()
    enabled_features: tuple[AblationFeature, ...] = ()
    dataset_hash: str | None = None
    description: str = ""

    @property
    def config_hash(self) -> str:
        state = self.to_state(include_hash=False)
        raw = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(raw.encode("utf-8")).hexdigest()

    def to_state(self, *, include_hash: bool = True) -> dict[str, Any]:
        state = {
            "schema_version": ABLATION_SCHEMA_VERSION,
            "ablation_id": self.ablation_id,
            "study_type": self.study_type.value,
            "base_config": self.base_config.to_state(),
            "target_config": self.target_config.to_state(),
            "disabled_features": [x.value for x in self.disabled_features],
            "enabled_features": [x.value for x in self.enabled_features],
            "dataset_hash": self.dataset_hash,
            "description": self.description,
        }
        if include_hash:
            state["config_hash"] = self.config_hash
        return state


@dataclass(frozen=True, slots=True)
class AblationFairnessResult:
    valid: bool
    unexpected_differences: tuple[str, ...]
    expected_differences: tuple[str, ...]


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, Mapping):
        for key in sorted(value):
            _flatten(f"{prefix}.{key}" if prefix else str(key), value[key], out)
    else:
        out[prefix] = value


def check_ablation_fairness(config: AblationConfig) -> AblationFairnessResult:
    left: dict[str, Any] = {}
    right: dict[str, Any] = {}
    _flatten("", config.base_config.to_state(), left)
    _flatten("", config.target_config.to_state(), right)
    diffs = tuple(sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k)))
    expected = tuple(sorted(f"features.{x.value}" for x in (*config.disabled_features, *config.enabled_features)))
    unexpected = tuple(x for x in diffs if x not in expected)
    missing = tuple(x for x in expected if x not in diffs)
    return AblationFairnessResult(not unexpected and not missing, tuple((*unexpected, *missing)), expected)


def removal_config(feature: AblationFeature, *, base: FullSystemConfig | None = None) -> AblationConfig:
    base = base or FullSystemConfig()
    flags = base.feature_config.to_state()
    flags[feature.value] = False
    target = replace(base, feature_config=AgentFeatureConfig.from_mapping(flags))
    return AblationConfig(
        ablation_id=f"full_minus_{feature.name.casefold()}",
        study_type=AblationStudyType.REMOVAL,
        base_config=base,
        target_config=target,
        disabled_features=(feature,),
        description=f"Full Liorin with only {feature.value} disabled",
    )


def default_removal_configs(base: FullSystemConfig | None = None) -> tuple[AblationConfig, ...]:
    base = base or FullSystemConfig()
    return tuple(removal_config(feature, base=base) for feature in AblationFeature)


def default_addition_configs(base: FullSystemConfig | None = None) -> tuple[AblationConfig, ...]:
    full = base or FullSystemConfig()
    all_off = AgentFeatureConfig(
        agentic_recovery_enabled=False,
        evidence_verifier_enabled=False,
        query_rewrite_enabled=False,
        supplement_enabled=False,
        clarification_recovery_enabled=False,
        reranker_enabled=False,
        parent_expansion_enabled=False,
        semantic_verifier_enabled=False,
    )
    stages = [
        ("a0_one_pass_basic", all_off, ()),
        ("a1_plus_reranker", replace(all_off, reranker_enabled=True), (AblationFeature.RERANKER,)),
        ("a2_plus_parent_expansion", replace(all_off, reranker_enabled=True, parent_expansion_enabled=True), (AblationFeature.PARENT_EXPANSION,)),
        ("a3_plus_verifier", replace(all_off, reranker_enabled=True, parent_expansion_enabled=True, evidence_verifier_enabled=True), (AblationFeature.EVIDENCE_VERIFIER,)),
        ("a4_plus_recovery", AgentFeatureConfig(), (AblationFeature.AGENTIC_RECOVERY, AblationFeature.QUERY_REWRITE, AblationFeature.SUPPLEMENT, AblationFeature.CLARIFICATION)),
    ]
    configs: list[AblationConfig] = []
    previous = replace(full, feature_config=stages[0][1])
    for index, (name, flags, enabled) in enumerate(stages[1:], start=1):
        target = replace(full, feature_config=flags)
        configs.append(AblationConfig(name, AblationStudyType.ADDITION, previous, target, enabled_features=enabled, description="Controlled staged addition on the same Production graph"))
        previous = target
    return tuple(configs)


def _rate(pass_count: int, denominator: int) -> dict[str, Any]:
    return {"numerator": pass_count, "denominator": denominator, "rate": pass_count / denominator if denominator else None}


def compare_paired_metric(base_rows: Mapping[str, bool | None], target_rows: Mapping[str, bool | None]) -> dict[str, Any]:
    paired_ids = sorted(set(base_rows) & set(target_rows))
    usable = [cid for cid in paired_ids if base_rows[cid] is not None and target_rows[cid] is not None]
    if not usable:
        return {"paired_cases": 0, "base": _rate(0, 0), "ablated": _rate(0, 0), "delta_pp": None, "status": AblationRunStatus.NOT_RUN.value}
    b = sum(bool(base_rows[cid]) for cid in usable)
    t = sum(bool(target_rows[cid]) for cid in usable)
    br, tr = b / len(usable), t / len(usable)
    return {"paired_cases": len(usable), "base": _rate(b, len(usable)), "ablated": _rate(t, len(usable)), "delta_pp": (tr - br) * 100.0, "status": AblationRunStatus.EXPLORATORY.value if len(usable) < 30 else "FORMAL"}



def full_system_config_from_state(value: Mapping[str, Any]) -> FullSystemConfig:
    return FullSystemConfig(
        feature_config=AgentFeatureConfig.from_mapping(value.get("features") or {}),
        context_strategy=str(value.get("context_strategy") or "LIORIN_CONTEXT_MEMORY_ARTIFACT"),
        model=str(value.get("model")) if value.get("model") is not None else None,
        embedding=str(value.get("embedding")) if value.get("embedding") is not None else None,
        retrieval=dict(value.get("retrieval") or {}), budget=dict(value.get("budget") or {}),
        governance=dict(value.get("governance") or {}), tool_configuration=dict(value.get("tool_configuration") or {}),
    )


def ablation_config_from_state(value: Mapping[str, Any]) -> AblationConfig:
    return AblationConfig(
        ablation_id=str(value.get("ablation_id") or ""),
        study_type=AblationStudyType(str(value.get("study_type") or "REMOVAL").upper()),
        base_config=full_system_config_from_state(value.get("base_config") or {}),
        target_config=full_system_config_from_state(value.get("target_config") or {}),
        disabled_features=tuple(AblationFeature(str(x)) for x in value.get("disabled_features") or ()),
        enabled_features=tuple(AblationFeature(str(x)) for x in value.get("enabled_features") or ()),
        dataset_hash=str(value.get("dataset_hash")) if value.get("dataset_hash") else None,
        description=str(value.get("description") or ""),
    )

__all__ = [
    "ABLATION_SCHEMA_VERSION", "AblationStudyType", "AblationRunStatus", "AblationFeature",
    "FullSystemConfig", "AblationConfig", "AblationFairnessResult", "check_ablation_fairness",
    "removal_config", "default_removal_configs", "default_addition_configs", "compare_paired_metric", "full_system_config_from_state", "ablation_config_from_state",
]

class ControlledAblationRunner:
    """Run base and ablated Production configurations on identical case IDs."""

    def __init__(self, *, judge_runtime=None, adapter_factory=None) -> None:
        self.judge_runtime = judge_runtime
        self.adapter_factory = adapter_factory

    def _adapter(self, config: FullSystemConfig):
        if self.adapter_factory is not None:
            return self.adapter_factory(config)
        from eval_platform.production_adapter import ProductionEvaluationAdapter
        return ProductionEvaluationAdapter.for_feature_config(config.feature_config)

    def run(self, samples: Sequence[Any], config: AblationConfig, *, output_dir: str | None = None) -> dict[str, Any]:
        fairness = check_ablation_fairness(config)
        if not fairness.valid:
            return {"ablation_id": config.ablation_id, "status": AblationRunStatus.INVALID.value, "fairness": {"valid": False, "unexpected_differences": list(fairness.unexpected_differences)}}
        from eval_platform.runner import FormalEvaluationRunner
        from eval_platform.contracts import TaskSuccessStatus
        base_out = None
        target_out = None
        if output_dir:
            from pathlib import Path
            root = Path(output_dir); root.mkdir(parents=True, exist_ok=True)
            base_out = root / "base"; target_out = root / "ablated"
        base_run = FormalEvaluationRunner(production_adapter=self._adapter(config.base_config), judge_runtime=self.judge_runtime).run(
            samples, output_dir=base_out, production_config=config.base_config.to_state(), model=config.base_config.model, embedding=config.base_config.embedding
        )
        target_run = FormalEvaluationRunner(production_adapter=self._adapter(config.target_config), judge_runtime=self.judge_runtime).run(
            samples, output_dir=target_out, production_config=config.target_config.to_state(), model=config.target_config.model, embedding=config.target_config.embedding
        )
        base_rows = {j.case_id: j.task_success_bool for j in base_run.judgments if j.task_success_status is not None}
        target_rows = {j.case_id: j.task_success_bool for j in target_run.judgments if j.task_success_status is not None}
        task = compare_paired_metric(base_rows, target_rows)
        payload = {
            "schema_version": ABLATION_SCHEMA_VERSION,
            "ablation": config.to_state(),
            "status": task["status"],
            "fairness": {"valid": fairness.valid, "expected_differences": list(fairness.expected_differences)},
            "paired_case_ids": sorted(set(base_rows) & set(target_rows)),
            "task_success": task,
            "base_run_id": base_run.run_id,
            "ablated_run_id": target_run.run_id,
        }
        if output_dir:
            from pathlib import Path
            root = Path(output_dir)
            (root / "ablation_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            lines = ["# Controlled Ablation", "", f"Experiment: `{config.ablation_id}`", f"Status: **{payload['status']}**", f"Paired cases: {task['paired_cases']}"]
            if task["delta_pp"] is None:
                lines.append("Task Success delta: NOT RUN")
            else:
                lines.append(f"Task Success delta: {task['delta_pp']:+.2f} pp")
            (root / "ablation_summary.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
            rows = []
            for cid in sorted(set(base_rows) | set(target_rows)):
                rows.append({"case_id": cid, "base_task_success": base_rows.get(cid), "ablated_task_success": target_rows.get(cid)})
            with (root / "ablation_case_results.jsonl").open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True)+"\n")
        return payload

__all__.append("ControlledAblationRunner")
