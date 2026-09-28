# Ordinary-user UI stress QA inventory

Target: the live local Evidence Atlas UI backed by the complete real PubMed/MedCPT index and NVIDIA NIM synthesis.

| Claim or control | Functional check | Visual state and evidence |
| --- | --- | --- |
| A normal user can research a medical question | Fill `#research-query`, click **Research**, wait for evidence synthesis and ranked papers | Desktop screenshot of the populated result state |
| Results come from the complete local index | Verify the live health/index count before the run and confirm returned PMIDs exist in the indexed corpus | Result count, paper titles, and citations visible in the UI |
| Paper details work | Open the top paper, inspect Overview and PubMed link, then close the drawer | Screenshot with the details drawer open |
| Filters and validation work | Change year/study type, run again, then submit a reversed year range | Filtered result state and visible validation alert |
| Admin diagnostics are not exposed | Use a fresh context with no admin session storage; assert diagnostic headings, scores, traces, provenance, and evidence spans are absent | Ordinary-user populated result screenshot |
| The interface survives repeated load | Run sequential searches, followed by independent user contexts at concurrency 2, 5, and 10 | Latency/success report plus drained backend active-query count |
| Responsive UI remains usable | Repeat the main journey at 1440x900 and 390x844 | Desktop and mobile screenshots; no horizontal overflow or clipped controls |
| Provider/backend failures are understandable | Record any live provider/rate-limit or backend error and verify a visible alert rather than fabricated success | Error screenshot when encountered |

Exploratory cases: rapid independent submissions during model warm-up, long biomedical wording, comparison/mechanism questions, zero/low-result filters, and opening/closing dense paper details on mobile.

Acceptance thresholds: 100% successful completion through concurrency 5; at concurrency 10, at least 95% successful completion, no 5xx/schema/citation corruption, p95 no more than 3x the warm sequential p95, and active queries returning to zero after the run.
