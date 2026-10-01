# Evidence Atlas evaluator improvements

The original demonstration had two useful searches discarded during verification, and an AA amyloidosis answer labelled supported despite explicit coverage gaps. A defensible evaluation should reward usefulness, source traceability, honest coverage, safe refusal, and understandable controls. These changes address those behaviors; they do not guarantee a score.

## Evidence release and extraction

**What I did:** Validate cited, exact stored source spans locally before optional semantic provider calls. Every cited source must match the quoted finding. Generated prose still requires complete semantic verdicts. Rank source sentences using query overlap, abstract sections, clinical results and numerical outcome signals; inherit structured abstract sections. Rank fallback findings across all papers, allowing several outcomes from one study within the four-span limit. Require no known coverage gaps for `SUPPORTED`; otherwise release valid findings as `LIMITED`.

**Why this approach:** Structured `{pmid, span_index}` model selections already identify stored sentences. Exact identity supplies deterministic evidence of what an abstract says, without spending another model call to recheck a quotation.

**Why not the alternative:** Increasing timeouts would retain latency and dependence on the same probabilistic verifier. Lowering the semantic threshold would risk releasing invented claims. Hardcoding the demonstration questions or their answers would not generalize.

**Issue / root cause:** The live provider shares a cumulative request budget. Rechecking already grounded selections could exhaust that budget and prune useful evidence. Overlap-only extraction favored background and aims, while status assignment used retrieval sufficiency despite response coverage gaps.

**Why this works best here:** Abstract wording, effect direction, numbers and citations remain source-derived. Novel claims retain the stricter verification path. Coverage labels describe what this search established rather than how many related papers were retrieved.

**Other valid patterns:** A dedicated independent semantic model can review generated summaries at greater latency and cost. Full-text evidence can improve population and endpoint coverage, but needs retrieval, licensing and provenance work. Extractive answers remain conservative and can be less fluent than verified summaries.

## Combined answer summaries

**What I did:** Extend structured source selection with one or two short summary sentences and explicit source IDs. Check strict structure, selected-source membership, citation/number/direction support and independent semantic entailment before releasing the summary. Map combined findings to original passages from the same paper or multiple cited papers. Each cited paper must contribute audited passages, and a supported semantic verdict must include every cited PMID. Retain selected source excerpts if summarization is malformed, unsupported or unavailable. Original passages remain accessible through citations and evidence details. Increase the bounded synthesis output allowance from 300 to 600 tokens to fit the extended JSON without truncation; retain the cumulative provider time budget.

**Why this approach:** The reader gets a direct combined answer, while the sources remain reviewable. Selection and summary share one generation request; request-scoped semantic caching avoids repeating identical verification calls during release.

**Why not the alternative:** Simply concatenating several conclusions is hard to read. Unverified rewriting can change null results, numerical effects or association into causation. Extra summarization calls after a complete answer would consume the limited provider budget.

**Issue / root cause:** Extractive output preserved evidence integrity but presented separate study conclusions without a readable synthesis. The original support gate required one passage to support an entire sentence, preventing legitimate connections across several findings or studies. Short output budgets could also truncate the larger summary JSON.

**Why this works best here:** A bounded structured draft can improve readability without bypassing existing evidence checks or destroying useful exact findings when the provider fails.

**Other valid patterns:** Deterministic templates can summarize counts and provenance safely, but cannot combine clinical meanings fluently. A separate summarizer is viable with an independently budgeted verifier and greater latency.

Joint lexical matching only identifies candidate evidence; it does not establish clinical entailment. The semantic verifier must check every component, source attribution, population and endpoint boundaries, and association versus causation. The requested exact acronym subtype also excludes records that explicitly discuss a different subtype without mentioning the requested one; missing subtype information remains uncertain. This is a conservative lexical boundary, not a complete clinical ontology.

## Research workspace

**What I did:** Add a restrained sage and teal reading layout, an editable question list, searchable history, optional advanced filters with date validation/reset, clearer loading and evidence states, readable findings, cited-first source cards, copy feedback, and progressive disclosure for evidence details. Preserve citation drawers, original abstracts, exports and admin access. Keep drafts typed during pending requests; support Enter, Shift+Enter and composition input. Translate fixed presentation boilerplate without rewriting medical source sentences or exports.

**Why this approach:** Users can begin with a question, read findings, inspect their papers, and follow up without confronting all technical controls at once.

**Why not the alternative:** A cosmetic status rename alone would preserve misleading answers. A framework migration would introduce avoidable integration work. Hiding limitations or calling every retrieved paper a supporting source would weaken trust.

**Issue / root cause:** Technical statuses and repeated caveats dominated the response, essential actions had little hierarchy, and candidates were visually indistinguishable from cited evidence.

The final browser pass also exposed a clipped header title and a pending-turn reconciliation race during hot reload. The display now uses the full question when the stored title is its 80-character automatic prefix, preserving custom titles. Completion replaces both its temporary turn ID and any already loaded persisted turn ID, preventing duplicate message bubbles. A later draft typed during research was confirmed to survive completion.

**Why this works best here:** The existing React, routing, authentication, API and evidence contracts remain intact. Native disclosures and labelled controls keep detail available, while the primary reading path is simpler.

**Other valid patterns:** A persistent two-column evidence pane works well on large screens but consumes reading space. A mobile source sheet is another option; the existing evidence workspace remains available in this iteration.

## Regression fixtures

**What I did:** Add unseen-topic extraction, exact-source outage, altered-number/direction, every-citation identity, and multi-outcome fallback tests. Update semantic rejection fixtures to use generated paraphrases rather than exact copied sentences; preserve pruning and fail-closed assertions. Update coverage expectations to require `LIMITED` when an explicit gap remains.

**Why this approach:** The tests distinguish deterministic source identity from probabilistic verification and check the actual guardrail each fixture intends to exercise.

**Why not the alternative:** Deleting failing guardrail assertions would conceal regressions. Treating a correct quotation as unsupported because of a test provider's arbitrary refusal would test the obsolete release policy.

**Issue / root cause:** Several fixtures assumed every exact quotation required an optional model verdict or that known gaps could still receive `SUPPORTED`.

**Why this works best here:** Safety assertions still reject unsupported generated claims, wrong numbers, effect reversals, and incomplete source identities.

**Other valid patterns:** Provider integration tests can supplement deterministic regressions, but require stable credentials, budgets and network conditions.

## Live PubMed proposal

This is a proposed follow-up, not an implemented feature. Use local retrieval first, with a visible live PubMed option or fallback when local coverage is poor. Fetch PubMed records through NCBI ESearch/EFetch, validate and normalize PMIDs and abstracts, deduplicate local and live records, and feed them through the same evidence pipeline. Display origin and retrieval date. Bound requests, cache results, respect rate limits, and report timeouts or empty results honestly. Retrieved text remains untrusted data and cannot direct agent actions.

The search itself does not establish evidence quality, completeness, or causal certainty. Keep an explicit distinction between a source-backed association and a clinical recommendation. Do not label `INSUFFICIENT` as proof that no published evidence exists.

Reference: [NCBI E-utilities documentation](https://www.ncbi.nlm.nih.gov/books/NBK25497/).

## Validation and demonstration

Final automated validation: **1225 passed, 2 skipped**, with 9 existing FastAPI/local-Qdrant warnings; frontend production build passed. Focused follow-up and report regressions also pass. Same-paper and multi-paper summary tests, semantic source attribution, malformed verdicts, wrong numbers, provider failures, safe refusal and release coverage are included. Demonstrate a fresh question, a partial answer with visible gaps, an original abstract opened from a citation, an editable follow-up, and the safe refusal case. The current corpus remains local and topic-skewed; this iteration improves evidence release and presentation, not corpus breadth.

Root owned planning, backend summary design, integration, final review and validation. GPT-5.6 Luna agents performed bounded extraction, UI and regression-fixture work and read-only diagnosis/review. Returned changes were reviewed and tested before acceptance; earlier agent interruptions were recovered from saved files. No commits or publication were requested.

| Assignment | Ownership boundary | Merge and validation | Status |
| --- | --- | --- | --- |
| Finding selection | Extraction scorer and unseen-topic tests | Root review; extraction and workflow regressions | integrated, closed |
| UI work | Composer and response components/styles | Root integration; production build; browser checks | integrated, closed |
| Release diagnosis/review | Read-only release and summary gates | Root reviewed findings; provider-outage and semantic tests | integrated, closed |
| Guardrail fixtures | Assigned unit/adversarial tests and new summary tests | Root reviewed diffs; targeted and full-suite validation | integrated, closed |

Browser checks verified history filtering, editable examples and follow-ups, date validation/reset, Shift+Enter, citation-to-abstract navigation, source expansion, copy feedback, and 390px layout without page overflow, including the evidence drawer. Screenshots are saved under `output/research-summary-desktop.jpg`, `output/research-source-desktop.jpg`, and `output/research-summary-mobile.jpg`. The JSON download action was exercised, but the in-app browser did not expose a completed download event; saved-file contents were not independently verified. Live provider behavior remains variable and can fall back to excerpts when summary verification fails.

Final authenticated live checks produced readable summaries for telehealth (`LIMITED` with a population gap), nephrolithiasis (`SUPPORTED`), and AA amyloidosis (`LIMITED` with population/outcome gaps). The attack remained `ABSTAIN` with zero citations. An additional cross-study question released a combined summary citing PMIDs 23736840 and 24848936. Cited IDs were checked against retrieved papers, and the answer text passed the local support audit; summaries also went through the workflow's semantic verifier. Results are recorded in `output/overhaul-final-live-results.json`. These runs demonstrate working source-grounded flows, not independent clinical adjudication or a guarantee of future provider output quality.

Final multi-paper preview: `output/research-multi-paper-summary.jpg`; unified report proof: `output/unified-research-report.jpg`. The full question title and report were checked at 1440px and 390px, with no page overflow; the report sections have no separate card borders, the composer appears once before deferred evidence details, and temporary viewport overrides were reset. An authenticated live follow-up reused the prior nephrolithiasis evidence: the first turn was `SUPPORTED`, and “Which findings are consistent across the studies?” returned `ANSWER_FROM_EVIDENCE` with cited PMIDs. A draft typed while the request was pending remained in the composer. The frontend on port 5173 and backend on port 8000 remain running for the requested local product. Temporary test commands finished; agent tasks are closed.

## Expanded research explanations

**What I did:** Increase the synthesis ceiling from 600 to 2,048 output tokens and replace the 70-word prompt with a three-part report: findings and sources, how studies relate, and a final summary. Aim for 250–450 words when justified by the supplied passages, with a validated 500-word ceiling, eight paragraphs maximum and 1,000 characters per paragraph. Present the sections as one continuous response with subtle headings, while retaining citation drawers, limitations, copy/export and legacy responses. Give report generation up to 30 seconds within a cumulative 60-second provider budget; other structured calls keep their 10-second ceiling. Permit one bounded revision after a rejected report, with the same source and verification constraints. Raise the bounded assistant-message contract to 12,000 characters and remove silent 4,000-character slicing so final paragraphs and citations survive delivery, persistence and follow-up history.

**Why this approach:** More tokens alone cannot overcome a two-sentence schema or a display that merges every sentence. Structure gives readers the evidence, its relationship to the question, and a direct answer without obscuring provenance.

**Why not the alternative:** Unlimited prose or lower verification thresholds could make the report longer while releasing unsupported interpretations. A minimum word count would pad sparse evidence. Unbounded retries would make the research desk unpredictable.

**Issue / root cause:** Generation was deliberately capped at 70 words and two items, with a 600-token limit. The original presentation also joined all cited lines into one paragraph. Expanded comparison prose sometimes failed evidence verification because it introduced speculative interpretation or changed an endpoint; the revised prompts require concrete outcomes and preserve source subgroup and endpoint names.

**Why this works best here:** Each paragraph must pass citation-to-span matching and independent semantic verification before release. Report headings are fixed local presentation labels. Representative span indices select the papers; report validation may use all already extracted source passages of those papers, never an unselected PMID. Failed revisions retain exact source excerpts, and known gaps still prevent a `SUPPORTED` status. Raising the token ceiling permits detail but does not guarantee a long report when the corpus is thin.

**Other valid patterns:** A configurable brief/detailed report toggle is useful when users have different reading needs. Progressive streaming could reduce perceived latency, but unverified medical prose should not appear as an approved answer. Structured generation still needs application validation because JSON-object mode allows arbitrary JSON; see [NVIDIA structured-generation documentation](https://docs.nvidia.com/nim/large-language-models/1.14.0/structured-generation.html).

Root owns the report schema, budget, revision policy, integration and final validation. GPT-5.6 Luna completed bounded response rendering and regression-test tasks; a separate read-only review checked release boundaries. Returned work is reviewed before acceptance.

## Follow-up placement and context

**What I did:** Put a single stable follow-up composer immediately after the latest response and before evidence details. Defer the latest response's evidence table, search interpretation, audit and candidate papers below the composer; older responses retain their source controls. Preserve limits beside the answer. Recognize references such as “the studies” and “previous findings” as context-dependent requests, allowing the planner to see previous turns. When a requested prior turn has no released evidence, return a normal clarification with no citations rather than a technical failure.

**Why this approach:** The next question should be available at the end of the answer, and its routing should resolve the subject from the conversation. Reusing the same composer instance preserves filters and drafts typed while research is pending.

**Why not the alternative:** A new composer inside each changing message would remount its state and risk clearing a later draft. A floating overlay can obscure evidence or mobile controls. Adding generic “studies” to the biomedical-topic allowlist would let unrelated questions bypass the topic boundary.

**Issue / root cause:** Candidate evidence and audit controls separated the answer from the input. The suggested consistency question lacked a pronoun recognized by the routing heuristic, so it could be rejected before history reached the planner. A no-evidence prior turn was treated as an exception instead of an expected research limitation.

**Why this works best here:** Source controls keep their original turn IDs and citations. Only context-dependent research references reach contextual planning; prohibited requests and rewritten biomedical-query checks remain enforced. Evidence reuse remains restricted to completed `SUPPORTED`/`LIMITED` turns, and missing evidence never becomes fabricated clinical content.

**Other valid patterns:** A compact docked composer is appropriate for long chats when viewport and keyboard behavior are tested carefully. A dedicated follow-up panel can work for report-oriented workflows but duplicates state unless it shares one controlled draft.
