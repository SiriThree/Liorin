from __future__ import annotations

from pathlib import Path

from eval_platform import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalEvaluationSample,
    EvaluationSample,
    TaskCategory,
    build_representative_seed_cases,
    canonical_dataset_hash,
    read_canonical_dataset,
    validate_dataset,
    write_canonical_dataset,
)


def test_canonical_sample_is_phase0_evaluation_sample_not_parallel_type():
    assert CanonicalEvaluationSample is EvaluationSample


def test_representative_seed_covers_five_primary_categories_and_validates():
    samples = build_representative_seed_cases(Path.cwd())
    assert len(samples) == 15
    assert {sample.category for sample in samples} == set(TaskCategory)
    result = validate_dataset(samples)
    assert result.valid
    assert result.case_count == 15


def test_canonical_json_and_jsonl_roundtrip_preserve_schema_and_hash(tmp_path: Path):
    samples = build_representative_seed_cases(Path.cwd())
    expected_hash = canonical_dataset_hash(samples)
    for suffix in ("json", "jsonl"):
        path = tmp_path / f"canonical.{suffix}"
        write_canonical_dataset(path, samples)
        loaded = read_canonical_dataset(path)
        assert all(sample.schema_version == CANONICAL_SCHEMA_VERSION for sample in loaded)
        assert [sample.to_dict() for sample in loaded] == [sample.to_dict() for sample in samples]
        assert canonical_dataset_hash(loaded) == expected_hash


def test_same_canonical_data_has_same_hash_independent_of_order():
    samples = build_representative_seed_cases(Path.cwd())
    assert canonical_dataset_hash(samples) == canonical_dataset_hash(tuple(reversed(samples)))


def test_unknown_canonical_and_nested_fields_fail_closed():
    samples = build_representative_seed_cases(Path.cwd())
    payload = samples[0].to_dict()
    payload["unexpected"] = "must fail"
    import pytest
    with pytest.raises(ValueError, match="unknown canonical sample"):
        EvaluationSample.from_dict(payload)

    payload = samples[0].to_dict()
    payload["expected_behavior"]["mystery"] = True
    with pytest.raises(ValueError, match="unknown ExpectedBehavior"):
        EvaluationSample.from_dict(payload)


def test_alternative_evidence_and_handoff_contract_roundtrip():
    from dataclasses import replace
    from eval_platform import (
        ExpectedBehavior,
        GoldEvidence,
        EvidenceSourceType,
        ResponseType,
        SuccessCriterion,
        TaskSuccessContract,
    )

    base = build_representative_seed_cases(Path.cwd())[0]
    e1 = GoldEvidence(
        evidence_id="doc:policy#a",
        source_type=EvidenceSourceType.DOCUMENT,
        document_id="policy",
        section_id="a",
        alternative_group="policy_equivalent_v1",
    )
    e2 = GoldEvidence(
        evidence_id="doc:faq#b",
        source_type=EvidenceSourceType.DOCUMENT,
        document_id="faq",
        section_id="b",
        alternative_group="policy_equivalent_v1",
    )
    sample = replace(
        base,
        expected_behavior=ExpectedBehavior(
            response_type=ResponseType.HANDOFF,
            clarification_required=False,
            handoff_required=True,
            handoff_reason="human_review_required",
        ),
        task_success_contract=TaskSuccessContract((
            SuccessCriterion.RESPONSE_TYPE_CORRECT,
            SuccessCriterion.HANDOFF_CORRECT,
        )),
        gold_evidence=(e1, e2),
        gold_facts=(),
    )
    loaded = EvaluationSample.from_dict(sample.to_dict())
    assert loaded.gold_evidence[0].alternative_group == "policy_equivalent_v1"
    assert loaded.gold_evidence[1].alternative_group == "policy_equivalent_v1"
    assert loaded.expected_behavior.handoff_required is True
    assert SuccessCriterion.HANDOFF_CORRECT in loaded.task_success_contract.required_criteria


def test_identity_mapping_never_invents_principal():
    import pytest
    from eval_platform import RuntimeCaseInput

    with pytest.raises(ValueError, match="requires tenant_id and user_id"):
        RuntimeCaseInput(
            case_id="identity-incomplete",
            messages=({"role": "user", "content": "hello"},),
            identity={"tenant_id": "tenant:a"},
        )


def test_invalid_split_enum_is_rejected():
    import pytest
    sample = build_representative_seed_cases(Path.cwd())[0]
    payload = sample.to_dict()
    payload["split"] = "BLIND_BY_FILENAME"
    with pytest.raises(ValueError):
        EvaluationSample.from_dict(payload)
