"""Construction-level comparison contracts mapped onto canonical evaluator modes."""
from __future__ import annotations
from collections import Counter
from typing import Any, Mapping


def comparison_report(drafts: list[Mapping[str, Any]]) -> dict[str, Any]:
    construction=Counter(); evaluator=Counter()
    for d in drafts:
        for f in d["gold_facts"]:
            if f["fact_role"] not in {"ANSWER_REQUIRED","REASONING_REQUIRED"}:
                continue
            construction[f["comparison_mode"]]+=1
            evaluator[f["evaluator_comparison_mode"]]+=1
    return {"construction_modes":dict(sorted(construction.items())),"evaluator_modes":dict(sorted(evaluator.items()))}
