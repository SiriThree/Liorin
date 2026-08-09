from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.annotation_pipeline.backends import BackendError, JSONBackend
from evals.annotation_pipeline.config import AgentConfig
from evals.benchmark.expansion.d3_annotation import (
    annotation_request_semantic_hash,
    build_annotation_request,
)
from evals.benchmark.expansion.d3_runtime import (
    annotation_runtime_readiness,
    provider_smoke,
    run_d3r_runtime_recovery,
    select_pilot_packets,
)

ROOT = Path(__file__).resolve().parents[2]
D2 = ROOT / "artifacts/evaluation/dataset-expansion-d2"
D3 = ROOT / "artifacts/evaluation/dataset-expansion-d3"
EXAMPLE = ROOT / "evals/benchmark/configs/private_business_dual_annotation.example.yaml"


def _packets():
    return [json.loads(x) for x in (D2 / "private_business_annotation_packets.jsonl").read_text().splitlines() if x.strip()]


def _cfg(agent_id="a"):
    return AgentConfig(
        agent_id=agent_id,
        role="annotator",
        backend="openai_compatible",
        provider="provider-real",
        model="model-real",
        base_url="https://runtime.local/v1",
        api_key_env=f"{agent_id.upper()}_KEY",
        prompt_profile="private_gold_review_v1",
        temperature=0,
        max_tokens=1000,
        timeout_seconds=1,
        max_retries=2,
    )


class SmokeBackend(JSONBackend):
    def __init__(self, config, value):
        super().__init__(config)
        self.value = value

    def complete_json(self, system, user, schema):
        self.last_http_attempt_count = 1
        if isinstance(self.value, Exception):
            raise self.value
        raw = json.dumps(self.value)
        return self.value, raw


def test_example_runtime_readiness_is_blocked_and_batch_stays_frozen(tmp_path, monkeypatch):
    monkeypatch.delenv("ANNOTATOR_A_API_KEY", raising=False)
    monkeypatch.delenv("ANNOTATOR_B_API_KEY", raising=False)
    result = annotation_runtime_readiness(D2, tmp_path / "out", EXAMPLE)
    assert result["status"] == "BLOCKED"
    assert result["batch"]["packet_count"] == 76
    assert result["batch"]["excluded_precheck"] == 8
    assert result["batch"]["packet_hashes_valid"] is True
    assert "PLACEHOLDER_PROVIDER" in result["annotator_a"]["placeholder_issues"]
    assert result["annotator_a"]["credential_configured"] is False


def test_placeholder_config_does_not_become_ready_just_because_key_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNOTATOR_A_API_KEY", "secret-a")
    monkeypatch.setenv("ANNOTATOR_B_API_KEY", "secret-b")
    result = annotation_runtime_readiness(D2, tmp_path / "out", EXAMPLE)
    assert result["status"] == "BLOCKED"
    assert not result["annotator_a"]["ready"]
    assert not result["annotator_b"]["ready"]
    text = json.dumps(result)
    assert "secret-a" not in text and "secret-b" not in text


def test_one_side_ready_other_missing_credential_is_partial(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text('''annotator_a:\n  agent_id: a\n  role: annotator\n  backend: openai_compatible\n  provider: pa\n  model: ma\n  base_url: https://127.0.0.1:9998/v1\n  api_key_env: A_KEY\n  prompt_profile: private_gold_review_v1\nannotator_b:\n  agent_id: b\n  role: annotator\n  backend: openai_compatible\n  provider: pb\n  model: mb\n  base_url: https://127.0.0.1:9999/v1\n  api_key_env: B_KEY\n  prompt_profile: private_gold_review_v1\n''')
    monkeypatch.setenv("A_KEY", "x")
    monkeypatch.delenv("B_KEY", raising=False)
    result = annotation_runtime_readiness(D2, tmp_path / "out", cfg)
    assert result["status"] == "PARTIAL"
    assert result["annotator_a"]["ready"] is True
    assert result["annotator_b"]["ready"] is False


def test_provider_smoke_is_infrastructure_only(monkeypatch):
    cfg = _cfg("a")
    monkeypatch.setenv("A_KEY", "x")
    backend = SmokeBackend(cfg, {"status": "OK", "probe_version": "private-business-annotator-provider-smoke-v1"})
    result = provider_smoke(cfg, backend=backend)
    assert result["status"] == "PASS"
    assert result["annotation_quality_result"] == "NOT_APPLICABLE"
    assert result["provider_attempt_count"] == 1


def test_provider_smoke_failure_is_not_annotation_reject(monkeypatch):
    cfg = _cfg("a")
    monkeypatch.setenv("A_KEY", "x")
    result = provider_smoke(cfg, backend=SmokeBackend(cfg, BackendError("timeout")))
    assert result["status"] == "FAIL"
    assert result["annotation_quality_result"] == "NOT_APPLICABLE"
    assert "timeout" in result["error"]


def test_semantic_request_hash_is_same_for_a_and_b():
    packet = _packets()[0]
    sa, ua, _ = build_annotation_request(packet, annotator_id="a", provider="pa", model="ma", run_id="ra")
    sb, ub, _ = build_annotation_request(packet, annotator_id="b", provider="pb", model="mb", run_id="rb")
    assert ua != ub
    assert annotation_request_semantic_hash(sa, ua) == annotation_request_semantic_hash(sb, ub)


def test_pilot_selection_is_deterministic_and_covers_domains_and_multifield():
    packets = _packets()
    a = select_pilot_packets(packets, 6)
    b = select_pilot_packets(packets, 6)
    assert [x["candidate_id"] for x in a] == [x["candidate_id"] for x in b]
    types = {x["source_snapshot"]["record_type"] for x in a}
    assert {"order", "ticket", "warranty"} <= types
    assert any(len(x["gold_draft"]["gold_facts_draft"]) > 1 for x in a)
    assert any(x["semantic_family_id"] == "TICKET_SUMMARY_LOOKUP" for x in a)


def test_check_only_makes_no_provider_calls_or_decisions(tmp_path, monkeypatch):
    monkeypatch.delenv("ANNOTATOR_A_API_KEY", raising=False)
    monkeypatch.delenv("ANNOTATOR_B_API_KEY", raising=False)
    out = tmp_path / "real-run"
    summary = run_d3r_runtime_recovery(ROOT, D2, D3, out, EXAMPLE, check_only=True)
    assert summary["mode"] == "CHECK_ONLY"
    assert summary["provider_call_count_a"] == 0
    assert summary["provider_call_count_b"] == 0
    runtime = json.loads((out / "annotation_runtime_manifest.json").read_text())
    assert runtime["historical_d3_preserved"] is True
    assert runtime["provider_call_count_a"] == 0


def test_blocked_real_run_has_76_incomplete_and_zero_agreement_denominator(tmp_path, monkeypatch):
    monkeypatch.delenv("ANNOTATOR_A_API_KEY", raising=False)
    monkeypatch.delenv("ANNOTATOR_B_API_KEY", raising=False)
    out = tmp_path / "real-run"
    summary = run_d3r_runtime_recovery(ROOT, D2, D3, out, EXAMPLE)
    assert summary["status"] == "PARTIAL"
    assert summary["actual_dual_annotation"] == "BLOCKED"
    assert summary["annotator_a_real_calls"] == 0
    assert summary["annotator_b_real_calls"] == 0
    incomplete = [json.loads(x) for x in (out / "annotation_incomplete.jsonl").read_text().splitlines() if x.strip()]
    assert len(incomplete) == 76
    agreement = json.loads((out / "annotation_agreement_summary.json").read_text())
    assert agreement["overall_decision_agreement"]["denominator"] == 0
    assert (out / "annotator_a_decisions.jsonl").read_text() == ""
    assert (out / "annotator_b_decisions.jsonl").read_text() == ""


def test_formal_canonical_is_still_39():
    canonical = ROOT / "evals/benchmark/data/canonical"
    total = sum(len(json.loads((canonical / n).read_text())) for n in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"))
    assert total == 39


def test_openai_compatible_backend_does_not_retry_auth_error(monkeypatch):
    from evals.annotation_pipeline.backends import NonRetryableBackendError, OpenAICompatibleBackend

    class Resp:
        status_code = 401
        text = "unauthorized"

    class Client:
        def __init__(self): self.calls = 0
        def post(self, *args, **kwargs): self.calls += 1; return Resp()
        def close(self): pass

    cfg = _cfg("a")
    monkeypatch.setenv("A_KEY", "x")
    backend = OpenAICompatibleBackend(cfg)
    client = Client(); backend.client.close(); backend.client = client
    with pytest.raises(NonRetryableBackendError):
        backend.complete_json("s", "u", {})
    assert client.calls == 1
    assert backend.last_http_attempt_count == 1


def test_openai_compatible_backend_retries_rate_limit_then_succeeds(monkeypatch):
    from evals.annotation_pipeline.backends import OpenAICompatibleBackend
    import evals.annotation_pipeline.backends as backends

    class Resp:
        def __init__(self, status, payload=None):
            self.status_code = status
            self.text = "rate" if status != 200 else "ok"
            self._payload = payload
        def json(self): return self._payload

    class Client:
        def __init__(self): self.calls = 0
        def post(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1: return Resp(429)
            return Resp(200, {"choices": [{"message": {"content": '{"status":"OK"}'}}]})
        def close(self): pass

    cfg = _cfg("a")
    monkeypatch.setenv("A_KEY", "x")
    monkeypatch.setattr(backends.time, "sleep", lambda _: None)
    backend = OpenAICompatibleBackend(cfg)
    client = Client(); backend.client.close(); backend.client = client
    parsed, _ = backend.complete_json("s", "u", {})
    assert parsed == {"status":"OK"}
    assert client.calls == 2
    assert backend.last_http_attempt_count == 2
