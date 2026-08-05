#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from annotation_pipeline.models import (
    QueryUnderstandingAnnotation,
    RoutingAnnotation,
    RetrievalAnnotation,
    AnswerGenerationAnnotation,
    AgentBehaviorAnnotation,
    EndToEndAnnotation,
    AdjudicationResponse,
)

MODELS = {
    "query_understanding.annotation.schema.json": QueryUnderstandingAnnotation,
    "routing.annotation.schema.json": RoutingAnnotation,
    "retrieval.annotation.schema.json": RetrievalAnnotation,
    "answer_generation.annotation.schema.json": AnswerGenerationAnnotation,
    "agent_behavior.annotation.schema.json": AgentBehaviorAnnotation,
    "end_to_end.annotation.schema.json": EndToEndAnnotation,
    "adjudication_response.schema.json": AdjudicationResponse,
}


def main() -> None:
    output = ROOT / "schemas" / "annotations"
    output.mkdir(parents=True, exist_ok=True)
    for name, model in MODELS.items():
        (output / name).write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"Wrote {len(MODELS)} schemas to {output}")


if __name__ == "__main__":
    main()
