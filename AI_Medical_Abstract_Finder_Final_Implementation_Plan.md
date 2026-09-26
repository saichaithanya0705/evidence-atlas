**AI-POWERED MEDICAL RESEARCH  
ABSTRACT FINDER**

**Final Technical Implementation Plan**

*Adaptive Agentic Evidence RAG for PubMed / MEDLINE research retrieval and synthesis*

| Core design goal: build a research assistant that does not merely retrieve abstracts. It should understand biomedical intent, adapt its search strategy to query complexity, iteratively repair weak retrieval, extract structured evidence, compare studies, and validate citations before returning a grounded research summary. |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

**Final architecture**

Biomedical Query Understanding + Adaptive RAG + Agentic Multi-Step Retrieval + Hybrid MedCPT/BM25 + MeSH/Graph Retrieval + CRAG Evidence Correction + Structured Evidence Synthesis + Citation Validation

Prepared as the working blueprint for implementation, evaluation, documentation, and the final 10-minute panel demonstration.

# 1. Executive Summary

The system will ingest PubMed/MEDLINE abstracts and metadata, create a biomedical search knowledge base, and expose an application where a researcher can ask a natural-language question. The system will decide how much retrieval work the question needs, search using multiple biomedical retrieval signals, correct weak evidence, extract study-level facts, synthesize findings across papers, and return traceable PMID-based citations.

| Important scope decision: the project is an evidence-finding and literature-synthesis tool, not a clinical decision system. Every answer must be framed as research evidence and must not silently convert an abstract-level result into medical advice. |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 2. Final System Architecture

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>OFFLINE / INDEXING PIPELINE<br />
PubMed CSV<br />
-&gt; schema validation + cleaning<br />
-&gt; metadata normalization + MeSH processing<br />
-&gt; MedCPT document embeddings<br />
-&gt; BM25 / sparse index<br />
-&gt; paper-MeSH graph<br />
-&gt; Qdrant knowledge base + metadata store<br />
<br />
ONLINE / QUERY PIPELINE<br />
User Query<br />
-&gt; Biomedical Query Understanding &amp; Enhancement<br />
-&gt; Medical Query Analyzer (PICO / concepts / filters)<br />
-&gt; Adaptive Router: SIMPLE | MODERATE | COMPLEX<br />
-&gt; Route-specific query expansion / research planning<br />
-&gt; Hybrid Retrieval: original dense + enhanced dense + BM25 + filters + optional graph<br />
-&gt; Reciprocal Rank Fusion<br />
-&gt; MedCPT cross-encoder reranking<br />
-&gt; Evidence Quality Judge (CRAG-style)<br />
-&gt; insufficient: rewrite / decompose / retrieve again<br />
-&gt; sufficient: continue<br />
-&gt; Structured Evidence Extraction<br />
-&gt; Study Comparison / Contradiction &amp; Gap Analysis<br />
-&gt; Evidence-Grounded Synthesis<br />
-&gt; Deterministic Citation Validator + claim support check<br />
-&gt; Final answer + evidence table + PMID citations</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

| **Decision**               | **Choice**                                                                             | **Why this choice**                                                                                                                                                                                                                                                                                                                                                              |
|----------------------------|----------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Orchestration              | LangGraph state machine                                                                | The flow contains conditional routing, iterative retrieval loops, validation and retries. Explicit state transitions are easier to debug and demonstrate than an unconstrained multi-agent chat.                                                                                                                                                                                 |
| Vector / hybrid store      | Qdrant                                                                                 | Stores dense vectors, sparse signals and metadata payloads in one retrieval service, reducing operational complexity while supporting filtered hybrid search.                                                                                                                                                                                                                    |
| Biomedical dense retrieval | MedCPT query encoder + article encoder                                                 | MedCPT was trained for biomedical information retrieval using large-scale PubMed search interactions, so it is more domain-aligned than a generic embedding model.                                                                                                                                                                                                               |
| Reranking                  | MedCPT cross-encoder                                                                   | A cross-encoder can judge a query and candidate abstract jointly, improving precision after the faster first-stage retrieval.                                                                                                                                                                                                                                                    |
| Lexical retrieval          | BM25 / sparse retrieval                                                                | Exact drug names, acronyms, gene names and rare biomedical terms can be missed by dense retrieval; lexical matching preserves those high-value exact matches.                                                                                                                                                                                                                    |
| Controlled vocabulary      | MeSH-aware expansion                                                                   | MeSH reduces ambiguity and maps lay or abbreviated wording to standardized biomedical concepts without relying only on free-form LLM rewriting.                                                                                                                                                                                                                                  |
| Graph retrieval            | Paper-MeSH concept graph, enabled mainly for moderate/complex queries                  | Graph neighbors can surface conceptually connected papers and relationships that may not be close in vector space; using it selectively prevents unnecessary latency.                                                                                                                                                                                                            |
| Generation                 | Provider-agnostic LLM adapter with structured outputs                                  | The project can switch between NIM, OpenAI-compatible APIs, Gemini or a local model without rewriting the retrieval architecture.                                                                                                                                                                                                                                                |
| Frontend                   | React + Vite                                                                           | Provides a component-based, production-style web UI for search, filters, evidence tables, abstract inspection and research summaries, while keeping the frontend cleanly separated from the FastAPI backend. It also supports dedicated auditability and explainability views such as query interpretation, retrieval provenance, claim-to-evidence mapping and research traces. |
| API                        | FastAPI                                                                                | Separates the retrieval/reasoning microservice from the UI and provides typed endpoints, validation and easy deployment.                                                                                                                                                                                                                                                         |
| Evaluation stack           | Classical IR metrics + RAGAS + RAGChecker-style diagnostics + medical robustness tests | Classical metrics quantify ranking quality, RAGAS evaluates retrieval context and generation quality, fine-grained diagnostics localize failures across retriever/generator modules, and medical robustness tests check behavior under noisy, incomplete or conflicting evidence.                                                                                                |

# 3. Design Principles

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                              | **Output**                      |
|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------|
| P1       | Preserve the original user query alongside every enhanced or decomposed version. **Why:** biomedical query rewriting can drift semantically; keeping the original as a retrieval signal protects recall and makes the transformation auditable. | Original + enhanced query state |
| P2       | Use the cheapest adequate retrieval strategy for each query. **Why:** simple searches do not need expensive agent loops, while complex comparative questions do.                                                                                | Adaptive latency/cost           |
| P3       | Separate retrieval, evidence extraction and synthesis. **Why:** forcing one LLM prompt to do all three makes errors difficult to diagnose and weakens grounding.                                                                                | Modular pipeline                |
| P4       | Treat retrieved abstracts as evidence, not truth. **Why:** abstracts can be incomplete, observational, contradictory or outdated; the answer must expose study type and limitations.                                                            | Safer summaries                 |
| P5       | Allow abstention and “insufficient evidence”. **Why:** medical research search should not invent a conclusion when the retrieved corpus does not support one.                                                                                   | Controlled failure mode         |
| P6       | Validate citations deterministically before returning the response. **Why:** a fluent answer with an invented PMID is a critical failure even if the prose sounds plausible.                                                                    | Citation integrity              |
| P7       | Measure each advanced component against a simpler baseline. **Why:** the final presentation should show that agentic complexity provides measurable retrieval or grounding gains.                                                               | Defensible architecture         |

# 4. Phase 0 - Scope, Corpus and Baseline Definition

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                                                          | **Output**           |
|----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------|
| 0.1      | Define the initial corpus size from the supplied CSV, preferably a controlled 100k-250k abstract subset if the source is extremely large. **Why:** this is enough to demonstrate realistic retrieval while avoiding full-PubMed infrastructure work before the retrieval quality is proven. | Corpus scope         |
| 0.2      | Freeze the core searchable fields: PMID, title, abstract, authors, publication date/year, MeSH terms, keywords and any available publication/study type. **Why:** retrieval, filters, UI and evaluation all depend on one canonical schema.                                                 | Canonical schema     |
| 0.3      | Define 30-50 representative evaluation queries before implementation. **Why:** predefining queries prevents tuning the system only to examples that already work and gives us an objective benchmark throughout development.                                                                | Evaluation query set |
| 0.4      | Implement a minimal dense-only baseline before advanced components. **Why:** every later improvement needs a comparison point for Recall@K, MRR, nDCG, citation quality and latency.                                                                                                        | Baseline metrics     |

# 5. Phase 1 - Medical Research Data Preparation and Knowledge Base

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                        | **Output**                   |
|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------|
| 1.1      | Load the CSV with explicit dtypes and schema checks; report missing columns, malformed dates and empty text fields. **Why:** silent schema errors create bad embeddings and misleading filter behavior.                                   | Data quality report          |
| 1.2      | Remove duplicate PMIDs and exact duplicate title/abstract records. **Why:** duplicates can dominate top-k results and falsely inflate retrieval relevance.                                                                                | Deduplicated corpus          |
| 1.3      | Drop records with no usable title and no abstract, while retaining title-only records only if the project explicitly needs them. **Why:** vectors built from empty evidence provide little value and waste index space.                   | Usable records               |
| 1.4      | Normalize Unicode, whitespace and obvious encoding artifacts without aggressively rewriting biomedical text. **Why:** cleaning should improve index consistency without altering scientific terminology.                                  | Clean text                   |
| 1.5      | Parse publication dates into normalized date/year fields and preserve the original date string. **Why:** year filters require consistent numeric values while the original metadata remains useful for display and audit.                 | Normalized dates             |
| 1.6      | Normalize MeSH terms into arrays and build a local MeSH lookup dictionary from the dataset or NLM descriptors. **Why:** standardized concepts enable controlled query expansion and graph construction.                                   | MeSH dictionary              |
| 1.7      | Normalize keyword fields into arrays while preserving original capitalization for display. **Why:** keywords contribute lexical retrieval signals but should remain human-readable in results.                                            | Keyword arrays               |
| 1.8      | Create the document text used by the article encoder from title + abstract, preserving both fields separately in metadata. **Why:** the title is highly discriminative while the abstract carries the study evidence.                     | Embedding text               |
| 1.9      | Generate MedCPT document/article embeddings in batches and cache them to disk before final indexing. **Why:** embedding generation is one of the expensive preprocessing steps and should not be repeated when only the index is rebuilt. | Embedding matrix/cache       |
| 1.10     | Create sparse/BM25 representations for title, abstract, MeSH and keywords. **Why:** lexical retrieval complements dense semantics for rare entities, drug names and exact terminology.                                                    | Sparse index                 |
| 1.11     | Create a Qdrant collection containing dense vector, sparse vector and metadata payload. **Why:** one store can serve hybrid retrieval and metadata filtering with less synchronization overhead.                                          | Searchable Qdrant collection |
| 1.12     | Build a lightweight paper-MeSH graph using NetworkX initially; move to Neo4j only if scale or graph queries justify it. **Why:** the graph adds concept-neighbor retrieval without introducing a second heavyweight database prematurely. | Concept graph                |
| 1.13     | Persist preprocessing statistics, model versions, embedding dimension and index build time. **Why:** reproducibility is part of the documentation and makes later evaluation trustworthy.                                                 | Index manifest               |

# 6. Phase 2 - Biomedical Query Understanding and Enhancement

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                                       | **Output**           |
|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------|
| 2.1      | Accept the original natural-language research query unchanged into state. **Why:** the original wording is the source of truth and acts as a safeguard against later query drift.                                                                                        | original_query       |
| 2.2      | Run lightweight spelling and whitespace normalization only when confidence is high. **Why:** obvious noise should not reduce retrieval, but biomedical spelling must not be “corrected” into a different medical concept.                                                | clean_query          |
| 2.3      | Expand common biomedical abbreviations such as T2DM or COPD using a curated dictionary. **Why:** acronyms are common in research queries and full forms improve both dense and lexical recall.                                                                           | abbreviation map     |
| 2.4      | Extract candidate medical entities and map them to controlled MeSH terms where possible. **Why:** controlled vocabulary reduces synonym ambiguity and supports filters/graph retrieval.                                                                                  | mesh_candidates      |
| 2.5      | Generate a conservative canonical query with a small structured-output LLM, while preserving the original. **Why:** researchers may use colloquial or compressed phrasing; a normalized formulation helps downstream analysis but must never replace the source query.   | canonical_query      |
| 2.6      | Extract high-confidence synonym expansions from the MeSH dictionary and curated terminology; treat free-form LLM synonyms as optional candidates requiring validation. **Why:** unrestricted synonym generation can broaden the query into medically different concepts. | validated expansions |
| 2.7      | Detect simple filters such as “after 2020”, “recent”, “randomized trial” or “meta-analysis”. **Why:** these constraints should become structured metadata filters rather than being left only inside semantic embeddings.                                                | initial filters      |
| 2.8      | Create both original-query and canonical-query dense embeddings. **Why:** dual retrieval preserves the user’s exact intent while benefiting from normalized biomedical language.                                                                                         | dual query vectors   |

# 7. Phase 3 - Medical Query Analyzer

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                               | **Output**                |
|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| 3.1      | Extract Population, Intervention, Comparator and Outcome when the query is compatible with PICO. **Why:** PICO provides a useful clinical-research structure for comparative and treatment questions.                                            | PICO fields               |
| 3.2      | For non-PICO questions, extract disease/topic, exposure, treatment, population, outcome, relationship, publication window and study type. **Why:** not every literature question is an intervention question, so forcing PICO would lose intent. | General research concepts |
| 3.3      | Classify intent such as discovery, comparison, effectiveness, safety, association, mechanism or evidence summary. **Why:** intent determines which retrieval and synthesis strategy should be used.                                              | intent label              |
| 3.4      | Assign must-have concepts, high-priority concepts, optional expansions and hard filters. **Why:** this lets the retriever distinguish mandatory medical meaning from helpful semantic expansion.                                                 | weighted concept plan     |
| 3.5      | Produce a compact structured QueryPlan JSON and log it with the request. **Why:** every later decision should be traceable to an explicit machine-readable interpretation of the question.                                                       | QueryPlan                 |

# 8. Phase 4 - Adaptive Query Complexity Router

| **Step** | **Technical step + why we use it**                                                                                                                                                                                 | **Output**    |
|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| 4.1      | Classify each QueryPlan as SIMPLE, MODERATE or COMPLEX using rules first and a small LLM/classifier for ambiguous cases. **Why:** routing avoids running expensive agentic reasoning for straightforward searches. | route label   |
| 4.2      | Route SIMPLE queries to one enhanced hybrid retrieval pass. **Why:** queries such as “papers on diabetic retinopathy after 2022” are well served by strong retrieval plus filters.                                 | Simple path   |
| 4.3      | Route MODERATE queries to multi-query expansion followed by merged retrieval. **Why:** synonym-heavy or multi-concept questions benefit from several search formulations without needing a full planning loop.     | Moderate path |
| 4.4      | Route COMPLEX questions to the research planner and iterative agent loop. **Why:** comparison, contradiction, multi-population or multi-treatment questions require decomposition and evidence coverage checks.    | Complex path  |
| 4.5      | Store router confidence and routing reason. **Why:** router errors can otherwise look like retrieval failures during evaluation.                                                                                   | Router trace  |

# 9. Phase 5 - Route-Specific Query Expansion and Research Planning

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                               | **Output**              |
|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------|
| 5.1      | For SIMPLE queries, use the original + canonical query and validated MeSH/synonym expansion only. **Why:** unnecessary decomposition would increase latency and can reduce precision.                                                                            | 1 search bundle         |
| 5.2      | For MODERATE queries, create 2-4 complementary subqueries that vary synonyms, study type terms and outcome wording. **Why:** multiple formulations improve recall when relevant papers use different biomedical terminology.                                     | Multi-query bundle      |
| 5.3      | For COMPLEX queries, create a research plan with explicit subquestions such as treatment A evidence, treatment B evidence and direct comparison evidence. **Why:** decomposing the information need makes coverage measurable and supports structured synthesis. | Research plan DAG/state |
| 5.4      | Add a query budget such as maximum subqueries and maximum retrieval loops. **Why:** agentic search must have a deterministic stopping condition to control cost and prevent looping.                                                                             | Search budget           |
| 5.5      | Deduplicate near-identical generated subqueries before retrieval. **Why:** duplicate searches waste tokens and can over-weight the same evidence during fusion.                                                                                                  | Unique subqueries       |

# 10. Phase 6 - Hybrid Biomedical Retrieval

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                      | **Output**              |
|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------|
| 6.1      | Search dense vectors with the MedCPT query encoder using the original query. **Why:** this directly captures the user’s semantic intent using a biomedical retrieval model.                                                             | Dense candidates A      |
| 6.2      | Search dense vectors using the canonical/enhanced query. **Why:** normalized terminology can recover papers that use standard biomedical language absent from the user’s wording.                                                       | Dense candidates B      |
| 6.3      | Run BM25/sparse retrieval over title, abstract, MeSH and keywords. **Why:** exact terms, acronyms and rare entities can rank poorly in embedding space but are highly informative lexically.                                            | Sparse candidates       |
| 6.4      | Apply hard metadata filters such as publication year and study/publication type at retrieval time where supported. **Why:** filtering before reranking prevents irrelevant candidates from consuming the reranking budget.              | Filtered candidates     |
| 6.5      | For moderate/complex routes, query the paper-MeSH graph from matched concepts and collect nearby papers/concepts. **Why:** graph expansion adds relation-based recall beyond text similarity.                                           | Graph candidates        |
| 6.6      | Fuse candidate rankings with Reciprocal Rank Fusion rather than directly comparing incompatible raw scores. **Why:** BM25, dense and graph scores have different scales; RRF combines rank evidence robustly without score calibration. | Fused candidate list    |
| 6.7      | Deduplicate by PMID and retain retrieval provenance for every candidate. **Why:** the system should know whether a paper was found by dense, lexical, graph or several channels for debugging and explainability.                       | Unique fused candidates |
| 6.8      | Take approximately the top 30-50 fused candidates into MedCPT cross-encoder reranking. **Why:** cross-encoders are more accurate but too expensive to apply across the entire corpus.                                                   | Reranked list           |
| 6.9      | Keep approximately the top 8-15 abstracts as the candidate evidence set, configurable by query complexity. **Why:** enough evidence is needed for comparison while excessive context increases cost and distracts the synthesizer.      | Candidate evidence set  |

# 11. Phase 7 - Evidence Quality Judge and Corrective Retrieval Loop

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                         | **Output**                 |
|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------|
| 7.1      | Compute deterministic evidence signals: top reranker scores, concept coverage, filter compliance, unique study count and result diversity. **Why:** evidence quality should not depend entirely on another generative model.                               | Objective evidence signals |
| 7.2      | Use an LLM evidence grader to judge relevance, subquestion coverage and whether the evidence is sufficient to answer the research question. **Why:** semantic coverage across several studies is difficult to represent with one numeric similarity score. | Evidence grade             |
| 7.3      | Combine deterministic and LLM signals into SUFFICIENT, PARTIAL or INSUFFICIENT. **Why:** a discrete state simplifies LangGraph routing and gives clear retry behavior.                                                                                     | Evidence status            |
| 7.4      | If PARTIAL, identify missing concepts/subquestions and generate targeted corrective queries. **Why:** corrective retrieval should search for the missing evidence rather than blindly repeating the original query.                                        | Targeted query rewrite     |
| 7.5      | If INSUFFICIENT, broaden terminology, relax only nonessential constraints or decompose the question further within the search budget. **Why:** retrieval failure may come from overly narrow wording or an under-decomposed question.                      | Recovery search            |
| 7.6      | If repeated retrieval still fails, return an insufficient-evidence response with the studies that were found. **Why:** abstention is preferable to inventing a medical research conclusion.                                                                | Graceful abstention        |

# 12. Phase 8 - Structured Evidence Extraction

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                                                                                                | **Output**              |
|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------|
| 8.1      | Extract a structured EvidenceRecord from each selected abstract with PMID, title, year, study type, population, intervention/exposure, comparator, outcomes, key finding and limitations where explicitly available. **Why:** structured evidence makes cross-study comparison more reliable than reasoning over raw prose alone. | EvidenceRecord JSON     |
| 8.2      | Use null/unknown for information not present in the abstract rather than inferring it. **Why:** abstract-level evidence often omits sample size, design details or limitations; fabricated completeness is unsafe.                                                                                                                | Faithful missing values |
| 8.3      | Attach the source PMID and exact supporting abstract sentences/spans to extracted claims. **Why:** claim-level provenance allows later validation and UI evidence highlighting.                                                                                                                                                   | Evidence spans          |
| 8.4      | Normalize study-type labels where possible while retaining the original publication type. **Why:** comparison logic benefits from consistent categories, but source metadata should remain auditable.                                                                                                                             | Normalized study design |
| 8.5      | Create an Evidence Table ordered by reranker relevance and evidence strength rather than publication year alone. **Why:** researchers need a concise, interpretable intermediate representation before synthesis.                                                                                                                 | Evidence table          |

# 13. Phase 9 - Multi-Study Analysis and Research Synthesis

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                            | **Output**            |
|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------|
| 9.1      | Group EvidenceRecords by treatment/exposure, population, outcome or subquestion from the research plan. **Why:** grouped evidence prevents the LLM from blending results from medically different contexts.                                   | Evidence groups       |
| 9.2      | Identify agreements, disagreements and evidence gaps across studies. **Why:** research synthesis should expose conflicting findings rather than averaging them into a false consensus.                                                        | Consistency analysis  |
| 9.3      | Compare study designs and publication dates when interpreting conflicting evidence. **Why:** an RCT, observational cohort and review do not provide equivalent evidence and older evidence may be superseded.                                 | Contextual comparison |
| 9.4      | Generate a concise research-oriented synthesis using only the EvidenceRecords and permitted metadata. **Why:** isolating the final generator from the wider world/model memory reduces unsupported medical claims.                            | Draft synthesis       |
| 9.5      | Require PMID citations beside factual study claims and create a separate “Evidence gaps / limitations” section. **Why:** readers should be able to inspect the source of a claim and understand what the corpus cannot establish.             | Cited answer          |
| 9.6      | Avoid clinical recommendations unless the query explicitly asks to summarize recommendations from cited literature, and label them as reported evidence. **Why:** the project is a literature assistant, not a physician or guideline engine. | Research-safe wording |

# 14. Phase 10 - Citation and Evidence Validation

| **Step** | **Technical step + why we use it**                                                                                                                                                                              | **Output**             |
|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------|
| 10.1     | Parse every PMID cited in the generated response and verify that it exists in the final EvidencePack. **Why:** this prevents fabricated or accidentally copied citations.                                       | PMID validity check    |
| 10.2     | Reject citations that were retrieved but not actually used as evidence for the corresponding claim. **Why:** citation presence alone does not guarantee attribution correctness.                                | Attribution check      |
| 10.3     | Run a claim-support pass that maps each factual sentence to one or more evidence spans. **Why:** a response can cite a real paper while stating something the abstract does not support.                        | Claim support map      |
| 10.4     | If unsupported claims exist, regenerate only the affected section using the validated evidence rather than rerunning the whole pipeline. **Why:** targeted repair lowers cost and preserves already-valid work. | Corrected response     |
| 10.5     | Fail closed if citation validation still fails after the configured retry limit. **Why:** returning a shorter, fully grounded answer is better than a richer answer containing unsupported medical claims.      | Validated final answer |

# 15. Phase 11 - FastAPI Microservice

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                                                                                                                                                                                          | **Output**               |
|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------|
| 11.1     | Create /search for retrieval-only results with query, filters, top_k and route controls. **Why:** retrieval should be testable independently from generation.                                                                                                                                                                                                                                                               | Search endpoint          |
| 11.2     | Create /analyze-query to expose query enhancement, extracted concepts, filters and route. **Why:** visible query interpretation makes debugging and the panel demo much stronger.                                                                                                                                                                                                                                           | Query analysis endpoint  |
| 11.3     | Create /research as the main end-to-end agentic endpoint. **Why:** clients need one API call that returns summary, studies, evidence table, citations and trace metadata.                                                                                                                                                                                                                                                   | Main research endpoint   |
| 11.4     | Create /paper/{pmid} to return stored metadata and abstract. **Why:** the frontend needs an easy way to inspect the exact source behind a citation.                                                                                                                                                                                                                                                                         | Paper detail endpoint    |
| 11.5     | Create /health and lightweight /metrics endpoints. **Why:** deployment needs operational checks and evaluation should capture latency/retry counts.                                                                                                                                                                                                                                                                         | Operational endpoints    |
| 11.6     | Use Pydantic models for QueryPlan, SearchResult, EvidenceRecord and ResearchResponse. **Why:** typed contracts reduce schema drift between LangGraph, API and UI layers.                                                                                                                                                                                                                                                    | Typed schemas            |
| 11.7     | Create /trace/{request_id} or include an equivalent trace object in /research containing query transformations, route, subqueries, retrieval-channel provenance, fusion/reranker scores, evidence-grader decisions, corrective-search count, selected PMIDs and version metadata. Why: the React UI needs structured decision metadata to provide auditability and explainability without exposing hidden chain-of-thought. | Explainability trace API |

# 16. Phase 12 - Researcher User Application

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                                                                                                                                        | **Output**                |
|----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| 12.1     | Build a React + Vite search interface with a prominent natural-language query box. **Why:** React gives us a flexible component-based UI for search, filters, evidence tables and interactive research results, while Vite keeps development and demo builds fast and the frontend remains cleanly separated from FastAPI.                                                | Search UI                 |
| 12.2     | Expose filters for year range, study/publication type and top-k only when useful. **Why:** structured controls complement semantic search without overwhelming the interface.                                                                                                                                                                                             | Filter panel              |
| 12.3     | Show the interpreted query, detected concepts and route in an expandable “How this search was understood” panel. **Why:** transparency helps researchers catch misinterpretation before trusting the synthesis.                                                                                                                                                           | Query trace panel         |
| 12.4     | Display retrieved paper cards with title, PMID, year, authors, MeSH, relevance signal and abstract preview. **Why:** users must be able to inspect source material rather than receiving only an AI summary.                                                                                                                                                              | Result cards              |
| 12.5     | Display the structured Evidence Table beside or below the research synthesis. **Why:** this exposes how the final comparison was constructed from individual studies.                                                                                                                                                                                                     | Evidence table UI         |
| 12.6     | Make PMID/citation items clickable to PubMed. **Why:** external source verification is essential for a research tool.                                                                                                                                                                                                                                                     | Source navigation         |
| 12.7     | Show evidence gaps, conflicts and insufficient-evidence warnings prominently. **Why:** uncertainty should be part of the product experience, not hidden in model internals.                                                                                                                                                                                               | Uncertainty UI            |
| 12.8     | Add a “Why this paper?” drawer for each result showing which retrieval channels found it, matched MeSH/keywords, dense/sparse/fusion/reranker scores and the filters it satisfied. Why: users should be able to understand why a study was ranked highly instead of treating relevance as a black box.                                                                    | Paper-level explanation   |
| 12.9     | Add claim-to-evidence interaction in the generated summary so selecting a citation or factual claim highlights the supporting EvidenceRecord and source abstract text. Why: direct claim-to-source inspection makes groundedness auditable and helps researchers verify synthesis quickly.                                                                                | Claim-evidence map        |
| 12.10    | Add an expandable Research Audit Trail showing the original query, enhanced query, extracted PICO/MeSH concepts, router decision, generated subqueries, corrective retrieval attempts, final evidence set and model/index versions. Why: this exposes the observable workflow and reproducibility metadata while deliberately avoiding free-form hidden chain-of-thought. | Research audit trail      |
| 12.11    | Allow export of the evidence table and audit trace as JSON/CSV where practical. Why: researchers can preserve the exact evidence set and system trace used for a result, making comparisons and external review easier.                                                                                                                                                   | Exportable audit artifact |

# 17. Phase 13 - Evaluation Strategy

Evaluation must test retrieval, routing, grounding and user-visible usefulness separately. A single “RAG score” is not sufficient. Use complementary layers: classical IR metrics for ranked PMID retrieval, RAGAS for context and generation quality, fine-grained RAG diagnostics for failure localization, medical robustness tests for noisy/conflicting evidence, deterministic citation checks and targeted human review.

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                                                                                                                           | **Output**                       |
|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------|
| 13.1     | Create a labelled query set spanning disease search, treatment effectiveness, adverse effects, association, comparison, date filtering and complex evidence synthesis. **Why:** different query classes stress different parts of the architecture.                                                                                                          | Benchmark set                    |
| 13.2     | For each query, manually label a small relevance set of known relevant PMIDs from the corpus, using PubMed/manual review where needed. **Why:** retrieval metrics require a reference set rather than an LLM’s opinion alone.                                                                                                                                | Relevance judgments              |
| 13.3     | Measure Recall@5/10, Precision@5/10, MRR and nDCG@10 for retrieval. **Why:** recall measures whether evidence is found, while ranking metrics measure whether it appears early enough to be useful.                                                                                                                                                          | Retrieval metrics                |
| 13.4     | Measure filter correctness for year/study-type constraints. **Why:** a semantically relevant paper that violates an explicit research filter is still an incorrect result.                                                                                                                                                                                   | Filter accuracy                  |
| 13.5     | Measure query router accuracy against manually assigned SIMPLE/MODERATE/COMPLEX labels. **Why:** poor routing can waste cost or prevent complex questions from receiving sufficient search depth.                                                                                                                                                            | Router accuracy                  |
| 13.6     | Measure citation validity as valid cited PMIDs / total cited PMIDs and citation attribution accuracy on a manually reviewed subset. **Why:** citation quality is a primary project requirement and should have its own metric.                                                                                                                               | Citation metrics                 |
| 13.7     | Measure groundedness/faithfulness using deterministic claim mapping plus RAGAS Faithfulness and an LLM-as-judge as secondary metrics, not as the only authority. Why: automatic judges provide scalable semantic checks, while deterministic citation/claim validation and manual medical review protect against judge errors.                               | Faithfulness / grounding metrics |
| 13.8     | Measure response completeness against required subquestions and evidence coverage. **Why:** a fully factual answer can still be unhelpful if it ignores half of a comparative query.                                                                                                                                                                         | Coverage metric                  |
| 13.9     | Track end-to-end latency, retrieval latency, reranking latency, LLM calls and corrective-loop count. **Why:** adaptive/agentic quality gains must be considered alongside operational cost.                                                                                                                                                                  | Performance metrics              |
| 13.10    | Run an ablation: dense-only baseline -\> hybrid -\> hybrid+reranker -\> full adaptive agentic pipeline. **Why:** this demonstrates the measurable contribution of each architectural layer.                                                                                                                                                                  | Ablation report                  |
| 13.11    | Run RAGAS retrieval evaluation using Context Precision and Context Recall on the benchmark, and use Context Entity Recall where useful for biomedical concepts. Why: these metrics evaluate whether retrieved context is both focused and sufficiently complete, complementing PMID-level Precision@K/Recall@K with semantic context-level evaluation.       | RAGAS retrieval report           |
| 13.12    | Run RAGAS generation evaluation using Faithfulness, Answer Relevancy and Answer Correctness when a reference answer is available. Why: the final answer must be supported by retrieved evidence, address the user’s question and match benchmark expectations rather than merely sounding fluent.                                                            | RAGAS generation report          |
| 13.13    | Add RAGChecker-style fine-grained diagnostics or an equivalent claim-level evaluation to separate retriever failures, context noise, unsupported claims and missed evidence. Why: a single aggregate score cannot tell whether an error came from search, reranking, evidence extraction or generation.                                                      | Fine-grained failure diagnostics |
| 13.14    | Run medical robustness tests inspired by MedRGB-style scenarios: inject irrelevant but plausible abstracts, conflicting evidence, incomplete evidence and misleading context, then measure whether the system preserves citations, identifies conflict or abstains. Why: medical RAG must remain reliable when retrieved evidence is noisy or contradictory. | Medical robustness report        |
| 13.15    | Perform a small human evaluation by medically literate reviewers or project evaluators scoring relevance, evidence coverage, citation attribution, factual support, usefulness and clarity on a representative sample. Why: framework metrics are proxies and should be triangulated with human judgement for research-oriented output.                      | Human evaluation sheet           |

# 18. Recommended Evaluation Targets

| **Decision**      | **Choice**                                                                                                                         | **Why this choice**                                                                                                                     |
|-------------------|------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| Retrieval recall  | Recall@10 \>= 0.80 on the curated benchmark                                                                                        | High recall is critical because the generator cannot use evidence that retrieval never finds.                                           |
| Ranking           | Improve MRR/nDCG over dense-only baseline                                                                                          | The absolute target depends on the labelled corpus; relative gain proves the hybrid/reranking value.                                    |
| Citation validity | 100% cited PMIDs present in EvidencePack                                                                                           | This deterministic requirement should be treated as a hard gate, not an average metric.                                                 |
| Filter accuracy   | Approximately 100% for explicit date/type filters                                                                                  | Metadata filters are deterministic and should rarely fail if data normalization is correct.                                             |
| Grounded claims   | Target \>= 95% supported factual claims on reviewed samples                                                                        | Medical research summaries should favor omission over unsupported inference.                                                            |
| Agent loop        | Most queries finish in 1 pass; complex queries \<= configured retry budget                                                         | The adaptive system should remain controlled and predictable.                                                                           |
| RAGAS retrieval   | Context Precision / Context Recall improve over dense-only and remain consistent with manual relevance labels                      | RAGAS should complement, not replace, explicit PMID relevance judgments and classical IR metrics.                                       |
| RAGAS generation  | High Faithfulness and Answer Relevancy, with Answer Correctness used where reference answers exist                                 | No universal threshold is assumed before benchmarking; compare variants on the same fixed evaluation set and inspect failures manually. |
| Robustness        | Minimal unsupported-claim increase under irrelevant/conflicting-context tests and correct abstention when evidence is insufficient | Medical research assistance should degrade safely when retrieval contains noise, contradiction or missing evidence.                     |

# 19. Phase 14 - Logging, Observability and Safety Controls

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                                           | **Output**                |
|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| 14.1     | Assign a request_id and log QueryPlan, route, subqueries, retrieved PMIDs, scores, evidence status and final citations. **Why:** agentic systems need a trace to explain why a particular paper or answer appeared.                                                          | Structured trace          |
| 14.2     | Log model names, prompt versions and index version with each evaluation run. **Why:** changing a model or prompt can alter results and must be reproducible.                                                                                                                 | Version traceability      |
| 14.3     | Do not log secrets or API keys and keep environment configuration in .env files excluded from Git. **Why:** the executable project must be safe to share and demo.                                                                                                           | Secret hygiene            |
| 14.4     | Display a research-use disclaimer in the UI and README. **Why:** the system summarizes literature and does not replace clinical judgment.                                                                                                                                    | Usage boundary            |
| 14.5     | Add explicit timeout, max-retry and max-subquery limits. **Why:** an agentic graph without resource guards can hang or become unexpectedly expensive.                                                                                                                        | Resource guards           |
| 14.6     | Persist retrieval provenance per PMID: dense rank/score, BM25 rank/score, graph source, RRF contribution, reranker score and applied filters. Why: paper-level explanations must be computed from real retrieval metadata rather than generated after the fact by an LLM.    | Retrieval provenance log  |
| 14.7     | Store claim-to-citation and claim-to-EvidenceRecord mappings for the final synthesis. Why: explainability should connect each material research claim to its actual evidence instead of offering generic post-hoc explanations.                                              | Claim provenance map      |
| 14.8     | Expose only structured workflow metadata and concise decision reasons in the UI, not private chain-of-thought. Why: researchers need reproducible system behavior, scores and evidence lineage, while hidden reasoning is neither required nor appropriate for auditability. | Safe explanation contract |

# 20. Recommended Repository Structure

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>medical-abstract-finder/<br />
├── backend/ # FastAPI + LangGraph research engine<br />
│ ├── app/<br />
│ │ ├── api/<br />
│ │ │ ├── routes_search.py # Standard semantic / hybrid search endpoints<br />
│ │ │ ├── routes_research.py # Adaptive-agentic research workflow endpoints<br />
│ │ │ ├── routes_papers.py # Paper / PMID detail and evidence endpoints<br />
│ │ │ ├── routes_audit.py # Audit-trail and explainability endpoints<br />
│ │ │ └── routes_health.py # Service-health endpoint<br />
│ │ ├── agents/<br />
│ │ │ ├── graph.py # LangGraph workflow definition<br />
│ │ │ ├── state.py # Shared workflow state<br />
│ │ │ └── nodes/<br />
│ │ │ ├── query_enhancer.py # Biomedical normalization before routing<br />
│ │ │ ├── query_analyzer.py # PICO, concepts, filters and intent extraction<br />
│ │ │ ├── router.py # Simple / moderate / complex route selection<br />
│ │ │ ├── planner.py # Multi-step research-plan generation<br />
│ │ │ ├── query_expander.py # Route-specific subquery generation<br />
│ │ │ ├── evidence_judge.py # CRAG-style retrieval sufficiency check<br />
│ │ │ ├── corrective_retrieval.py # Retry / reformulation when evidence is weak<br />
│ │ │ ├── evidence_extractor.py # Structured study-evidence extraction<br />
│ │ │ ├── study_comparator.py # Cross-study comparison and conflict detection<br />
│ │ │ ├── synthesizer.py # Grounded research-summary generation<br />
│ │ │ └── citation_validator.py # Claim / PMID validation before response<br />
│ │ ├── retrieval/<br />
│ │ │ ├── medcpt.py # Dense biomedical query/article encoding<br />
│ │ │ ├── bm25.py # Sparse lexical retrieval<br />
│ │ │ ├── hybrid.py # Dense + sparse + graph candidate orchestration<br />
│ │ │ ├── fusion.py # Reciprocal Rank Fusion / score fusion<br />
│ │ │ ├── reranker.py # MedCPT cross-encoder reranking<br />
│ │ │ ├── mesh.py # MeSH expansion and controlled vocabulary<br />
│ │ │ ├── metadata_filters.py # Year, study type, disease and other filters<br />
│ │ │ └── graph_retrieval.py # Paper-MeSH/entity graph retrieval<br />
│ │ ├── evidence/<br />
│ │ │ ├── schemas.py # EvidencePack and StudyEvidence contracts<br />
│ │ │ ├── provenance.py # Source, score, route and transformation tracking<br />
│ │ │ └── claim_mapping.py # Claim-to-evidence associations for explainability<br />
│ │ ├── models/<br />
│ │ │ ├── request_response.py # API request / response schemas<br />
│ │ │ └── paper.py # Canonical PubMed paper schema<br />
│ │ ├── services/<br />
│ │ │ ├── llm_provider.py # Provider-agnostic structured LLM adapter<br />
│ │ │ ├── qdrant_service.py # Vector / payload database access<br />
│ │ │ ├── mesh_service.py # MeSH lookup utilities<br />
│ │ │ └── audit_service.py # Persist and return research trace metadata<br />
│ │ ├── core/<br />
│ │ │ ├── config.py # Environment and runtime configuration<br />
│ │ │ ├── logging.py # Structured application logs<br />
│ │ │ ├── telemetry.py # Latency / node / retrieval instrumentation<br />
│ │ │ └── exceptions.py # Shared error definitions<br />
│ │ └── main.py # FastAPI application entry point<br />
│ └── tests/<br />
│ ├── unit/ # Node, retriever and validator unit tests<br />
│ ├── integration/ # Qdrant / API / workflow integration tests<br />
│ └── end_to_end/ # Query-to-cited-answer regression tests<br />
│<br />
├── frontend/ # React + Vite researcher application<br />
│ ├── src/<br />
│ │ ├── components/<br />
│ │ │ ├── search/<br />
│ │ │ │ ├── QueryInput.jsx # Natural-language research query input<br />
│ │ │ │ ├── FilterPanel.jsx # Year / MeSH / study-type filters<br />
│ │ │ │ └── QueryInterpretation.jsx # Shows normalized query and extracted concepts<br />
│ │ │ ├── results/<br />
│ │ │ │ ├── PaperCard.jsx # Ranked paper summary and metadata<br />
│ │ │ │ ├── AbstractViewer.jsx # Full abstract inspection<br />
│ │ │ │ ├── EvidenceTable.jsx # Structured cross-study evidence table<br />
│ │ │ │ └── CitationList.jsx # PMID-linked supporting citations<br />
│ │ │ ├── explainability/<br />
│ │ │ │ ├── WhyThisPaper.jsx # Explains retrieval signals for each result<br />
│ │ │ │ ├── RetrievalScoreBreakdown.jsx # Dense / BM25 / graph / reranker provenance<br />
│ │ │ │ ├── ClaimEvidenceMap.jsx # Connects generated claims to supporting studies<br />
│ │ │ │ └── ResearchAuditTrail.jsx # Query transforms, route, retries and evidence flow<br />
│ │ │ └── common/ # Shared UI components<br />
│ │ ├── pages/<br />
│ │ │ ├── SearchPage.jsx # Search and ranked abstracts<br />
│ │ │ ├── ResearchPage.jsx # Agentic synthesis and evidence comparison<br />
│ │ │ ├── PaperDetailPage.jsx # Individual-paper detail view<br />
│ │ │ └── EvaluationDashboard.jsx # Retrieval / RAGAS / latency demo metrics<br />
│ │ ├── services/<br />
│ │ │ └── api.js # FastAPI client<br />
│ │ ├── hooks/ # Search and research-state hooks<br />
│ │ ├── types/ # Frontend data contracts<br />
│ │ ├── App.jsx<br />
│ │ └── main.jsx<br />
│ ├── package.json<br />
│ └── vite.config.js<br />
│<br />
├── data/<br />
│ ├── raw/ # Original PubMed / MEDLINE files<br />
│ ├── processed/ # Clean canonical records<br />
│ ├── manifests/ # Dataset versions, counts and checksums<br />
│ └── evaluation/ # Frozen benchmark query/evidence sets<br />
│<br />
├── pipelines/ # Offline data and index-building jobs<br />
│ ├── inspect_dataset.py # Schema and data-quality profiling<br />
│ ├── preprocess.py # Cleaning and metadata normalization<br />
│ ├── build_embeddings.py # MedCPT document embedding generation<br />
│ ├── build_qdrant.py # Dense/sparse index construction<br />
│ ├── build_mesh_graph.py # Paper-MeSH/entity graph construction<br />
│ └── update_index.py # Incremental corpus/index updates<br />
│<br />
├── evaluation/<br />
│ ├── datasets/<br />
│ │ ├── queries.json # Representative research questions<br />
│ │ ├── relevance_labels.json # Retrieval relevance judgments<br />
│ │ └── grounded_answers.json # Reference answers where available<br />
│ ├── retrieval/<br />
│ │ ├── eval_ir_metrics.py # Recall@K, Precision@K, MRR and nDCG<br />
│ │ └── eval_ragas_context.py # RAGAS Context Precision / Recall<br />
│ ├── generation/<br />
│ │ ├── eval_ragas_generation.py # Faithfulness, relevancy and correctness<br />
│ │ └── eval_ragchecker.py # Fine-grained retriever/generator diagnostics<br />
│ ├── robustness/<br />
│ │ ├── noisy_query_tests.py # Acronym, spelling and lay-language robustness<br />
│ │ ├── conflicting_evidence_tests.py # Contradictory-study behavior<br />
│ │ └── citation_integrity_tests.py # Unsupported citation / claim checks<br />
│ ├── ablation.py # Baseline vs hybrid vs reranked vs full-agentic<br />
│ └── reports/ # JSON/CSV figures and evaluation summaries<br />
│<br />
├── docs/<br />
│ ├── architecture.md # Data-to-response architecture<br />
│ ├── design_decisions.md # Decisions and trade-offs<br />
│ ├── api_contract.md # API and provenance fields<br />
│ ├── evaluation_plan.md # Metrics, datasets and acceptance criteria<br />
│ └── demo_script.md # 8-minute guided demo flow<br />
│<br />
├── infra/<br />
│ ├── Dockerfile.backend # FastAPI container<br />
│ ├── Dockerfile.frontend # React production build/container<br />
│ └── docker-compose.yml # Backend + frontend + Qdrant orchestration<br />
│<br />
├── .github/<br />
│ └── workflows/<br />
│ └── ci.yml # Tests, linting and build validation<br />
├── requirements.txt # Python dependencies<br />
├── .env.example # Required environment variables<br />
├── .gitignore<br />
└── README.md # Setup, indexing, run, evaluation and sample usage</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 21. Core Data Contracts

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>QueryPlan<br />
- original_query<br />
- canonical_query<br />
- intent<br />
- pico: population/intervention/comparator/outcome<br />
- concepts / mesh_terms / synonyms<br />
- must_have / high_priority / optional_terms<br />
- filters<br />
- route + router_confidence<br />
- subqueries<br />
<br />
EvidenceRecord<br />
- pmid / title / year / authors<br />
- publication_type / mesh_terms<br />
- population<br />
- intervention_or_exposure<br />
- comparator<br />
- outcomes<br />
- key_findings<br />
- limitations<br />
- supporting_spans<br />
- retrieval_provenance<br />
- reranker_score<br />
<br />
ResearchResponse<br />
- interpreted_query<br />
- route / subqueries<br />
- summary<br />
- key_findings<br />
- comparison<br />
- conflicts<br />
- evidence_gaps<br />
- studies[]<br />
- citations[]<br />
- validation_status<br />
- trace_summary</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 22. LangGraph State Machine

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>START<br />
-&gt; enhance_query<br />
-&gt; analyze_query<br />
-&gt; route_query<br />
<br />
SIMPLE -&gt; retrieve<br />
MODERATE -&gt; expand_queries -&gt; retrieve<br />
COMPLEX -&gt; plan_research -&gt; retrieve<br />
<br />
retrieve<br />
-&gt; fuse<br />
-&gt; rerank<br />
-&gt; grade_evidence<br />
<br />
grade_evidence == sufficient<br />
-&gt; extract_evidence<br />
<br />
grade_evidence == partial/insufficient AND budget_remaining<br />
-&gt; corrective_query<br />
-&gt; retrieve<br />
<br />
grade_evidence == insufficient AND budget_exhausted<br />
-&gt; abstain_with_sources<br />
<br />
extract_evidence<br />
-&gt; compare_studies<br />
-&gt; synthesize<br />
-&gt; validate_citations<br />
<br />
validation failed AND retry_remaining<br />
-&gt; repair_answer<br />
-&gt; validate_citations<br />
<br />
validation passed<br />
-&gt; END</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 23. Recommended Build Order

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                                                                                      | **Output**                      |
|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------|
| B1       | Implement dataset inspection, preprocessing and canonical schema first. **Why:** every later stage depends on clean metadata and stable identifiers.                                                                                                                                                                    | Clean corpus                    |
| B2       | Implement MedCPT dense indexing and a dense-only /search baseline. **Why:** establishes that the corpus, embeddings and API work before adding complexity.                                                                                                                                                              | Baseline search                 |
| B3       | Add sparse/BM25 retrieval, metadata filters and RRF. **Why:** hybrid retrieval should be validated before any agent depends on it.                                                                                                                                                                                      | Hybrid search                   |
| B4       | Add MedCPT cross-encoder reranking and measure the gain. **Why:** reranking is a high-value precision improvement with relatively little architectural risk.                                                                                                                                                            | Reranked search                 |
| B5       | Add the Biomedical Query Understanding & Enhancement layer. **Why:** query normalization, MeSH and filter extraction improve all routes and should exist before the router.                                                                                                                                             | QueryPlan v1                    |
| B6       | Add adaptive SIMPLE/MODERATE/COMPLEX routing. **Why:** routing is the control layer that decides when advanced retrieval is justified.                                                                                                                                                                                  | Adaptive path                   |
| B7       | Add multi-query expansion for MODERATE queries. **Why:** this provides a controlled intermediate step before implementing the full agent loop.                                                                                                                                                                          | Multi-query retrieval           |
| B8       | Add complex research planning and LangGraph iterative retrieval. **Why:** agentic behavior should be built on a proven retriever, not used to compensate for an untested search layer.                                                                                                                                  | Agentic retrieval               |
| B9       | Add MeSH graph construction and graph retrieval only after hybrid retrieval works. **Why:** graph retrieval is valuable but should remain an additive channel, not a dependency blocking the MVP.                                                                                                                       | Graph-assisted retrieval        |
| B10      | Add evidence grading and corrective retrieval. **Why:** the agent needs a principled reason to search again instead of looping arbitrarily.                                                                                                                                                                             | CRAG-style correction           |
| B11      | Add EvidenceRecord extraction and evidence tables. **Why:** structured evidence is the bridge between retrieval and reliable synthesis.                                                                                                                                                                                 | EvidencePack                    |
| B12      | Add comparison/synthesis prompts and citation validation. **Why:** generation should be the last major intelligence layer, after retrieval quality and evidence structure are stable.                                                                                                                                   | Grounded answer                 |
| B13      | Build the React + Vite UI using already-tested API endpoints, including “Why this paper?”, claim-to-evidence mapping and the Research Audit Trail. Why: a decoupled React frontend can evolve independently from retrieval and reasoning logic while making retrieval provenance and evidence use directly inspectable. | Auditable demo application      |
| B14      | Run classical IR metrics, RAGAS, fine-grained RAG diagnostics, medical robustness tests, ablation and failure analysis; tune thresholds only from benchmark results. Why: final thresholds and architecture claims should be evidence-driven rather than selected by intuition.                                         | Comprehensive evaluation report |
| B15      | Containerize, finish README, architecture diagram and demo script. **Why:** reproducibility and explanation are explicit grading deliverables.                                                                                                                                                                          | Submission package              |

# 24. Suggested Execution Schedule

| **Decision** | **Choice**                                                                    | **Why this choice**                                                                                                    |
|--------------|-------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| Days 1-2     | Dataset inspection, preprocessing, schema, benchmark queries                  | Lock the data contract and evaluation set before model work.                                                           |
| Days 3-4     | MedCPT dense index + Qdrant + baseline API                                    | Get a working end-to-end search early.                                                                                 |
| Days 5-6     | BM25/sparse + filters + RRF + reranker                                        | Build the strongest deterministic retrieval layer.                                                                     |
| Days 7-8     | Query enhancer + analyzer + adaptive router                                   | Add biomedical understanding and adaptive control.                                                                     |
| Days 9-10    | Multi-query + complex planner + LangGraph                                     | Introduce agentic search only after retrieval is stable.                                                               |
| Day 11       | Evidence grader + corrective loop + graph retrieval                           | Improve failure recovery and concept-based recall.                                                                     |
| Day 12       | Evidence extraction + comparison + synthesis                                  | Turn retrieval output into research-oriented analysis.                                                                 |
| Day 13       | Citation validator + safety/abstention behavior                               | Make final answers auditable and grounded.                                                                             |
| Day 14       | React + Vite + explainability/auditability UI + API polish                    | Prepare a usable demonstration interface where users can inspect retrieval provenance, evidence lineage and citations. |
| Days 15-16   | Classical IR + RAGAS + robustness/fine-grained evaluation + ablation + tuning | Generate measurable proof for retrieval, generation, grounding, robustness and design decisions.                       |
| Days 17-18   | README, architecture diagram, Docker and panel presentation                   | Package the implementation and practice the final story.                                                               |

# 25. Scope Priorities: Must-Have vs Stretch

| **Decision**        | **Choice**                                                                                                                                                                                                                                              | **Why this choice**                                                                                                                            |
|---------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| Must-have           | Clean corpus, MedCPT dense retrieval, BM25, filters, RRF, reranker, query enhancer, adaptive router, evidence extraction, synthesis, citation validation, classical IR + RAGAS evaluation, FastAPI, React + Vite with auditability/explainability views | These directly satisfy the rubric and create a complete evidence-grounded product whose search and synthesis can be inspected by the end user. |
| High-value advanced | Multi-query retrieval, LangGraph complex planner, CRAG-style evidence grader/corrective loop                                                                                                                                                            | These are the core differentiators that make the system genuinely adaptive and agentic.                                                        |
| Optional advanced   | Paper-MeSH graph retrieval                                                                                                                                                                                                                              | Adds a clear advanced retrieval channel when MeSH metadata is rich enough, but the project still works without it.                             |
| Stretch only        | Citation graph traversal, full-paper ingestion, RAPTOR-style hierarchical retrieval, learned router, HyDE fallback, RL-trained search agent                                                                                                             | Interesting research extensions, but they introduce data or training work that can distract from the scored deliverables.                      |

# 26. Representative Test Queries

| **Step** | **Technical step + why we use it**                                                                                                                                                                       | **Output**         |
|----------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------|
| T1       | “Find recent studies on diabetic retinopathy published after 2022.” **Why:** tests simple semantic retrieval plus a hard publication-year filter.                                                        | Expected SIMPLE    |
| T2       | “Research on cardiovascular complications in T2DM patients treated with SGLT2 inhibitors.” **Why:** tests acronym expansion, medical normalization, MeSH expansion and hybrid retrieval.                 | Expected MODERATE  |
| T3       | “Compare GLP-1 receptor agonists and SGLT2 inhibitors for cardiovascular outcomes in adults with type 2 diabetes.” **Why:** tests decomposition, comparative evidence coverage and structured synthesis. | Expected COMPLEX   |
| T4       | “Do recent studies agree that mRNA vaccines are effective against non-COVID respiratory infections?” **Why:** tests recency, evidence sufficiency and agreement/disagreement analysis.                   | Expected COMPLEX   |
| T5       | “Find randomized controlled trials of treatment X in disease Y.” **Why:** tests study-type extraction and metadata filtering.                                                                            | SIMPLE/MODERATE    |
| T6       | “What evidence is available for an obscure disease-treatment combination with very few papers?” **Why:** tests corrective retrieval and graceful insufficient-evidence behavior.                         | Corrective/abstain |

# 27. Mapping to the Project Rubric

| **Decision** | **Choice**                                                                                                                                                                                                                              | **Why this choice**                                                                                                                           |
|--------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| Task 1 - 20% | Preprocessing, normalized biomedical metadata, MedCPT embeddings, BM25/sparse index, Qdrant, MeSH graph and index manifest                                                                                                              | Provides a reproducible searchable medical research knowledge base.                                                                           |
| Task 2 - 25% | Query enhancer, analyzer, adaptive routing, hybrid retrieval, filters, RRF, reranking and citations                                                                                                                                     | Implements natural-language semantic/hybrid evidence search with ranking and metadata control.                                                |
| Task 3 - 25% | Evidence grader, corrective retrieval, EvidenceRecords, cross-study comparison, grounded synthesis and citation validation                                                                                                              | Directly targets evidence-based research insights and unsupported-claim prevention.                                                           |
| Task 4 - 20% | Benchmark queries, classical retrieval metrics, RAGAS retrieval/generation metrics, robustness and fine-grained diagnostics, router/citation/grounding evaluation, ablation study and React + Vite app with auditability/explainability | Demonstrates measurable quality and provides an end-user application where search decisions, evidence lineage and citations can be inspected. |
| Task 5 - 10% | Architecture, technical decisions, trade-offs, Docker, README, API documentation and 8-minute demo                                                                                                                                      | Makes the project reproducible and easy to explain to the panel.                                                                              |

# 28. Major Risks and Trade-offs

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                      | **Output**               |
|----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------|
| R1       | Risk: Query enhancement changes medical meaning. Mitigation: keep original query, validate MeSH/synonyms and use both original and canonical retrieval. **Why:** recall gains are not worth semantic drift.                                             | Controlled enhancement   |
| R2       | Risk: Agentic loops increase latency/cost. Mitigation: adaptive router, fixed search budget and evidence-based stopping. **Why:** advanced reasoning should be spent only when it improves answerability.                                               | Bounded agent cost       |
| R3       | Risk: Graph retrieval creates noisy concept expansion. Mitigation: restrict graph depth and fuse/rerank graph candidates with other channels. **Why:** graph proximity alone is not evidence relevance.                                                 | Controlled graph channel |
| R4       | Risk: Study-type metadata may be absent or inconsistent. Mitigation: use source publication type first and abstract extraction only when explicit. **Why:** inferred study design can be wrong from abstracts.                                          | Metadata fallback        |
| R5       | Risk: LLM invents missing study details. Mitigation: strict EvidenceRecord schema with null allowed and supporting spans required. **Why:** missing information is safer than fabricated precision.                                                     | Faithful extraction      |
| R6       | Risk: Real PMID but incorrect claim attribution. Mitigation: claim-to-evidence validation after generation. **Why:** citation existence is not the same as citation correctness.                                                                        | Attribution validation   |
| R7       | Risk: Full PubMed scale overwhelms the development environment. Mitigation: validate architecture on a controlled subset and design batch/index interfaces for later scale-up. **Why:** retrieval quality should be proven before infrastructure scale. | Scalable scope           |

# 29. 10-Minute Panel Presentation Plan

| **Step**   | **Technical step + why we use it**                                                                                                                                                          | **Output**           |
|------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------|
| 0:00-0:45  | Problem and limitation of keyword/simple RAG search. **Why:** establishes the gap the architecture solves before showing technical detail.                                                  | Problem framing      |
| 0:45-1:45  | Show the architecture and explain the adaptive router, hybrid retrieval and evidence-validation loop. **Why:** these are the project’s main differentiators.                                | Architecture story   |
| 1:45-2:30  | Briefly show data preprocessing and the searchable knowledge base. **Why:** Task 1 carries 20% and should not be hidden behind the demo UI.                                                 | Knowledge base proof |
| 2:30-3:30  | Run a SIMPLE query and show query enhancement, filters and fast retrieval. **Why:** demonstrates that the architecture does not over-engineer straightforward searches.                     | Simple demo          |
| 3:30-6:30  | Run a COMPLEX comparative query and show planner subqueries, retrieval channels, reranking, evidence judge and any corrective loop. **Why:** visually proves the agentic/adaptive behavior. | Core advanced demo   |
| 6:30-7:15  | Show Evidence Table, study comparison, final summary and clickable PMID citations. **Why:** connects internal architecture to researcher value.                                             | Research output      |
| 7:15-8:00  | Show evaluation/ablation chart or table: dense vs hybrid vs rerank vs full agentic system. **Why:** proves the extra architecture is measurable, not decorative.                            | Evaluation evidence  |
| 8:00-10:00 | Q&A. Keep architecture trade-offs, corpus size, hallucination controls and scaling strategy ready. **Why:** these are likely panel questions for an advanced RAG design.                    | Q&A readiness        |

# 30. Final Deliverables Checklist

| **Step** | **Technical step + why we use it**                                                                                                                                                                                                                                                                                                                                           | **Output**                        |
|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------|
| D1       | Architecture diagram in JPEG/PDF showing offline indexing and online adaptive-agentic flow. **Why:** explicitly required and essential for communicating the system.                                                                                                                                                                                                         | Architecture asset                |
| D2       | Design document containing decisions and trade-offs from this plan. **Why:** the rubric asks for technical reasoning, not only source code.                                                                                                                                                                                                                                  | Design documentation              |
| D3       | Executable FastAPI microservice with modular retrieval/agent packages. **Why:** demonstrates production-style separation and testability.                                                                                                                                                                                                                                    | Backend code                      |
| D4       | React + Vite application with search, filters, abstracts, evidence table, summary, citations, “Why this paper?” explanations, claim-to-evidence mapping and a Research Audit Trail. Why: Task 4 requires an application for end users, and research users should be able to inspect how evidence produced the result.                                                        | Auditable frontend                |
| D5       | README with setup, environment variables, dataset preparation, index build, run commands, sample queries and expected output. **Why:** another user must be able to reproduce the solution.                                                                                                                                                                                  | README                            |
| D6       | Evaluation report with classical IR metrics, RAGAS Context Precision/Recall, Faithfulness/Answer Relevancy/Answer Correctness where applicable, fine-grained RAG diagnostics, medical robustness tests, benchmark queries, ablation results and failure cases. Why: quality claims must be backed by complementary retrieval, generation, grounding and robustness evidence. | Comprehensive evaluation artifact |
| D7       | Dockerfile/docker-compose for API, Qdrant and UI where practical. **Why:** reduces setup friction during review and demonstration.                                                                                                                                                                                                                                           | Container setup                   |
| D8       | 10-minute presentation with an 8-minute guided demo and 2-minute Q&A buffer. **Why:** this is a stated deliverable and should follow the architecture story rather than being a feature tour.                                                                                                                                                                                | Presentation                      |

# 31. Research Foundations for the Architecture

**MedCPT:** Jin et al., Bioinformatics, 2023. Biomedical retriever and reranker trained from large-scale PubMed search logs. <u>https://pubmed.ncbi.nlm.nih.gov/37930897/</u>

**Adaptive-RAG:** Jeong et al., NAACL 2024. Dynamically selects retrieval strategy according to query complexity. <u>https://aclanthology.org/2024.naacl-long.389/</u>

**Corrective RAG (CRAG):** Yan et al., 2024. Uses a retrieval evaluator and corrective actions when retrieved evidence is weak. <u>https://arxiv.org/abs/2401.15884</u>

**PaperQA2 / language agents for science:** Skarlinski et al., 2024. Agentic scientific literature search, evidence gathering and citation-grounded synthesis. <u>https://arxiv.org/abs/2409.13740</u>

**Medical Graph RAG:** Wu et al., ACL 2025. Graph retrieval for evidence-based medical generation. <u>https://aclanthology.org/2025.acl-long.1381/</u>

| **Final rule: do not return a medical claim or citation unless it is traceable to the retrieved evidence.** |
|-------------------------------------------------------------------------------------------------------------|

# 32. Dataset Reference Links

Reference sources for obtaining the PubMed / MEDLINE abstract corpus used by this project. **Why:** keeping the primary and alternative dataset locations in the implementation plan makes dataset acquisition reproducible and provides fallback sources for development, subsets and experiments.

| **Priority** | **Dataset / Source**                   | **Reference Link**                                                                                                          |
|--------------|----------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| Primary      | PubMed / MEDLINE Download              | [<u>https://pubmed.ncbi.nlm.nih.gov/download/</u>](https://pubmed.ncbi.nlm.nih.gov/download/)                               |
| Alternative  | NCBI PubMed dataset on Hugging Face    | [<u>https://huggingface.co/datasets/ncbi/pubmed</u>](https://huggingface.co/datasets/ncbi/pubmed)                           |
| Alternative  | PubMed Abstracts dataset on Kaggle     | [<u>https://www.kaggle.com/datasets/bonhart/pubmed-abstracts</u>](https://www.kaggle.com/datasets/bonhart/pubmed-abstracts) |
| Alternative  | PubMed Central Text Mining Collections | [<u>https://pmc.ncbi.nlm.nih.gov/tools/textmining/</u>](https://pmc.ncbi.nlm.nih.gov/tools/textmining/)                     |
| Alternative  | NCBI BioNLP Research Data              | [<u>https://www.ncbi.nlm.nih.gov/research/bionlp/Data/</u>](https://www.ncbi.nlm.nih.gov/research/bionlp/Data/)             |
