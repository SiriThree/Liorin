# Migration Dependency Report

## Runtime Used

- Python: target `.venv` via `.venv\Scripts\python.exe`
- OS shell: Windows PowerShell
- Network: enabled, but no real production Milvus/LLM blind-test run was claimed.

## Packaging Changes

`pyproject.toml` now includes the `retrieval` and `governance` packages and force-includes:

- `retrieval/verification_policy.json`
- `governance/degradation_matrix.json`
- `governance/release_gate_config.json`

## Real Dependencies Not Completed In This Migration

- Real Milvus production index is not validated as complete.
- Real three-model annotation is not executed.
- Blind Test formal evaluation is not executed.
- Release gate is not passed; it fails closed until a reviewed aggregate release report and non-null thresholds exist.

## Compatibility Fixes Made

- `langchain_core.documents.Document` tests now use current `page_content` / `metadata` construction.
- `evals/annotation_pipeline/io_utils.read_json()` accepts UTF-8 BOM via `utf-8-sig`, fixing Windows-generated JSON review files.
- `tools.__init__` uses lazy exports to avoid test/production import-order side effects.
- Authenticated principals can retrieve public/global public knowledge documents when no explicit tenant filter is supplied for `manual`, `policy`, or `faq`; private tenant ACLs remain default-deny.

## Source ZIP Baseline

The source ZIP test baseline was not green under the target runtime:

- Command: `D:\...\Liorin\.venv\Scripts\python.exe -m pytest -q tests evals\tests`
- Exit: `1`
- Key output: `112 passed, 25 failed`
- Main causes: old `Document(text, md)` construction and Windows default encoding reads.
