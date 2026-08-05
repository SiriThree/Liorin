#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from annotation_pipeline import AnnotationPipeline, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run independent A/B annotation, C-only disagreement adjudication, and build human review queue.")
    parser.add_argument("--config", required=True, help="YAML pipeline config")
    args = parser.parse_args()
    config = load_config(args.config)
    pipeline = AnnotationPipeline(config)
    manifest = pipeline.run()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
