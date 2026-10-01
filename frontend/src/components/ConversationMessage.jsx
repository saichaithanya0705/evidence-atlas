import { useCallback, useMemo, useState } from "react";
import { getTrace } from "../api.js";
import { exportPublicResearchJson, exportResearchJson, getCitationPmids } from "../utils.js";
import AuditTrail from "./AuditTrail.jsx";
import EvidenceTable from "./EvidenceTable.jsx";
import InterpretationPanel from "./InterpretationPanel.jsx";
import { renderCitations } from "./SynthesisPanel.jsx";
import "./ConversationMessage.css";

const statusLabels = {
  SUPPORTED: "Source-backed findings",
  LIMITED: "Partial answer",
  PARTIAL: "Partial answer",
  INSUFFICIENT: "Evidence is limited",
  ABSTAIN: "Outside research scope",
  FAILED: "Could not complete",
};

function uniquePmids(values = []) {
  return [...new Set(values.filter(Boolean).map(String))];
}

function useResearchExport({ result, content, citedPmids, retrievedPapers, evidenceRows, isAdmin, trace }) {
  return useCallback(() => {
    const exportPayload = {
      query: result?.query,
      synthesis: content,
      cited_pmids: citedPmids,
      consensus_level: result?.consensus_level,
      evidence_gaps: result?.evidence_gaps || [],
      retrieved_papers: retrievedPapers.map(paper => ({
        pmid: paper.pmid, title: paper.title, abstract: paper.abstract, journal: paper.journal,
        year: paper.year, authors: paper.authors, mesh_terms: paper.mesh_terms, study_type: paper.study_type,
      })),
      evidence_table: evidenceRows.map(row => ({
        pmid: row.pmid, title: row.title, year: row.year, study_design: row.study_design,
        population: row.population, intervention: row.intervention, comparator: row.comparator,
        outcome: row.outcome, key_findings: row.key_findings, limitations: row.limitations,
        supporting_text_spans: row.supporting_text_spans, retrieval_channels: row.retrieval_channels,
        subquestion_ids: row.subquestion_ids,
      })),
    };
    if (!isAdmin) exportPublicResearchJson(exportPayload);
    else exportResearchJson({ ...exportPayload, request_id: result?.request_id }, trace);
  }, [citedPmids, content, evidenceRows, isAdmin, result, retrievedPapers, trace]);
}

function RetrievedSources({ papers, citedPmids, onSelect }) {
  const [showAll, setShowAll] = useState(false);
  const orderedPapers = [...papers].sort((a, b) => Number(citedPmids.includes(String(b.pmid))) - Number(citedPmids.includes(String(a.pmid))));
  const visiblePapers = showAll ? orderedPapers : orderedPapers.slice(0, 3);
  const citedCandidateCount = papers.filter(paper => citedPmids.includes(String(paper.pmid))).length;
  if (!papers.length) return null;

  return <section className="message-papers" aria-label="Related source papers">
    <div className="message-papers-heading">
      <div>
        <h3>Candidate sources</h3>
        <p className="message-section-note">{citedCandidateCount} of {papers.length} candidate {papers.length === 1 ? "paper is cited in" : "papers are cited in"} the answer.</p>
      </div>
      {papers.length > 3 && <button type="button" className="plain-button source-toggle" onClick={() => setShowAll(value => !value)} aria-expanded={showAll}>
        {showAll ? "Show fewer" : `Show all ${papers.length}`}
      </button>}
    </div>
    <ul>{visiblePapers.map(paper => {
      const pmid = String(paper.pmid);
      const cited = citedPmids.includes(pmid);
      return <li key={pmid} className="source-card">
        <div className="source-card-main">
          <button type="button" className="source-title-button" onClick={() => onSelect?.(paper)}>{paper.title || `PMID ${pmid}`}</button>
          <span className={`source-support-status${cited ? " is-supported" : ""}`}>{cited ? "Cited in answer" : "Candidate source"}</span>
        </div>
        <div className="source-card-meta">
          <button type="button" className="source-pmid-button" onClick={() => onSelect?.(paper)}>PMID: {pmid}</button>
          <span>{[paper.year, paper.study_type, paper.journal].filter(Boolean).join(" · ")}</span>
        </div>
      </li>;
    })}</ul>
  </section>;
}

export function ConversationEvidenceDetails({ content, result, turnId, onEvidence, onPaper, isAdmin = false, activePmids = [], citedPmids = [], retrievedPapers, evidenceRows }) {
  const [audit, setAudit] = useState({ trace: null, loading: false, error: "" });
  const effectiveCitedPmids = citedPmids.length ? citedPmids : uniquePmids(result?.cited_pmids?.length ? result.cited_pmids : getCitationPmids(content || ""));
  const effectiveRetrievedPapers = useMemo(() => retrievedPapers || [...new Map((result?.retrieved_papers || []).filter(paper => paper?.pmid).map(paper => [String(paper.pmid), paper])).values()], [retrievedPapers, result?.retrieved_papers]);
  const effectiveEvidenceRows = evidenceRows || result?.evidence_table || [];
  const exportJson = useResearchExport({ result, content, citedPmids: effectiveCitedPmids, retrievedPapers: effectiveRetrievedPapers, evidenceRows: effectiveEvidenceRows, isAdmin, trace: audit.trace });
  const openEvidence = useCallback((pmid, target = {}) => onEvidence?.(pmid, { turnId, ...target }), [onEvidence, turnId]);
  const loadAudit = useCallback(async () => {
    if (!isAdmin || !result?.request_id || audit.loading) return;
    setAudit(current => ({ ...current, loading: true, error: "" }));
    try {
      const trace = await getTrace(result.request_id);
      setAudit({ trace, loading: false, error: "" });
    } catch (error) {
      setAudit({ trace: null, loading: false, error: error instanceof Error ? error.message : "Audit trace could not be loaded." });
    }
  }, [audit.loading, isAdmin, result?.request_id]);
  return <article className="conversation-message conversation-evidence-details">
    {result?.interpretation && <InterpretationPanel interpretation={result.interpretation} isAdmin={isAdmin} initiallyExpanded={false} />}
    {effectiveEvidenceRows.length > 0 && <details className="message-disclosure evidence-disclosure"><summary>Compare {effectiveEvidenceRows.length} retrieved evidence {effectiveEvidenceRows.length === 1 ? "record" : "records"}</summary><EvidenceTable rows={effectiveEvidenceRows} activePmids={activePmids} turnId={turnId} coverageStatuses={result?.interpretation?.coverage_statuses || []} onTraceEvidence={openEvidence} onExportJson={exportJson} /></details>}
    {isAdmin && result?.request_id && <AuditTrail research={result} trace={audit.trace} loading={audit.loading} error={audit.error} onLoad={loadAudit} onExport={exportJson} />}
    <RetrievedSources papers={effectiveRetrievedPapers} citedPmids={effectiveCitedPmids} onSelect={onPaper ? paper => onPaper(paper, { turnId }) : undefined} />
  </article>;
}

export default function ConversationMessage({ role, content, status, action, result, turnId, onEvidence, onPaper, isAdmin = false, activePmids = [], deferDetails = false }) {
  const [copyState, setCopyState] = useState("");
  const isAssistant = role === "assistant";
  const failed = status === "FAILED";
  const researched = action !== "CLARIFY" && action !== "ABSTAIN";
  const evidenceRows = result?.evidence_table || [];
  const retrievedPapers = useMemo(() => {
    const seen = new Set();
    return (result?.retrieved_papers || []).filter(paper => {
      const pmid = String(paper.pmid || "");
      if (!pmid || seen.has(pmid)) return false;
      seen.add(pmid);
      return true;
    });
  }, [result?.retrieved_papers]);
  const citedPmids = useMemo(() => uniquePmids(result?.cited_pmids?.length ? result.cited_pmids : getCitationPmids(content || "")), [content, result?.cited_pmids]);
  const answerParagraphs = useMemo(() => (content || "").split(/\n+/).filter(Boolean), [content]);
  const sourceExcerpts = answerParagraphs.includes("Retrieved abstract evidence:");
  const reportSections = useMemo(() => {
    const headings = {
      "Findings and sources:": "findings",
      "How the studies relate:": "relationships",
      "Final summary:": "summary",
    };
    if (!Object.keys(headings).every(heading => answerParagraphs.includes(heading))) return null;
    const sections = [];
    let current = null;
    answerParagraphs.forEach(paragraph => {
      const kind = headings[paragraph];
      if (kind) {
        current = { kind, heading: paragraph, paragraphs: [] };
        sections.push(current);
      } else if (current) current.paragraphs.push(paragraph);
    });
    return sections;
  }, [answerParagraphs]);
  const summaryFindings = isAssistant && researched && !sourceExcerpts && !reportSections && !failed && citedPmids.length > 0;

  const openEvidence = useCallback((pmid, target = {}) => onEvidence?.(pmid, { turnId, ...target }), [onEvidence, turnId]);
  const openCitations = useCallback(pmids => pmids.forEach(pmid => openEvidence(pmid)), [openEvidence]);
  const exportJson = useResearchExport({ result, content, citedPmids, retrievedPapers, evidenceRows, isAdmin, trace: null });

  const copyAnswer = useCallback(async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard is unavailable in this browser.");
      await navigator.clipboard.writeText(content || "");
      setCopyState("Answer copied");
    } catch (error) {
      setCopyState(error instanceof Error ? error.message : "Could not copy the answer.");
    }
  }, [content]);

  const statusLabel = action === "ABSTAIN" ? statusLabels.ABSTAIN : statusLabels[status] || status;
  function presentationText(paragraph) {
    if (paragraph === "Retrieved abstract evidence:") return "What the abstracts report";
    if (paragraph === "Evidence gaps are listed separately in the response.") return null;
    if (paragraph === "The full question was not established by the available evidence.") return "These findings cover part of your question. The limitations below explain what remains unresolved.";
    if (paragraph === "The available retrieved evidence is insufficient to provide a validated research summary.") return "I couldn't establish a source-backed answer from this search. You can inspect the candidate papers below, or narrow the population and outcome in your question.";
    return paragraph;
  }
  return <article className={`conversation-message conversation-${role}${failed ? " conversation-failed" : ""}`}>
    <div className="conversation-message-heading"><strong>{isAssistant ? "Evidence Atlas" : "You"}</strong>{isAssistant && statusLabel && <span className={`answer-status status-${status?.toLowerCase() || "default"}`}>{statusLabel}</span>}</div>
    {summaryFindings && <h3 className="message-summary-label">Evidence summary</h3>}
    <div className="message-answer">{reportSections ? <div className="message-report" aria-label="Research report">
      {reportSections.map(section => <section className={`message-report-section report-section-${section.kind}`} key={section.kind}>
        <h3>{section.heading}</h3>
        <div className="message-report-body">{section.paragraphs.map((paragraph, index) => <p key={index}>{renderCitations(paragraph, openCitations)}</p>)}</div>
      </section>)}
    </div> : summaryFindings ? <>
      <p className="combined-summary">{answerParagraphs.filter(paragraph => getCitationPmids(paragraph).length).map((paragraph, index) => <span key={index}>{index > 0 ? " " : ""}{renderCitations(paragraph, openCitations)}</span>)}</p>
      {answerParagraphs.filter(paragraph => !getCitationPmids(paragraph).length).map((paragraph, index) => { const displayed = presentationText(paragraph); return displayed && <p className="answer-context" key={index}>{displayed}</p>; })}
    </> : isAssistant ? answerParagraphs.map((paragraph, index) => { const displayed = presentationText(paragraph); return displayed && <p className={getCitationPmids(paragraph).length ? "source-finding" : "answer-context"} key={index}>{renderCitations(displayed, openCitations)}</p>; }) : content}</div>
    {isAssistant && researched && <div className="message-toolbar" aria-label="Answer actions">
      <button type="button" className="text-icon-button" onClick={copyAnswer}>Copy answer</button>
      <button type="button" className="text-icon-button" onClick={exportJson}>Download JSON</button>
      {copyState && <span className="message-action-feedback" role="status" aria-live="polite">{copyState}</span>}
    </div>}
    {failed && <p className="message-context">A technical failure prevented this turn from completing. This is not a finding about the evidence.</p>}
    {isAssistant && researched && result?.evidence_gaps?.length > 0 && <section className="message-limitations" aria-labelledby={`limitations-${turnId}`}><h3 id={`limitations-${turnId}`}>Limitations</h3><ul>{result.evidence_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul></section>}
    {isAssistant && researched && !deferDetails && <ConversationEvidenceDetails content={content} result={result} turnId={turnId} onEvidence={onEvidence} onPaper={onPaper} isAdmin={isAdmin} activePmids={activePmids} citedPmids={citedPmids} retrievedPapers={retrievedPapers} evidenceRows={evidenceRows} />}
  </article>;
}
