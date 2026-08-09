"""Shared paths for the public benchmark assets."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CORPUS_DIR = ROOT / "corpus"
SCHEMA_DIR = ROOT / "schemas"
REPORT_DIR = ROOT / "reports"

DATASETS = {
    "dev": DATA_DIR / "dev_v7_3.json",
    "validation": DATA_DIR / "validation_v7_3.json",
    # Historical name retained for compatibility. Phase 0 cannot prove that this
    # split has remained unseen throughout prior tuning, so it is not a trusted
    # blind/test claim until a fresh controlled run is established.
    "blind": DATA_DIR / "blind_test_inputs_v7_3.json",
}

DATASET_TRUST_STATUS = {
    "dev": "DEVELOPMENT",
    "validation": "VALIDATION",
    "blind": "HISTORICAL_BLIND_INPUTS_UNVERIFIED",
}

CORPUS_PATH = CORPUS_DIR / "corpus_v7_3.json"
FACT_REGISTRY_PATH = CORPUS_DIR / "fact_registry_v7_3.json"
