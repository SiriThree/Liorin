from __future__ import annotations

from pathlib import Path

from eval_platform.cli import main


def test_context_experiment_cli_can_audit_unreviewed_dataset_without_loading_production(tmp_path: Path):
    root=Path(__file__).resolve().parents[2]
    dataset=root/"evals/benchmark/data/canonical/phase4_multi_turn_candidates_v1.json"
    rc=main(["experiment","context","--dataset",str(dataset),"--strategies","FULL_HISTORY,LIORIN_CONTEXT_MEMORY_ARTIFACT","--output",str(tmp_path)])
    assert rc==0
    assert (tmp_path/"context_experiment_run.json").exists()
    assert (tmp_path/"quality_cost_summary.json").exists()
