from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from eval_platform import (
    DatasetValidationError,
    ExpectedBehavior,
    GoldEvidence,
    GoldFact,
    ResponseType,
    SuccessCriterion,
    TaskCategory,
    TaskSuccessContract,
    build_representative_seed_cases,
    validate_dataset,
)


def _seed(case_id: str):
    return next(s for s in build_representative_seed_cases(Path.cwd()) if s.sample_id == case_id)


def test_duplicate_case_id_fails_closed():
    sample = _seed("SEED-KNOW-FAQ-001")
    with pytest.raises(DatasetValidationError, match="duplicate case_id"):
        validate_dataset((sample, sample))


def test_invalid_category_subcategory_fails_closed():
    sample = _seed("SEED-KNOW-FAQ-001")
    invalid = replace(sample, subcategory="ORDER")
    with pytest.raises(DatasetValidationError, match="incompatible"):
        validate_dataset((invalid,))


def test_required_and_forbidden_tool_conflict_fails_closed():
    sample = _seed("SEED-KNOW-FAQ-001")
    invalid = replace(sample, expected_behavior=replace(sample.expected_behavior, required_tools=("x",), forbidden_tools=("x",)))
    with pytest.raises(DatasetValidationError, match="both required and forbidden"):
        validate_dataset((invalid,))


def test_private_query_without_identity_fails_closed():
    sample = _seed("SEED-PRIVATE-ORDER-001")
    invalid = replace(sample, runtime_input=replace(sample.runtime_input, identity=None))
    with pytest.raises(DatasetValidationError, match="requires identity"):
        validate_dataset((invalid,))


def test_invalid_mixed_case_without_structured_evidence_fails_closed():
    sample = _seed("SEED-MIXED-ORDER-POLICY-001")
    only_documents = tuple(e for e in sample.gold_evidence if e.source_type.value == "DOCUMENT")
    invalid = replace(sample, gold_evidence=only_documents, gold_facts=())
    with pytest.raises(DatasetValidationError, match="mixed case requires"):
        validate_dataset((invalid,))


def test_missing_evidence_reference_fails_closed():
    sample = _seed("SEED-KNOW-FAQ-001")
    fact = replace(sample.gold_facts[0], supporting_evidence_ids=("missing:evidence",))
    invalid = replace(sample, gold_facts=(fact,))
    with pytest.raises(DatasetValidationError, match="references missing evidence"):
        validate_dataset((invalid,))


def test_clarification_without_slots_fails_closed():
    sample = _seed("SEED-TRBL-CLARIFY-001")
    invalid = replace(sample, expected_behavior=replace(sample.expected_behavior, required_clarification_slots=()))
    with pytest.raises(DatasetValidationError, match="requires at least one slot"):
        validate_dataset((invalid,))


def test_empty_success_contract_fails_closed():
    sample = _seed("SEED-KNOW-FAQ-001")
    invalid = replace(sample, task_success_contract=TaskSuccessContract(()))
    with pytest.raises(DatasetValidationError, match="required_criteria must not be empty"):
        validate_dataset((invalid,))
