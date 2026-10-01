import { useEffect, useState } from "react";
import Icon from "./Icon.jsx";
import { formatScore, formatValue, pubmedUrl } from "../utils.js";
import { metadataText } from "../paperDetails.js";

const channels = [
  { label: "Dense", keys: ["dense", "vector", "medcpt", "dense_similarity"] },
  { label: "BM25", keys: ["bm25", "sparse", "lexical"] },
  { label: "Graph", keys: ["graph", "mesh_graph", "graph_retrieval"] },
];
function readChannel(values, keys) {
  const entry = Object.entries(values || {}).find(([key]) => keys.includes(key.toLowerCase()));
  return entry?.[1];
}

export default function EvidencePaperTab({ tab, loadPaperDetails }) {
  const [details, setDetails] = useState({ status: "loading", metadata: null, errorStatus: null });
  const [retryAttempt, setRetryAttempt] = useState(0);
  const pmid = tab.paper?.pmid;
  useEffect(() => {
    let active = true;
    setDetails({ status: "loading", metadata: null, errorStatus: null });
    loadPaperDetails(pmid).then(metadata => {
      if (active) setDetails({ status: "loaded", metadata, errorStatus: null });
    }).catch(error => {
      if (active) setDetails({ status: "error", metadata: null, errorStatus: error?.status });
    });
    // A late response must not replace metadata in a different selected tab.
    return () => { active = false; };
  }, [pmid, loadPaperDetails, retryAttempt]);
  const paper = { ...(tab.paper || {}), ...(details.metadata || {}) };
  const spans = [];
  for (const reference of tab.references || []) if (reference.spanText && !spans.includes(reference.spanText)) spans.push(reference.spanText);
  for (const row of paper.evidenceRecords || []) for (const span of row.supporting_text_spans || []) if (!spans.includes(span)) spans.push(span);
  const scores = paper.channel_scores || {};
  const ranks = paper.channel_ranks || {};
  const scoreRows = channels.map(channel => ({ label: channel.label, score: readChannel(scores, channel.keys), rank: readChannel(ranks, channel.keys) }));
  scoreRows.push({ label: "RRF fusion", score: paper.rrf_score });
  scoreRows.push({ label: "MedCPT reranker", score: paper.reranker_score });
  const unknownScores = Object.entries(scores).filter(([key]) => !channels.some(channel => channel.keys.includes(key.toLowerCase())));

  return <div className="evidence-paper-content">
    {details.status === "loading" && <p className="inline-state" role="status">Loading full paper metadata…</p>}
    {details.status === "error" && <div className="detail-warning" role="alert">Paper details could not be loaded. This tab remains open; the available conversation record is shown below. <button type="button" onClick={() => setRetryAttempt(current => current + 1)}>Retry paper details</button></div>}
    {(paper.sessionExpired || details.errorStatus === 401) && <div className="detail-warning" role="status">Your session expired. Sign in again to load additional paper details; this evidence tab is preserved.</div>}
    <h2 className="drawer-paper-title">{formatValue(paper.title, `PMID ${paper.pmid}`)}</h2>
    <div className="drawer-metadata"><span>PMID: {paper.pmid}</span><span>{formatValue(paper.year || paper.publication_date)}</span><span>{formatValue(paper.study_type)}</span><span>{formatValue(paper.journal)}</span></div>
    <div className="drawer-actions">
      <a href={pubmedUrl(paper.pmid)} target="_blank" rel="noopener noreferrer"><Icon name="external" size={15} /> View on PubMed</a>
      {paper.doi && <a href={`https://doi.org/${encodeURIComponent(paper.doi)}`} target="_blank" rel="noopener noreferrer"><Icon name="external" size={15} /> Publisher DOI</a>}
    </div>
    {paper.empty && <p className="inline-state" role="status">No additional paper details were returned. The selected source stays available in this workspace.</p>}
    <section className="paper-section"><h3>Abstract</h3><p className="drawer-abstract">{formatValue(paper.abstract, "No abstract was returned.")}</p></section>
    <section className="paper-section"><h3>Study details</h3><dl className="paper-details">
      <div><dt>Authors</dt><dd>{formatValue(paper.authors)}</dd></div><div><dt>Journal</dt><dd>{formatValue(paper.journal)}</dd></div><div><dt>Year</dt><dd>{formatValue(paper.publication_date || paper.year)}</dd></div><div><dt>Study type</dt><dd>{formatValue(paper.study_type)}</dd></div><div><dt>MeSH terms</dt><dd>{metadataText(paper.mesh_terms, details.status)}</dd></div><div><dt>Keywords</dt><dd>{metadataText(paper.keywords, details.status)}</dd></div>
    </dl></section>
    {(paper.evidenceRecords || []).length > 0 && <section className="paper-section"><h3>Extracted findings</h3>{paper.evidenceRecords.map((record, index) => <article className="paper-finding" key={`${record.pmid}-${index}`}><p>{formatValue(record.key_findings, "No finding text was returned.")}</p><dl className="paper-details"><div><dt>Outcome</dt><dd>{formatValue(record.outcome)}</dd></div><div><dt>Limitations</dt><dd>{formatValue(record.limitations)}</dd></div></dl></article>)}</section>}
    <section className="paper-section"><h3>Supporting spans used in this conversation</h3>
      {spans.length ? <ul className="drawer-spans">{spans.map((span, index) => <li key={`${index}-${span}`} data-evidence-span className={span === tab.selectedSpan ? "is-highlighted" : ""} ref={node => { if (node && span === tab.selectedSpan) node.scrollIntoView({ block: "nearest", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); }}>{span}</li>)}</ul> : <p className="drawer-muted">No supporting text span has been selected yet.</p>}
      <h3>Conversation turns</h3>
      {(tab.references || []).filter(reference => reference.turnId).length ? <ol className="turn-references">{[...new Set(tab.references.map(reference => reference.turnId).filter(Boolean))].map(id => <li key={id}>{id}</li>)}</ol> : <p className="drawer-muted">This paper has no linked turn reference.</p>}
    </section>
    {(paper.channel_scores || paper.graph_path || paper.filter_satisfied !== undefined) && <section className="paper-section"><h3>Retrieval provenance</h3><p className="provenance-intro">Scores and ranks below are the values returned by the retrieval service.</p><div className="score-list">
      {scoreRows.map(row => <div className="score-row" key={row.label}><span>{row.label}</span><strong>{formatScore(row.score)}</strong><small>{row.rank === undefined ? "Rank not returned" : `Rank ${row.rank}`}</small></div>)}
      {unknownScores.map(([key, value]) => <div className="score-row" key={key}><span>{key}</span><strong>{formatScore(value)}</strong><small>{formatValue(ranks[key], "Rank not returned")}</small></div>)}
    </div><div className={`filter-verdict ${paper.filter_satisfied === false ? "filter-failed" : ""}`}><Icon name={paper.filter_satisfied === false ? "alert" : "check"} size={16} /><span>{paper.filter_satisfied === false ? "One or more filters were not satisfied" : "Metadata filters satisfied"}</span></div>
      <h3>Graph path</h3>{paper.graph_path?.length ? <ol className="graph-path">{paper.graph_path.map((term, index) => <li key={index}>{term}</li>)}</ol> : <p className="drawer-muted">No graph path was returned for this paper.</p>}
    </section>}
  </div>;
}
