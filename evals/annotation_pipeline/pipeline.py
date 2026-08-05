from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .agents import AdjudicationAgent, AnnotationAgent, validate_annotation_against_packet
from .agreement import build_agreement_report
from .backends import make_backend
from .compare import diff_annotations, merge_with_resolutions
from .config import PipelineConfig
from .io_utils import (
    append_jsonl,
    index_by,
    read_json,
    read_jsonl,
    sha256_json,
    sha256_text,
    utc_now,
    write_json_atomic,
)
from .models import AdjudicatedRecord, AnnotationEnvelope
from .review_queue import build_review_queue
from .source_index import SourceIndex


class AnnotationPipeline:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.samples = self._load_samples()
        self.sample_by_id = {sample["id"]: sample for sample in self.samples}
        self.source_index = SourceIndex(str(config.corpus_path), [str(p) for p in config.candidate_pool_paths])
        self.annotator_a = AnnotationAgent(config.annotator_a, make_backend(config.annotator_a))
        self.annotator_b = AnnotationAgent(config.annotator_b, make_backend(config.annotator_b))
        self.adjudicator_c = AdjudicationAgent(config.adjudicator_c, make_backend(config.adjudicator_c))
        self.paths = {
            "packets": self.output_dir / "source_packets.jsonl",
            "a": self.output_dir / "annotator_a.jsonl",
            "b": self.output_dir / "annotator_b.jsonl",
            "c": self.output_dir / "adjudicator_c.jsonl",
            "adjudicated": self.output_dir / "adjudicated.jsonl",
            "agreement": self.output_dir / "agreement_report.json",
            "review": self.output_dir / "human_review_queue.json",
            "manifest": self.output_dir / "run_manifest.json",
            "spec": self.output_dir / "run_spec.json",
        }
        self._ensure_run_spec()

    def _ensure_run_spec(self) -> None:
        module_dir = Path(__file__).resolve().parent
        code_files = sorted(module_dir.glob("*.py"))
        candidate_pool_hashes = {}
        for candidate_path in self.config.candidate_pool_paths:
            path = Path(candidate_path)
            candidate_pool_hashes[str(path)] = sha256_text(path.read_text(encoding="utf-8"))
        spec = {
            "pipeline_version": "v7.4.2",
            "code_sha256": {path.name: sha256_text(path.read_text(encoding="utf-8")) for path in code_files},
            "dataset_sha256": sha256_json(self.samples),
            "corpus_sha256": sha256_json(self.source_index.corpus),
            "candidate_pool_sha256": candidate_pool_hashes,
            "agents": {
                "A": self.config.annotator_a.model_dump(mode="json"),
                "B": self.config.annotator_b.model_dump(mode="json"),
                "C": self.config.adjudicator_c.model_dump(mode="json"),
            },
            "packet_settings": {
                "top_k_source_context": self.config.top_k_source_context,
                "retrieval_candidate_pool_size": self.config.retrieval_candidate_pool_size,
                "max_source_packet_chars": self.config.max_source_packet_chars,
            },
        }
        spec_hash = sha256_json(spec)
        payload = {"spec_hash": spec_hash, "spec": spec}
        if self.paths["spec"].exists():
            existing = read_json(self.paths["spec"])
            if existing.get("spec_hash") != spec_hash:
                raise RuntimeError(
                    "output_dir already belongs to a different dataset/model/prompt configuration; "
                    "use a new output_dir or remove the previous run"
                )
        else:
            write_json_atomic(self.paths["spec"], payload)

    def _load_samples(self) -> list[dict[str, Any]]:
        rows = read_json(self.config.dataset_path)
        if not isinstance(rows, list):
            raise ValueError("dataset must be a JSON array")
        if not self.config.include_blind_samples:
            rows = [row for row in rows if row.get("split") != "blind_test"]
        ids = [str(row.get("id")) for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("dataset contains duplicate sample ids")
        return rows

    def build_packets(self) -> dict[str, dict[str, Any]]:
        existing = index_by(read_jsonl(self.paths["packets"]), "sample_id") if self.paths["packets"].exists() else {}
        for sample in self.samples:
            if sample["id"] in existing:
                continue
            packet = self.source_index.build_packet(
                sample,
                top_k=self.config.top_k_source_context,
                retrieval_pool_size=self.config.retrieval_candidate_pool_size,
                max_chars=self.config.max_source_packet_chars,
            )
            # Security invariant: packet is constructed from id/layer/input + retrieved source context only.
            def forbidden_paths(value, path=""):
                found=[]
                if isinstance(value, dict):
                    for key, child in value.items():
                        child_path=f"{path}/{key}"
                        if key in {"gold", "annotation", "split"}:
                            found.append(child_path)
                        found.extend(forbidden_paths(child, child_path))
                elif isinstance(value, list):
                    for i, child in enumerate(value):
                        found.extend(forbidden_paths(child, f"{path}/{i}"))
                return found
            forbidden = forbidden_paths(packet)
            if forbidden:
                raise AssertionError(f"gold-leaking packet paths: {forbidden[:20]}")
            append_jsonl(self.paths["packets"], packet)
            existing[sample["id"]] = packet
        return existing

    def run_annotators(self, packets: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows_a = self._run_one_annotator(self.annotator_a, packets, self.paths["a"])
        rows_b = self._run_one_annotator(self.annotator_b, packets, self.paths["b"])
        return rows_a, rows_b

    def _run_one_annotator(
        self,
        agent: AnnotationAgent,
        packets: dict[str, dict[str, Any]],
        output_path: Path,
    ) -> list[dict[str, Any]]:
        existing_rows = read_jsonl(output_path)
        existing = index_by(existing_rows, "sample_id") if existing_rows else {}
        missing = [packet for sid, packet in packets.items() if sid not in existing]

        def call(packet: dict[str, Any]) -> dict[str, Any]:
            return agent.annotate(packet).model_dump(mode="json")

        if missing:
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {pool.submit(call, packet): packet["sample_id"] for packet in missing}
                for future in as_completed(futures):
                    row = future.result()
                    append_jsonl(output_path, row)
                    existing[row["sample_id"]] = row
        return [existing[sample["id"]] for sample in self.samples]

    def adjudicate(
        self,
        packets: dict[str, dict[str, Any]],
        rows_a: list[dict[str, Any]],
        rows_b: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        a_by_id = index_by(rows_a, "sample_id")
        b_by_id = index_by(rows_b, "sample_id")
        existing_rows = read_jsonl(self.paths["adjudicated"])
        existing = index_by(existing_rows, "sample_id") if existing_rows else {}
        c_existing_rows = read_jsonl(self.paths["c"])
        c_existing = index_by(c_existing_rows, "sample_id") if c_existing_rows else {}

        for sample in self.samples:
            sample_id = sample["id"]
            if sample_id in existing:
                continue
            annotation_a = a_by_id[sample_id]["annotation"]
            annotation_b = b_by_id[sample_id]["annotation"]
            conflicts = diff_annotations(annotation_a, annotation_b)
            adjudicator_response = None
            if conflicts:
                if sample_id in c_existing:
                    from .models import AdjudicationResponse
                    response = AdjudicationResponse.model_validate(c_existing[sample_id]["response"])
                else:
                    response, request_hash, raw_hash, attempt_count, validation_errors = self.adjudicator_c.adjudicate(
                        packets[sample_id], annotation_a, annotation_b, conflicts
                    )
                    c_row = {
                        "sample_id": sample_id,
                        "layer": sample["layer"],
                        "adjudicator_id": self.config.adjudicator_c.agent_id,
                        "provider": self.config.adjudicator_c.provider,
                        "model": self.config.adjudicator_c.model,
                        "prompt_profile": self.config.adjudicator_c.prompt_profile,
                        "request_hash": request_hash,
                        "raw_response_sha256": raw_hash,
                        "attempt_count": attempt_count,
                        "validation_errors": validation_errors,
                        "response": response.model_dump(mode="json"),
                        "created_at": utc_now(),
                    }
                    append_jsonl(self.paths["c"], c_row)
                    c_existing[sample_id] = c_row
                final_annotation = merge_with_resolutions(
                    annotation_a,
                    annotation_b,
                    conflicts,
                    [item.model_dump(mode="json") for item in response.resolutions],
                )
                final_annotation["quality_status"] = response.quality_status
                final_annotation["quality_issues"] = response.quality_issues
                final_annotation["confidence"] = response.confidence
                final_annotation["rationale"] = response.rationale
                final_model = AnnotationEnvelope.model_validate({"annotation": final_annotation}).annotation
                validate_annotation_against_packet(final_model, packets[sample_id])
                final_annotation = final_model.model_dump(mode="json")
                adjudicator_response = response
            else:
                final_annotation = annotation_a

            record = AdjudicatedRecord(
                sample_id=sample_id,
                layer=sample["layer"],
                had_disagreement=bool(conflicts),
                conflict_paths=[item["path"] for item in conflicts],
                annotation_a=AnnotationEnvelope.model_validate({"annotation": annotation_a}).annotation,
                annotation_b=AnnotationEnvelope.model_validate({"annotation": annotation_b}).annotation,
                adjudicator_response=adjudicator_response,
                final_annotation=AnnotationEnvelope.model_validate({"annotation": final_annotation}).annotation,
                created_at=utc_now(),
            ).model_dump(mode="json")
            append_jsonl(self.paths["adjudicated"], record)
            existing[sample_id] = record
        return [existing[sample["id"]] for sample in self.samples]

    def finalize(
        self,
        packets: dict[str, dict[str, Any]],
        rows_a: list[dict[str, Any]],
        rows_b: list[dict[str, Any]],
        adjudicated: list[dict[str, Any]],
    ) -> dict[str, Any]:
        agreement = build_agreement_report(rows_a, rows_b)
        write_json_atomic(self.paths["agreement"], agreement)
        review_queue = build_review_queue(
            self.samples,
            packets,
            adjudicated,
            random_review_rate=self.config.random_review_rate,
            seed=self.config.random_seed,
        )
        write_json_atomic(self.paths["review"], review_queue)
        manifest = {
            "version": "v7.4-annotation-pipeline",
            "created_at": utc_now(),
            "dataset_path": str(self.config.dataset_path),
            "dataset_sha256": sha256_json(self.samples),
            "corpus_path": str(self.config.corpus_path),
            "corpus_sha256": sha256_json(self.source_index.corpus),
            "sample_count": len(self.samples),
            "annotators": {
                "A": self.config.annotator_a.model_dump(mode="json", exclude={"api_key_env"}),
                "B": self.config.annotator_b.model_dump(mode="json", exclude={"api_key_env"}),
                "C": self.config.adjudicator_c.model_dump(mode="json", exclude={"api_key_env"}),
            },
            "independence": {
                "strict": not self.config.allow_correlated_agents,
                "signatures": [
                    self.config.annotator_a.independence_signature,
                    self.config.annotator_b.independence_signature,
                    self.config.adjudicator_c.independence_signature,
                ],
            },
            "counts": {
                "annotator_a": len(rows_a),
                "annotator_b": len(rows_b),
                "disagreements": sum(row["had_disagreement"] for row in adjudicated),
                "adjudicator_calls": sum(row["adjudicator_response"] is not None for row in adjudicated),
                "human_review_queue": len(review_queue),
            },
            "human_review_policy": {
                "all_disagreements": True,
                "all_high_risk": True,
                "random_consensus_rate": self.config.random_review_rate,
                "random_seed": self.config.random_seed,
            },
        }
        write_json_atomic(self.paths["manifest"], manifest)
        return manifest

    def run(self) -> dict[str, Any]:
        packets = self.build_packets()
        rows_a, rows_b = self.run_annotators(packets)
        adjudicated = self.adjudicate(packets, rows_a, rows_b)
        return self.finalize(packets, rows_a, rows_b, adjudicated)
