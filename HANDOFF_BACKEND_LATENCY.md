# Backend latency handoff

## Checkpoint

This checkpoint instruments the backend research graph and records timing data in the existing administrator-only trace. Normal users still receive no query plan, trace, evidence spans, retrieval diagnostics, or timing metadata.

## Implemented in this checkpoint

- Added per-node workflow timings and retrieval-pass timings to `/trace/{request_id}` and admin `/search` output.
- Added synthesis generation/validation timing metadata.
- Changed NVIDIA synthesis to ask for validated PMID/span-index selections, then render the selected source spans locally. Invalid provider output falls back to deterministic source spans.
- Disabled Nemotron reasoning for the short judge/synthesis calls, disabled OpenAI-compatible client retries, bounded synthesis output, skipped NIM calls when no evidence exists, and serialized shared retrieval/reranker passes.
- Added `MEDCPT_KEEP_MODELS_LOADED`; set it to `true` locally in `.env` for this workstation, while `.env.example` defaults to `false` for memory-constrained machines.
- Added `scripts/benchmark_research_latency.py` for repeatable admin-only HTTP timing measurements.

## Evidence from live indexed corpus

Query: `Empagliflozin kidney outcomes in type 2 diabetes`, `max_loops=0`, 29,939 indexed abstracts.

- Before these changes: about 32–51 seconds; synthesis spent 6–23 seconds producing prose that citation validation discarded.
- After bounded span selection and reasoning disabled: validated NVIDIA result in about 9.7 seconds warm, then about 7.2 seconds with model retention enabled.
- Warm retained-model trace: query analysis ~0.73 s, retrieval ~1.42 s, judge ~1.61 s, synthesis ~3.41 s, total ~7.20 s.
- A no-result filter (`year_min=2026`) still took about 6.8 seconds because retrieval and the optional judge still run; this is the next clear backend optimization.

## Validation

`python -m pytest -q` passed: **785 passed, 1 skipped**. The suite emitted only expected deprecation/local-Qdrant warnings.

Run live measurements with:

```powershell
.venv\Scripts\python.exe scripts\benchmark_research_latency.py --runs 3
```

Do not commit `.env`, datasets, Qdrant storage, model caches, or generated evaluation artifacts. The local `.env` contains the uncommitted `MEDCPT_KEEP_MODELS_LOADED=true` setting; reproduce it manually only after checking available memory.

## Recommended next work

1. Add an index-manifest year-bound fast path before MedCPT/BM25/LLM work for impossible date filters, with a stale-manifest guard.
2. Add retrieval subchannel timings (query encoding, dense searches, BM25, graph, fusion) to identify the remaining 1–2 second warm retrieval cost.
3. Benchmark `max_loops=2`, concurrent requests, and mobile UI separately after backend changes settle; shared search passes are now serialized for correctness.
4. Review whether the remote NIM selection call is needed for every query; deterministic source-span output is already the safe fallback.
