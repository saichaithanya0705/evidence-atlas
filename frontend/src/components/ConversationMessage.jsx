import { useCallback, useState } from "react";
import { getTrace } from "../api.js";
import { exportPublicResearchJson, exportResearchJson } from "../utils.js";
import AuditTrail from "./AuditTrail.jsx";
import EvidenceTable from "./EvidenceTable.jsx";
import InterpretationPanel from "./InterpretationPanel.jsx";
import { renderCitations } from "./SynthesisPanel.jsx";

function RetrievedSources({ papers, onSelect }) {
  if (!papers.length) return null;
  return <section className="message-papers" aria-label="Related source papers">
    <h3>Related source papers</h3>
    <ul>{papers.map(paper => <li key={String(paper.pmid)}>
      <button type="button" className="source-title-button" onClick={() => onSelect(paper)}>{paper.title || `PMID ${paper.pmid}`}</button>
      <button type="button" className="source-pmid-button" onClick={() => onSelect(paper)}>PMID: {paper.pmid}</button>
      <span>{[paper.year, paper.study_type, paper.journal].filter(Boolean).join(" · ")}</span>
    </li>)}</ul>
  </section>;
}

export default function ConversationMessage({ role, content, status, action, result, turnId, onEvidence, onPaper, isAdmin = false, activePmids = [] }) {
  const [audit, setAudit] = useState({ trace: null, loading: false, error: "" });
  const isAssistant = role === "assistant";
  const failed = status === "FAILED";
  const insufficient = status === "INSUFFICIENT";
  const researched = action !== "CLARIFY" && action !== "ABSTAIN";

  const openEvidence = useCallback((pmid, target = {}) => onEvidence?.(pmid, { turnId, ...target }), [onEvidence, turnId]);
  const openCitations = useCallback(pmids => pmids.forEach(pmid => openEvidence(pmid)), [openEvidence]);
  const selectPaper = useCallback(paper => onPaper?.(paper, { turnId }), [onPaper, turnId]);
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

  const evidenceRows = result?.evidence_table || [];
  const safeExport = useCallback(() => {
    const exportPayload = {
      query: result?.query,
      synthesis: content,
      cited_pmids: result?.cited_pmids || [],
      consensus_level: result?.consensus_level,
      evidence_gaps: result?.evidence_gaps || [],
      retrieved_papers: (result?.retrieved_papers || []).map(paper => ({
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
    if (!isAdmin) {
      exportPublicResearchJson(exportPayload);
      return;
    }
    exportResearchJson({ ...exportPayload, request_id: result?.request_id }, audit.trace);
  }, [audit.trace, content, evidenceRows, isAdmin, result]);

  return <article className={`conversation-message conversation-${role}${failed ? " conversation-failed" : ""}`}>
    <div className="conversation-message-heading"><strong>{isAssistant ? "Evidence Atlas" : "You"}</strong>{action === "ABSTAIN" && <span className="answer-status insufficient">ABSTAIN</span>}{status && researched && <span className={failed ? "answer-status failed" : insufficient ? "answer-status insufficient" : "answer-status"}>{status}</span>}</div>
    <p>{isAssistant ? renderCitations(content || "", openCitations) : content}</p>
    {failed && <p className="message-context">A technical failure prevented this turn from completing. This is not a finding about the evidence.</p>}
    {insufficient && researched && <p className="message-context">The available evidence did not establish a reliable answer. Review the original papers and noted gaps.</p>}
    {researched && result?.evidence_gaps?.length > 0 && <div className="message-context"><strong>Evidence gaps</strong><ul>{result.evidence_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul></div>}
    {isAssistant && researched && result?.interpretation && <InterpretationPanel interpretation={result.interpretation} isAdmin={isAdmin} />}
    {isAssistant && researched && evidenceRows.length > 0 && <EvidenceTable rows={evidenceRows} activePmids={activePmids} turnId={turnId} coverageStatuses={result?.interpretation?.coverage_statuses || []} onTraceEvidence={openEvidence} onExportJson={safeExport} />}
    {isAssistant && isAdmin && result?.request_id && <AuditTrail research={result} trace={audit.trace} loading={audit.loading} error={audit.error} onLoad={loadAudit} onExport={safeExport} />}
    {isAssistant && researched && <RetrievedSources papers={result?.retrieved_papers || []} onSelect={selectPaper} />}
  </article>;
}
