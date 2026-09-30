"""Comparable retrieval benchmark variants and resumable artifact writing."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evaluation.benchmark import file_checksum, load_benchmark, stable_checksum
from evaluation.models import BenchmarkEntry
from backend.app.models.request_response import RetrievalCandidate


class QueryEvaluationArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    benchmark_version: str
    corpus_identity: str
    query_id: str
    variant: str = Field(pattern=r"^(dense_only|hybrid|reranked|agentic)$")
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_filters: dict[str, Any]
    top_k: int = Field(ge=1)
    candidate_pmids: list[str]
    candidates: list[dict[str, Any]]
    latency_ms: float = Field(ge=0)
    hybrid_candidate_pool_pmids: list[str] | None = None
    research_plan: dict[str, Any] | None = None
    coverage: Any = None
    corrections: list[Any] | None = None
    evidence: list[Any] | None = None
    answer: dict[str, Any] | None = None
    citations: list[str] | None = None

    @model_validator(mode="after")
    def validate_variant_payload(self):
        candidate_ids = [str(item.get("pmid", "")) for item in self.candidates]
        if candidate_ids != self.candidate_pmids or len(candidate_ids) > self.top_k:
            raise ValueError("candidate IDs must match serialized candidates and respect top_k")
        if self.variant == "reranked":
            if self.hybrid_candidate_pool_pmids is None:
                raise ValueError("reranked artifacts must record the hybrid candidate pool")
            if len(self.hybrid_candidate_pool_pmids) < len(self.candidate_pmids):
                raise ValueError("reranked candidates must come from the recorded hybrid pool")
        if self.variant == "agentic" and any(
            value is None for value in (self.research_plan, self.coverage, self.corrections, self.evidence, self.answer, self.citations)
        ):
            raise ValueError("agentic artifacts require plan, coverage, correction, evidence, answer, and citation data")
        return self


class EvaluationVariant(Protocol):
    name: str

    def run(self, entry: BenchmarkEntry) -> QueryEvaluationArtifact: ...


def configuration_hash(configuration: Mapping[str, Any]) -> str:
    return stable_checksum(dict(configuration))


class _RetrievalVariant:
    name = ""
    channels: tuple[str, ...] = ()

    def __init__(self, *, planner: Any, retriever: Any, top_k: int, benchmark_version: str, corpus_identity: str, settings: Any = None):
        self.planner = planner
        self.retriever = retriever
        self.top_k = int(top_k)
        self.benchmark_version = str(benchmark_version)
        self.corpus_identity = str(corpus_identity)
        self.settings = settings

    def _plan(self, entry: BenchmarkEntry):
        filters = {"study_types": [entry.study_type]}
        return self.planner(entry.query, filters, route_override=entry.expected_route)

    def _configuration(self) -> dict[str, Any]:
        names = {
            "dense_only": ("DENSE_TOP_K", "MEDCPT_QUERY_ENCODER"),
            "hybrid": ("DENSE_TOP_K", "SPARSE_TOP_K", "RRF_K", "MAX_SUBQUERIES", "RERANKER_TOP_N", "MEDCPT_QUERY_ENCODER", "BM25_INDEX_PATH", "MESH_GRAPH_PATH"),
            "reranked": ("DENSE_TOP_K", "SPARSE_TOP_K", "RRF_K", "MAX_SUBQUERIES", "RERANKER_TOP_N", "MEDCPT_QUERY_ENCODER", "MEDCPT_CROSS_ENCODER", "BM25_INDEX_PATH", "MESH_GRAPH_PATH"),
            "agentic": ("MAX_CORRECTIVE_LOOPS", "MAX_SUBQUERIES", "RERANKER_TOP_N", "RRF_K", "MEDCPT_QUERY_ENCODER", "MEDCPT_CROSS_ENCODER"),
        }.get(self.name, ())
        return {
            "variant": self.name,
            "channels": self.channels,
            "top_k": self.top_k,
            "benchmark_version": self.benchmark_version,
            "corpus_identity": self.corpus_identity,
            "settings": {name: getattr(self.settings, name) for name in names if self.settings is not None and hasattr(self.settings, name)},
        }

    def _artifact(self, entry, plan, candidates, started, *, pool=None, **extra):
        return QueryEvaluationArtifact(
            benchmark_version=self.benchmark_version,
            corpus_identity=self.corpus_identity,
            query_id=entry.id,
            variant=self.name,
            configuration_hash=configuration_hash(self._configuration()),
            metadata_filters={"study_types": [entry.study_type]},
            top_k=self.top_k,
            candidate_pmids=[str(candidate.pmid) for candidate in candidates],
            candidates=[candidate.model_dump(mode="json") if hasattr(candidate, "model_dump") else dict(candidate) for candidate in candidates],
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            hybrid_candidate_pool_pmids=[str(candidate.pmid) for candidate in pool] if pool is not None else None,
            **extra,
        )


class DenseOnlyVariant(_RetrievalVariant):
    name = "dense_only"
    channels = ("dense_original",)

    def run(self, entry: BenchmarkEntry) -> QueryEvaluationArtifact:
        started = time.perf_counter()
        plan = self._plan(entry)
        candidates = self.retriever.search_channels(plan, channels=self.channels, top_k=self.top_k)
        return self._artifact(entry, plan, candidates, started)


class HybridVariant(_RetrievalVariant):
    name = "hybrid"
    channels = ("dense_original", "dense_canonical", "bm25", "mesh_graph")

    def run(self, entry: BenchmarkEntry) -> QueryEvaluationArtifact:
        started = time.perf_counter()
        plan = self._plan(entry)
        candidates = self.retriever.search_channels(plan, channels=self.channels, top_k=self._pool_size())
        return self._artifact(entry, plan, candidates, started)

    def _pool_size(self) -> int:
        return max(self.top_k, int(getattr(self.settings, "RERANKER_TOP_N", self.top_k)))


class RerankedVariant(HybridVariant):
    name = "reranked"

    def __init__(self, *, reranker: Any, **kwargs):
        super().__init__(**kwargs)
        self.reranker = reranker

    def _configuration(self):
        config = super()._configuration()
        config["variant"] = self.name
        config["settings"] = {
            name: getattr(self.settings, name)
            for name in ("RERANKER_TOP_N", "MEDCPT_CROSS_ENCODER")
            if self.settings is not None and hasattr(self.settings, name)
        }
        config["reranker"] = getattr(self.settings, "MEDCPT_CROSS_ENCODER", "production")
        return config

    def run(self, entry: BenchmarkEntry) -> QueryEvaluationArtifact:
        started = time.perf_counter()
        hybrid_artifact = HybridVariant(
            planner=self.planner,
            retriever=self.retriever,
            top_k=self.top_k,
            benchmark_version=self.benchmark_version,
            corpus_identity=self.corpus_identity,
            settings=self.settings,
        ).run(entry)
        pool = [RetrievalCandidate.model_validate(candidate) for candidate in hybrid_artifact.candidates]
        reranked, _trace = self.reranker.rerank(entry.query, pool, top_n=int(getattr(self.settings, "RERANKER_TOP_N", self.top_k)))
        return self._artifact(entry, None, reranked[:self.top_k], started, pool=pool)


class AgenticVariant(_RetrievalVariant):
    name = "agentic"

    def __init__(self, *, service: Any, top_k: int, benchmark_version: str, corpus_identity: str, settings: Any = None):
        super().__init__(planner=None, retriever=None, top_k=top_k, benchmark_version=benchmark_version, corpus_identity=corpus_identity, settings=settings)
        self.service = service

    def _configuration(self):
        return {
            "variant": self.name,
            "top_k": self.top_k,
            "settings": {
                name: getattr(self.settings, name)
                for name in ("MAX_CORRECTIVE_LOOPS", "MAX_SUBQUERIES", "RERANKER_TOP_N", "RRF_K", "MEDCPT_QUERY_ENCODER", "MEDCPT_CROSS_ENCODER")
                if self.settings is not None and hasattr(self.settings, name)
            },
            "benchmark_version": self.benchmark_version,
            "corpus_identity": self.corpus_identity,
        }

    def run(self, entry: BenchmarkEntry) -> QueryEvaluationArtifact:
        started = time.perf_counter()
        if hasattr(self.service, "research_benchmark_entry"):
            response, trace = self.service.research_benchmark_entry(
                entry, max_loops=int(getattr(self.settings, "MAX_CORRECTIVE_LOOPS", 2))
            )
        else:
            response = self.service.research(entry.query, user_filters={"study_types": [entry.study_type]}, max_loops=int(getattr(self.settings, "MAX_CORRECTIVE_LOOPS", 2)), route_floor=entry.expected_route)
            trace = self.service.get_trace(response.request_id) or {}
        candidates = list(response.retrieved_papers[:self.top_k])
        plan = trace.get("query_plan", {})
        return QueryEvaluationArtifact(
            benchmark_version=self.benchmark_version, corpus_identity=self.corpus_identity,
            query_id=entry.id, variant=self.name,
            configuration_hash=configuration_hash(self._configuration()),
            metadata_filters={"study_types": [entry.study_type]}, top_k=self.top_k,
            candidate_pmids=[str(item.pmid) for item in candidates],
            candidates=[item.model_dump(mode="json") for item in candidates],
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            research_plan=trace.get("research_plan", response.research_plan),
            coverage=trace.get("coverage_history", response.coverage_statuses),
            corrections=trace.get("corrective_queries", []),
            evidence=[item.model_dump(mode="json") for item in response.evidence_table],
            answer=response.model_dump(mode="json"), citations=list(response.cited_pmids),
        )


def write_artifact_atomic(path: str | Path, artifact: Mapping[str, Any] | QueryEvaluationArtifact) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = artifact.model_dump(mode="json") if isinstance(artifact, QueryEvaluationArtifact) else dict(artifact)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def run_evaluation(entries: Sequence[BenchmarkEntry], variants: Mapping[str, EvaluationVariant], *, output_dir: str | Path, query_id: str | None = None, resume: bool = False) -> dict[str, int]:
    output = Path(output_dir)
    selected = [entry for entry in entries if query_id is None or entry.id == query_id]
    result = {"written": 0, "skipped": 0}
    for name, variant in variants.items():
        for entry in selected:
            target = output / name / f"{entry.id}.json"
            if resume and target.exists():
                try:
                    existing = QueryEvaluationArtifact.model_validate_json(target.read_text(encoding="utf-8"))
                    expected_hash = configuration_hash(variant._configuration()) if hasattr(variant, "_configuration") else None
                    if (
                        existing.query_id == entry.id
                        and existing.variant == name
                        and existing.benchmark_version == getattr(variant, "benchmark_version", None)
                        and existing.corpus_identity == getattr(variant, "corpus_identity", None)
                        and existing.configuration_hash == expected_hash
                    ):
                        result["skipped"] += 1
                        continue
                except Exception:
                    pass
            artifact = variant.run(entry)
            QueryEvaluationArtifact.model_validate(artifact.model_dump(mode="json"))
            write_artifact_atomic(target, artifact)
            result["written"] += 1
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run comparable retrieval benchmark variants")
    parser.add_argument("--benchmark", type=Path, default=Path("data/evaluation/benchmark_v2.json"))
    parser.add_argument("--variant", choices=("dense_only", "hybrid", "reranked", "agentic", "all"), default="all")
    parser.add_argument("--query-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("data/evaluation/variants"))
    args = parser.parse_args(argv)
    dataset = load_benchmark(args.benchmark)
    corpus = Path(dataset.corpus_path)
    if not corpus.is_absolute():
        corpus = Path.cwd() / corpus
    identity = file_checksum(corpus)
    from backend.app.core.config import get_settings
    from backend.app.workflow.service import ResearchService

    settings = get_settings()
    service = ResearchService(settings)
    retriever = service._get_hybrid_retriever()
    variants = {
        "dense_only": DenseOnlyVariant(planner=service._build_plan, retriever=retriever, top_k=settings.RERANKER_TOP_N, benchmark_version=dataset.version, corpus_identity=identity, settings=settings),
        "hybrid": HybridVariant(planner=service._build_plan, retriever=retriever, top_k=settings.RERANKER_TOP_N, benchmark_version=dataset.version, corpus_identity=identity, settings=settings),
        "reranked": RerankedVariant(planner=service._build_plan, retriever=retriever, reranker=service._get_reranker(), top_k=settings.RERANKER_TOP_N, benchmark_version=dataset.version, corpus_identity=identity, settings=settings),
        "agentic": AgenticVariant(service=service, top_k=settings.RERANKER_TOP_N, benchmark_version=dataset.version, corpus_identity=identity, settings=settings),
    }
    selected = variants if args.variant == "all" else {args.variant: variants[args.variant]}
    print(json.dumps(run_evaluation(dataset.entries, selected, output_dir=args.output_dir, query_id=args.query_id, resume=args.resume), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
