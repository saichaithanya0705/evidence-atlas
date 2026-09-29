import Icon from "./Icon.jsx";
import { getCitationPmids, pubmedUrl } from "../utils.js";

export function renderCitations(text, onEvidence) {
  const parts = [];
  const pattern = /\[?PMID:\s*(\d+)\]?/gi;
  let previousEnd = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > previousEnd) parts.push(text.slice(previousEnd, match.index));
    const pmid = match[1];
    parts.push(
      onEvidence ? <button className="citation-link citation-button" type="button" key={match.index} onClick={() => onEvidence([pmid])}>PMID: {pmid}</button> : <a className="citation-link" href={pubmedUrl(pmid)} target="_blank" rel="noreferrer" key={match.index}>PMID: {pmid}</a>,
    );
    previousEnd = pattern.lastIndex;
  }
  if (previousEnd < text.length) parts.push(text.slice(previousEnd));
  return parts;
}

function uncertaintyText(research) {
  if (research.citations_valid === false) {
    return "Citation validation flagged this synthesis. Verify every linked source before relying on the summary.";
  }
  if (research.consensus_level === "insufficient") {
    return "The returned evidence was insufficient to support a reliable conclusion.";
  }
  if (research.consensus_level === "conflicting") {
    return "The included studies report conflicting findings. Review the source evidence before drawing a conclusion.";
  }
  if (research.consensus_level === "mixed") {
    return "Findings vary across the included studies; the synthesis may not capture every source-level difference.";
  }
  if (research.evidence_gaps?.length) {
    return "Evidence gaps were reported for this question. Interpret the synthesis with caution.";
  }
  return "This evidence summary does not replace review of the original studies or clinical judgment.";
}

export default function SynthesisPanel({ research, onTraceEvidence, isAdmin, loading, error }) {
  const synthesis = research?.synthesis || "";
  const paragraphs = synthesis.split(/\n\s*\n/).filter(Boolean);
  const pmids = getCitationPmids(synthesis);
  const cautious = research && (
    research.consensus_level !== "consensus"
    || research.citations_valid === false
    || (research.evidence_gaps || []).length > 0
  );

  return (
    <section className="panel synthesis-panel" aria-labelledby="synthesis-heading">
      <div className="panel-heading synthesis-heading">
        <h2 id="synthesis-heading"><Icon name="file" size={19} /> Evidence synthesis</h2>
        {research && isAdmin ? (
          <span className={"consensus-label consensus-" + research.consensus_level}>
            {research.consensus_level || "Evidence summary"}
          </span>
        ) : <span className="subtle-label">Research synthesis</span>}
      </div>
      {loading ? <div className="synthesis-loading" role="status">
        <span className="large-spinner" />
        <h3>Building an evidence-grounded answer</h3>
        <p>Retrieving sources and reviewing their findings. This may take a little time.</p>
        <div className="reading-skeleton" aria-hidden="true"><i /><i /><i /></div>
      </div> : error ? <div className="synthesis-empty"><h3>Let’s try that again</h3><p>No synthesis was produced. Review the message above and retry your question.</p></div> : !research ? (
        <div className="synthesis-empty">
          <h3>From question to understanding</h3>
          <ol className="research-steps">
            <li><strong>Ask a focused question</strong><p>Start with a population, treatment, or outcome you want to explore.</p></li>
            <li><strong>Compare the sources</strong><p>Explore ranked abstracts and the studies behind the synthesis.</p></li>
            <li><strong>Read with context</strong><p>Check original findings, study designs, and limitations before drawing conclusions.</p></li>
          </ol>
        </div>
      ) : (
        <>
          {isAdmin && cautious && (
            <div className="uncertainty-banner" role="status">
              <Icon name="alert" size={19} />
              <div>
                <strong>Interpret findings with care</strong>
                <p>{uncertaintyText(research)}</p>
                {(research.evidence_gaps || []).length > 0 && (
                  <ul>{research.evidence_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>
                )}
              </div>
            </div>
          )}
          {synthesis ? (
            <div className="synthesis-copy">
              {paragraphs.map((paragraph, index) => {
                const paragraphPmids = [...new Set(getCitationPmids(paragraph))];
                return (
                  <div className="synthesis-claim" key={index}>
                    <p>{renderCitations(paragraph, onTraceEvidence)}</p>
                    {isAdmin && paragraphPmids.length > 0 && (
                      <button
                        className="trace-claim-button"
                        type="button"
                        onClick={() => onTraceEvidence(paragraphPmids)}
                      >
                        Trace claim to source evidence <Icon name="arrow" size={14} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="inline-state">The research service returned no synthesis text.</div>
          )}
          {pmids.length > 0 && (
            <p className="synthesis-footnote">
              {new Set(pmids).size} cited source{new Set(pmids).size === 1 ? "" : "s"} returned
                {isAdmin && research.citation_precision !== undefined && research.citation_precision !== null
                ? " · Citation precision " + Math.round(Number(research.citation_precision) * 100) + "%"
                : ""}
              . Original abstracts remain the source of record.
            </p>
          )}
        </>
      )}
    </section>
  );
}
