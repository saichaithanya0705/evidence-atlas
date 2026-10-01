# AI Medical Research Abstract Finder

A local research prototype for searching biomedical abstracts with query understanding, adaptive routing, MedCPT dense embeddings, BM25 lexical retrieval, MeSH concepts, a paper–MeSH graph, and an embedded Qdrant index. It is for literature exploration and demonstration; it is not a clinical decision tool.

## Windows quick start

Requirements: Windows 10 or 11, Python 3.10 or later (Python 3.11 is recommended), Node.js 20.19+ or 22.12+ with npm, and enough disk space for Python packages and the three MedCPT model caches. The first online setup downloads model weights and can take a while.

1. From the project root, run `start.bat`.
2. The launcher creates or reuses `.venv`, installs `requirements.txt`, copies `.env.example` to `.env` only if `.env` does not already exist, downloads/verifies the three MedCPT models, prepares the dataset and index artifacts, installs frontend dependencies, prompts for the first administrator account if needed, and starts FastAPI and Vite.
3. Open <http://127.0.0.1:5173>. FastAPI health is checked at <http://127.0.0.1:8000/health>.
4. Press Ctrl+C in the launcher window to stop the API and frontend processes. Logs are written to `logs/backend.log` and `logs/frontend.log`.

Setup stages are safe to repeat. Existing `.env` and raw dataset files are preserved. A complete index with a matching processed-corpus hash is reused on normal startup; changed corpus files trigger rebuilding. `--ingest` always reindexes. Qdrant uses local embedded storage under `data/qdrant_storage`.

To acquire original PubMed records from the root `PubMed_Phrases.tar.gz` before rebuilding, run `start.bat --ingest`. A normal `start.bat` deliberately reuses the existing dataset and does not redownload it. The archive supplies phrase-to-PMID mappings; `--ingest` then fetches canonical XML records from the official NCBI E-utilities API and writes the normalized CSV before indexing it. `PUBMED_INGEST_LIMIT` controls the requested upper bound (default `100000`; the archive can contain fewer unique PMIDs), for example `set PUBMED_INGEST_LIMIT=1000` followed by `start.bat --ingest` for a shorter CPU-only build. This online option cannot be combined with `--offline`.

For a deliberate model-offline run, use `start.bat --offline`. This never downloads MedCPT models and uses complete local model caches when available. If required weights are missing, the run is marked `degraded-offline` in `data/manifests/assets_manifest.json` and may use deterministic mock embeddings. That mode is only for software development; results are not MedCPT results. npm may still need registry access to install frontend packages.

## Accounts and administrator workspace

There is no public registration. On first interactive startup, the launcher prompts you to create the `administrator` account with a hidden password. You can also run `.venv\Scripts\python.exe scripts\manage_accounts.py bootstrap-admin --username administrator` before startup. Bootstrap works only while the account database is empty. The SQLite account and audit database lives at `data/app/evidence_atlas.sqlite3` by default and is excluded from Git; back it up if you need to preserve accounts and query history.

If an account holder loses a password, an administrator can set a temporary replacement on the **Accounts** page. For local recovery when no administrator can sign in, run `.venv\Scripts\python.exe scripts\manage_accounts.py reset-password --username administrator` on the machine that owns the SQLite database. The password is prompted privately, existing sessions are revoked, and the account must choose a new password at next sign-in.

Sign in at <http://127.0.0.1:5173/login>. Administrators can create user or additional administrator accounts on the **Accounts** page, issuing a temporary password that must be changed on first sign-in. Users see a focused research workspace without advanced filters. Administrators get advanced filters in **Research**, durable per-account **Audit logs** with query traces and evidence snapshots, and a separate **Observability** page. The API enforces the same role boundary; the old `ADMIN_API_KEY` and `X-Admin-Key` mechanism is retired and ignored. Sessions use HttpOnly cookies, and state-changing requests require a same-origin CSRF token.

## NVIDIA NIM configuration

The copied `.env` starts with `LLM_MODE=mock`, so an NVIDIA key is not required for local development. To enable NIM-backed generation, edit `.env` and set:

```dotenv
NVIDIA_API_KEY=your-key
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
LLM_MODE=nim
```

Keep the key in `.env`; do not commit it. `.env` is excluded from Git. The key is sent to NVIDIA only when the application makes an NIM request. Model download and indexing do not require an NVIDIA key. To return to deterministic local demo responses, set `LLM_MODE=mock`.

The NIM path uses a bounded, non-reasoning model call to select exact supporting spans; the server validates the returned PMID/span indices and renders cited text from the stored evidence. Invalid selections or provider failures fall back to deterministic source spans. `LLM_SYNTHESIS_MAX_TOKENS` bounds the selection call (default 300); an empty evidence set never calls NIM.

## Conversational biomedical research

The conversation agent resolves a follow-up from bounded conversation history, then sends every initial or corrective research query through the query enhancer, guarded router, and research workflow. Agent complexity is advisory: the executed route is the highest of the deterministic rule route, a valid agent hint, and any carried route floor. The biomedical source corpus, indexes, and Qdrant collection are never changed by conversation turns.

Answers use four statuses. `SUPPORTED` means the full answer passed deterministic source and claim checks. `LIMITED` means some requested parts were not established; it contains only independently supported claims, with the remaining gaps stated separately. `INSUFFICIENT` means no releasable supported claim was found and the answer explains the gap or asks a clarification. `FAILED` means a technical error prevented completion. A model judgment can request more research or downgrade a result; it cannot promote insufficient evidence, bypass filters, expand the configured loop budget, or invent a source. Every released biomedical claim must map to retrieved evidence with an exact supporting abstract span.

Bounds are controlled by `CONVERSATION_HISTORY_TURN_LIMIT` (default 12 recent entries), `CONVERSATION_MESSAGE_MAX_CHARS` (4000), `CONVERSATION_TITLE_MAX_CHARS` (80), `AGENT_OUTPUT_MAX_TOKENS` (800), `LLM_TIMEOUT_SECONDS` (30 seconds per provider request), and `MAX_CORRECTIVE_LOOPS` (2). A conversation allows one running turn; a concurrent duplicate receives HTTP 409. Conversations and linked administrator audit summaries are stored in the application SQLite database until that database is deliberately archived or removed. The agent sees only the configured recent history window and a bounded deterministic summary of older turns. Audit records retain bounded structured summaries and exclude prompts, raw model output, and private reasoning.

The interface summarizes biomedical literature for research exploration; it does not provide medical advice or clinical decisions. `LLM_MODE=mock` uses deterministic fallback behavior and is suitable for offline UI and software checks only. It does not represent live planner or semantic-grading intelligence. Only `LLM_MODE=nim` with a valid `NVIDIA_API_KEY` exercises configured live NVIDIA NIM planning and semantic grading. Never release claims from model memory: a claim must have a retrieved PMID and exact supporting span.

Run the deterministic conversation backend and frontend checks with:

```powershell
python -m pytest tests/adversarial/test_conversational_research_guardrails.py tests/unit/test_conversational_research_evaluation.py -q
cd frontend
npm run test:ui-conversations
npm run test:ui-preview
npm run test:ui-accounts
npm run build
```

The fixture evaluator reads a JSON object, not the live corpus, and reports deterministic route accuracy, correction count, answer and abstention distribution, unsupported-claim rate, citation validity, attribution, latency, and model-call count. Optional LLM-as-judge or RAGAS-style signals are secondary evidence only:

```powershell
python scripts/evaluate_conversational_research.py path\to\fixture-report.json
```

Live NIM and real-index checks are separate from deterministic CI and require configured credentials and exclusive local index access. See `TEST_READY.md` and `frontend/tests/README.md` for their commands and prerequisites.

## Backend latency measurements

While the API is running, run `python scripts/benchmark_research_latency.py --runs 3` from the project root. It reports HTTP wall time, admin-only workflow stages, each retrieval pass, and synthesis time without printing the administrator key or answer. The first run includes model/index loading; later runs reflect warm-request latency. `--max-loops 2` exercises corrective retrieval, and `--year-min 2026` can measure a no-result filter against an older corpus.

The default `MEDCPT_KEEP_MODELS_LOADED=false` releases the large query and cross-encoder weights between retrieval passes for memory-constrained machines. Set it to `true` in local `.env` when sufficient GPU/RAM is available; this avoids repeated loading and release costs. Search passes are serialized within the backend process because the retriever and reranker share mutable model and trace state.

## Corpus and model setup

`python scripts/setup_assets.py` validates/preserves `data/raw/pubmed_sample.csv`, creates expected directories, verifies and caches `ncbi/MedCPT-Query-Encoder`, `ncbi/MedCPT-Article-Encoder`, and `ncbi/MedCPT-Cross-Encoder`, and writes `data/manifests/assets_manifest.json`. Normal mode fails with a nonzero exit code if a model cannot be downloaded and loaded. Use `--offline` only when intentionally working without model downloads. Do not use `--offline` to claim real MedCPT retrieval quality.

The recorded corpus used for the published evaluation contains 29,994 PubMed records. A reused local corpus can differ; its verified local manifests and actual index determine its size. The downloaded abstracts and generated indexes are intentionally not committed to Git; a fresh checkout must run `start.bat --ingest` with `PubMed_Phrases.tar.gz` present to acquire and index the selected corpus. `data/manifests/pubmed_ingestion_manifest.json`, `preprocessing_manifest.json`, and `index_manifest.json` record the verified source, transformations, hashes, and exact point count. Check their identities against local artifacts after pulling manifests from another machine. Any small repository fixture must not be treated as biomedical evidence. The full official PubMed baseline linked in the implementation plan is tens of millions of citations, so this workstation-oriented corpus remains below the plan's preferred 100k-250k controlled subset. NLM remains the source of record, abstracts may be copyrighted, and this project does not imply NLM/NIH/HHS endorsement.

Run M1 indexing manually, if needed, from the project root:

```powershell
python scripts/setup_assets.py
python pipelines/inspect_dataset.py
python pipelines/preprocess.py
python pipelines/build_embeddings.py --resume --checkpoint-every 10
python pipelines/build_bm25.py
python pipelines/build_mesh_dict.py
python pipelines/build_mesh_graph.py
python pipelines/index_qdrant.py
```

The normal launcher runs these steps in order. `data/manifests/` contains the asset, dataset, preprocessing, graph, and index manifests. If the corpus changes, preprocessing and downstream artifacts must be rebuilt; the embedding builder checks the cleaned corpus hash before reusing its cache.

## Evaluation

The frozen 40-query benchmark is `data/evaluation/benchmark_v2.json`. Its labels use web-assisted PubMed source verification: PMID, title, abstract evidence, and local corpus identity were checked against official PubMed records. This is a small query-focused benchmark, not a representative PubMed sample or a clinical validation study. The published run used 29,994 records; fresh evaluations bind their artifacts to the actual local corpus checksum and should state any difference from that recorded build.

From the repository root, run all four comparable variants and promote the complete checksum-bound report:

```powershell
.\.venv\Scripts\python.exe -m evaluation.ablation --benchmark data/evaluation/benchmark_v2.json --variant all --resume --output-dir data/evaluation/variants
.\.venv\Scripts\python.exe -m evaluation.run_evaluation --benchmark data/evaluation/benchmark_v2.json --variants dense_only hybrid reranked agentic --output-dir evaluation/reports
```

The report includes Recall@10, Precision@10, MRR@10, nDCG@10, filter accuracy, latency, available citation checks, robustness deltas, and failure categories. The dense-only, hybrid, and reranked variants are retrieval-only, so their null answers and answer metrics marked `not_run` are expected and are not product failures. Each metric has an explicit `completed`, `not_run`, or `failed` status; unavailable values remain null with a reason. Reports and metrics are visible only to administrators through the **Evaluations** dashboard and `/admin/evaluations` API. Ordinary-user research views do not expose them. See [the measured report](docs/evaluation_report.md), [evaluation plan](docs/evaluation_plan.md), and [administrator demo](docs/demo_script.md) for the run ID, checksums, limitations, and repeatable walkthrough.

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

The recorded 29,994-point collection is larger than Qdrant's recommended embedded-local threshold of 20,000 points. It is correct and usable for this no-Docker workstation setup, but concurrent searches are slower and local payload indexes are not accelerated; a Qdrant server or managed Qdrant deployment is the appropriate production scaling path.

## UI stress validation

With the API and Vite UI running, execute `npm run test:ui-stress` from `frontend/`. The test uses fresh ordinary-user browser contexts, exercises sequential, 2-user, 5-user, 10-user, and 390-pixel mobile flows, and fails if administrator-only analysis, traces, provenance, evidence spans, or retrieval diagnostics appear. The latest consolidated result is `data/evaluation/ui-stress/final-report.json`.
