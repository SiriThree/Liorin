from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentConfig(StrictModel):
    agent_id: str
    role: Literal["annotator", "adjudicator"]
    backend: Literal["openai_compatible", "mock"] = "openai_compatible"
    provider: str = "openai-compatible"
    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    prompt_profile: str
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, ge=256)
    timeout_seconds: float = Field(default=120.0, gt=0)
    seed: int | None = None

    def api_key(self) -> str:
        if self.backend == "mock":
            return "mock"
        value = os.getenv(self.api_key_env, "")
        if not value:
            raise RuntimeError(
                f"missing API key for {self.agent_id}: environment variable {self.api_key_env} is empty"
            )
        return value

    @property
    def independence_signature(self) -> tuple[str, str, str]:
        return (self.provider.strip().lower(), self.base_url.rstrip("/").lower(), self.model.strip().lower())


class PipelineConfig(StrictModel):
    dataset_path: Path
    corpus_path: Path
    output_dir: Path
    annotator_a: AgentConfig
    annotator_b: AgentConfig
    adjudicator_c: AgentConfig
    top_k_source_context: int = Field(default=16, ge=4, le=50)
    retrieval_candidate_pool_size: int = Field(default=30, ge=10, le=100)
    max_source_packet_chars: int = Field(default=30000, ge=8000, le=120000)
    candidate_pool_paths: list[Path] = Field(default_factory=list)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    random_review_rate: float = Field(default=0.10, ge=0.0, le=1.0)
    random_seed: int = 20260805
    allow_correlated_agents: bool = False
    include_blind_samples: bool = True

    @model_validator(mode="after")
    def validate_roles_and_independence(self):
        if self.annotator_a.role != "annotator" or self.annotator_b.role != "annotator":
            raise ValueError("annotator_a and annotator_b must have role=annotator")
        if self.adjudicator_c.role != "adjudicator":
            raise ValueError("adjudicator_c must have role=adjudicator")
        ids = {self.annotator_a.agent_id, self.annotator_b.agent_id, self.adjudicator_c.agent_id}
        if len(ids) != 3:
            raise ValueError("A, B, and C must use three distinct agent_id values")
        if not self.allow_correlated_agents:
            signatures = {
                self.annotator_a.independence_signature,
                self.annotator_b.independence_signature,
                self.adjudicator_c.independence_signature,
            }
            if len(signatures) != 3:
                raise ValueError(
                    "strict independence requires three distinct provider/base_url/model signatures; "
                    "set allow_correlated_agents=true only with an explicit disclosure"
                )
        return self


def load_config(path: str | Path) -> PipelineConfig:
    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    base = config_path.parent.parent if config_path.parent.name == "configs" else config_path.parent
    for key in ["dataset_path", "corpus_path", "output_dir"]:
        value = Path(raw[key])
        if not value.is_absolute():
            raw[key] = str((base / value).resolve())
    pools = []
    for value in raw.get("candidate_pool_paths", []):
        p = Path(value)
        pools.append(str(p if p.is_absolute() else (base / p).resolve()))
    raw["candidate_pool_paths"] = pools
    return PipelineConfig.model_validate(raw)
