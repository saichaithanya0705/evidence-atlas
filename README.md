# AI Medical Research Abstract Finder

A local research prototype for searching biomedical abstracts with query understanding, adaptive routing, MedCPT dense embeddings, BM25 lexical retrieval, MeSH concepts, a paper–MeSH graph, and an embedded Qdrant index. It is for literature exploration and demonstration; it is not a clinical decision tool.

## Windows quick start

Requirements: Windows 10 or 11, Python 3.10 or later (Python 3.11 is recommended), Node.js with npm, and enough disk space for Python packages and the three MedCPT model caches. The first online setup downloads model weights and can take a while.

1. From the project root, run `start.bat`.
2. The launcher creates or reuses `.venv`, installs `requirements.txt`, copies `.env.example` to `.env` only if `.env` does not already exist, downloads/verifies the three MedCPT models, prepares the dataset and M1 index artifacts, installs the frontend dependencies, and starts FastAPI and Vite.
3. Open <http://127.0.0.1:5173>. FastAPI health is checked at <http://127.0.0.1:8000/health>.
4. Press Ctrl+C in the launcher window to stop the API and frontend processes. Logs are written to `logs/backend.log` and `logs/frontend.log`.

Setup stages are safe to repeat. Existing `.env` and raw dataset files are preserved. Embeddings are reused only when their corpus hash matches; derived preprocessing/index files are rebuilt as needed. Qdrant uses local embedded storage under `data/qdrant_storage`.

For a deliberate model-offline run, use `start.bat --offline`. This never downloads MedCPT models and uses complete local model caches when available. If required weights are missing, the run is marked `degraded-offline` in `data/manifests/assets_manifest.json` and may use deterministic mock embeddings. That mode is only for software development; results are not MedCPT results. npm may still need registry access to install frontend packages.

## Administrator-only diagnostics

The ordinary researcher view is intentionally limited to the synthesis and bibliographic paper details. Query plans, routing decisions, retrieval scores, evidence spans, provenance, correction-loop traces, and JSON trace export are administrator-only. On first normal startup, `scripts/setup_project.py` generates a strong local `ADMIN_API_KEY` in `.env` without printing it; enter that value through the **Admin access** button when diagnostic review is required. The API independently enforces the same boundary with the `X-Admin-Key` header, so hiding panels in the browser is not the security control. Do not commit `.env` or share the key; replace this shared local key with an identity-aware session/JWT integration before exposing the service to multiple users.

## NVIDIA NIM configuration

The copied `.env` starts with `LLM_MODE=mock`, so an NVIDIA key is not required for local development. To enable NIM-backed generation, edit `.env` and set:

```dotenv
NVIDIA_API_KEY=your-key
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL_NAME=meta/llama-3.3-70b-instruct
LLM_MODE=nim
```

Keep the key in `.env`; do not commit it. `.env` is excluded from Git. The key is sent to NVIDIA only when the application makes an NIM request. Model download and indexing do not require an NVIDIA key. To return to deterministic local demo responses, set `LLM_MODE=mock`.

## Corpus and model setup

`python scripts/setup_assets.py` prepares `data/raw/pubmed_sample.csv`, creates expected directories, verifies and caches `ncbi/MedCPT-Query-Encoder`, `ncbi/MedCPT-Article-Encoder`, and `ncbi/MedCPT-Cross-Encoder`, and writes `data/manifests/assets_manifest.json`. Normal mode fails with a nonzero exit code if a model cannot be downloaded and loaded. Use `--offline` only when intentionally working without model downloads. Do not use `--offline` to claim real MedCPT retrieval quality.

The bundled `data/raw/pubmed_sample.csv` is a small demo/test corpus (30 fixture records). Its abstracts and PMID-like identifiers are not verified against PubMed and must not be treated as authoritative biomedical records. The repository does not define a bulk PubMed download source. To use a real corpus, provide a properly licensed/authorized CSV with at least `pmid`, `title`, and `abstract` columns, plus available metadata such as authors, publication date/year, MeSH terms, keywords, and publication type. The setup script preserves an existing CSV; `--force` replaces it with the bundled demo fixture, so do not use that flag when maintaining a real corpus.

Run M1 indexing manually, if needed, from the project root:

```powershell
python scripts/setup_assets.py
python pipelines/inspect_dataset.py
python pipelines/preprocess.py
python pipelines/build_embeddings.py
python pipelines/build_bm25.py
python pipelines/build_mesh_dict.py
python pipelines/build_mesh_graph.py
python pipelines/index_qdrant.py
```

The normal launcher runs these steps in order. `data/manifests/` contains the asset, dataset, preprocessing, graph, and index manifests. If the corpus changes, preprocessing and downstream artifacts must be rebuilt; the embedding builder checks the cleaned corpus hash before reusing its cache.

## Evaluation

Run the reproducible classical IR and router benchmark after the setup has built `data/processed/bm25_index.pkl`:

```powershell
python -m evaluation.run_evaluation --top-k 10 --output data/evaluation/latest.json
```

The frozen query set and relevance labels are in `data/evaluation/queries.json`. The report includes Recall@K, Precision@K, MRR@K, nDCG@K, and labeled router accuracy. The labels refer only to the bundled demo corpus; they do not establish real-world PubMed performance or medical correctness.

For deterministic checks on saved `/research` response objects, pass a JSON list with this shape:

```json
[
  {
    "query": "example",
    "synthesis": "A research summary [PMID: 12345].",
    "cited_pmids": ["12345"],
    "retrieved_papers": [{"pmid": "12345", "abstract": "Exact source abstract text."}],
    "evidence_table": [{"pmid": "12345", "supporting_text_spans": ["Exact source abstract text."]}]
  }
]
```

```powershell
python -m evaluation.run_evaluation --answers path\to\answers.json --output data/evaluation/latest.json
```

Citation checks measure whether each cited PMID appears in the retrieved evidence and whether its quoted span is an exact substring of that PMID's abstract. They do not judge whether the quote semantically supports the claim; human review remains necessary. Without `--answers`, the citation section is reported as `not_run`.

## Development commands

```powershell
# Run the API only (from the project root with .venv active)
python -m uvicorn backend.app.main:app --reload

# Run the Vite UI only (from frontend/)
npm install
npm run dev

# Run project tests
python -m pytest
```

The application uses local files and embedded Qdrant storage. No Docker service or container is required.
