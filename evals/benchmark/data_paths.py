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
    "blind": DATA_DIR / "blind_test_inputs_v7_3.json",
}

CORPUS_PATH = CORPUS_DIR / "corpus_v7_3.json"
FACT_REGISTRY_PATH = CORPUS_DIR / "fact_registry_v7_3.json"
