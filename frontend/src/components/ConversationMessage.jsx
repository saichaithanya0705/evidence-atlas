import RankedPapers from "./RankedPapers.jsx";
import { renderCitations } from "./SynthesisPanel.jsx";

export default function ConversationMessage({ role, content, status, action, result, onEvidence, onPaper }) {
  const isAssistant = role === "assistant";
  const failed = status === "FAILED";
  const insufficient = status === "INSUFFICIENT";
  return <article className={`conversation-message conversation-${role}${failed ? " conversation-failed" : ""}`}>
    <div className="conversation-message-heading"><strong>{isAssistant ? "Evidence Atlas" : "You"}</strong>{status && action !== "CLARIFY" && <span className={failed ? "answer-status failed" : insufficient ? "answer-status insufficient" : "answer-status"}>{status}</span>}</div>
    <p>{isAssistant ? renderCitations(content || "", onEvidence ? pmids => pmids.forEach(onEvidence) : undefined) : content}</p>
    {failed && <p className="message-context">A technical failure prevented this turn from completing. This is not a finding about the evidence.</p>}
    {insufficient && <p className="message-context">The available evidence did not establish a reliable answer. Review the original papers and noted gaps.</p>}
    {result?.evidence_gaps?.length > 0 && <div className="message-context"><strong>Evidence gaps</strong><ul>{result.evidence_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul></div>}
    {result?.evidence_table?.length > 0 && <section className="message-evidence" aria-label="Evidence from cited papers">
      <h3>Evidence from cited papers</h3>
      {result.evidence_table.map((row, index) => <article key={`${row.pmid}-${index}`}>
        <button type="button" onClick={() => onEvidence?.(row.pmid)}>PMID: {row.pmid} · {row.title}</button>
        <p>{row.key_findings}</p>
        {row.limitations && <p className="message-context">Limitations: {row.limitations}</p>}
        {row.supporting_text_spans?.map((span, spanIndex) => <blockquote key={spanIndex}>{span}</blockquote>)}
      </article>)}
    </section>}
    {result?.retrieved_papers?.length > 0 && <div className="message-papers"><RankedPapers papers={result.retrieved_papers} total={result.retrieved_papers.length} selectedPmid={null} onSelect={onPaper} onSourceSelect={onPaper} loading={false} hasSearched isAdmin={false} />{result.cited_pmids?.length > 0 && <p>Inspect the original papers before drawing conclusions.</p>}</div>}
  </article>;
}
