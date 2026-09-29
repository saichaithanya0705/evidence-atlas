import { useMemo, useState } from "react";
import Icon from "./Icon.jsx";
import Modal from "./Modal.jsx";
import { formatScore, formatValue, pubmedUrl } from "../utils.js";

const tabs = ["Overview", "Evidence", "Provenance", "Related"];
const channels = [
  { label: "Dense", keys: ["dense", "vector", "medcpt", "dense_similarity"] },
  { label: "BM25", keys: ["bm25", "sparse", "lexical"] },
  { label: "Graph", keys: ["graph", "mesh_graph", "graph_retrieval"] },
];

function readChannel(values, keys) {
  const entries = Object.entries(values || {});
  const found = entries.find(([key]) => keys.includes(key.toLowerCase()));
  return found ? found[1] : undefined;
}

function PaperOverview({ paper, loadError }) {
  const abstract = paper.abstract || "";
  return (
    <div className="drawer-tab-content">
      {loadError && (
        <p className="detail-warning" role="status">
          Full paper details could not be loaded. Showing the fields returned with this ranked result.
        </p>
      )}
      <h3>Abstract</h3>
      <p className="drawer-abstract">{formatValue(abstract, "No abstract was returned.")}</p>
      <h3>Key details</h3>
      <dl className="paper-details">
        <div><dt>Journal</dt><dd>{formatValue(paper.journal)}</dd></div>
        <div><dt>Publication date</dt><dd>{formatValue(paper.publication_date || paper.year)}</dd></div>
        <div><dt>Study design</dt><dd>{formatValue(paper.study_type)}</dd></div>
        <div><dt>Authors</dt><dd>{formatValue(paper.authors)}</dd></div>
        <div><dt>MeSH terms</dt><dd>{formatValue(paper.mesh_terms)}</dd></div>
        <div><dt>Keywords</dt><dd>{formatValue(paper.keywords)}</dd></div>
      </dl>
    </div>
  );
}

function PaperEvidence({ paper, evidence, active }) {
  const row = evidence.find((item) => String(item.pmid) === String(paper.pmid));
  if (!row) {
    return (
      <div className="drawer-tab-content">
        <div className="inline-state">No structured evidence record was returned for PMID {paper.pmid}.</div>
      </div>
    );
  }
  return (
    <div className="drawer-tab-content">
      <h3>Extracted finding</h3>
      <p>{formatValue(row.key_findings)}</p>
      <h3>Supporting spans from the abstract</h3>
      {(row.supporting_text_spans || []).length ? (
        <ul className="drawer-spans">
          {row.supporting_text_spans.map((span, index) => (
            <li className={active ? "span-highlight" : ""} key={index}>{span}</li>
          ))}
        </ul>
      ) : <p className="drawer-muted">The API returned no supporting text spans for this evidence record.</p>}
      <dl className="paper-details">
        <div><dt>Outcome</dt><dd>{formatValue(row.outcome)}</dd></div>
        <div><dt>Limitations</dt><dd>{formatValue(row.limitations)}</dd></div>
      </dl>
    </div>
  );
}

function PaperProvenance({ paper }) {
  const scores = paper.channel_scores || {};
  const ranks = paper.channel_ranks || {};
  const rows = channels.map((channel) => ({
    ...channel,
    score: readChannel(scores, channel.keys),
    rank: readChannel(ranks, channel.keys),
  }));
  rows.push({ label: "RRF fusion", score: paper.rrf_score, rank: undefined });
  rows.push({ label: "MedCPT reranker", score: paper.reranker_score, rank: undefined });
  const unknownScores = Object.entries(scores).filter(([key]) =>
    !channels.some((channel) => channel.keys.includes(key.toLowerCase())),
  );

  return (
    <div className="drawer-tab-content">
      <p className="provenance-intro">Scores and ranks below are the values returned by the retrieval service.</p>
      <div className="score-list">
        {rows.map((row) => (
          <div className="score-row" key={row.label}>
            <span>{row.label}</span>
            <strong>{formatScore(row.score)}</strong>
            <small>{row.rank === undefined ? "Rank not returned" : "Rank " + row.rank}</small>
          </div>
        ))}
        {unknownScores.map(([key, value]) => (
          <div className="score-row" key={key}>
            <span>{key}</span>
            <strong>{formatScore(value)}</strong>
            <small>{formatValue(ranks[key], "Rank not returned")}</small>
          </div>
        ))}
      </div>
      <div className={"filter-verdict " + (paper.filter_satisfied === false ? "filter-failed" : "")}>
        <Icon name={paper.filter_satisfied === false ? "alert" : "check"} size={16} />
        <span>{paper.filter_satisfied === false ? "One or more filters were not satisfied" : "Metadata filters satisfied"}</span>
      </div>
      <h3>Graph path</h3>
      {paper.graph_path?.length
        ? <ol className="graph-path">{paper.graph_path.map((term, index) => <li key={index}>{term}</li>)}</ol>
        : <p className="drawer-muted">No graph path was returned for this paper.</p>}
    </div>
  );
}

function RelatedPapers({ paper, papers, onSelect }) {
  const related = useMemo(() => {
    const terms = new Set((paper.mesh_terms || []).map((term) => term.toLowerCase()));
    if (!terms.size) return [];
    return papers
      .filter((candidate) => candidate.pmid !== paper.pmid)
      .map((candidate) => ({
        candidate,
        shared: (candidate.mesh_terms || []).filter((term) => terms.has(term.toLowerCase())),
      }))
      .filter((item) => item.shared.length)
      .sort((left, right) => right.shared.length - left.shared.length)
      .slice(0, 6);
  }, [paper, papers]);

  return (
    <div className="drawer-tab-content">
      <p className="provenance-intro">Related papers are matched by shared MeSH terms in the current result set.</p>
      {related.length ? related.map(({ candidate, shared }) => (
        <button className="related-paper" type="button" key={candidate.pmid} onClick={() => onSelect(candidate)}>
          <strong>{candidate.title}</strong>
          <span>PMID: {candidate.pmid} · {shared.join(", ")}</span>
        </button>
      )) : <p className="drawer-muted">No related papers with shared MeSH terms were returned in this result set.</p>}
    </div>
  );
}

export default function PaperDrawer({
  selectedPaper,
  paperDetails,
  detailLoading,
  detailError,
  evidence,
  papers,
  active,
  onSelect,
  onClose,
  isAdmin,
}) {
  const [activeTab, setActiveTab] = useState("Overview");

  if (!selectedPaper) {
    return null;
  }

  const paper = { ...selectedPaper, ...paperDetails };
  return (
    <Modal
      className="panel paper-drawer"
      label={"Selected paper details for PMID " + selectedPaper.pmid}
      onClose={onClose}
    >
      <div className="panel-heading drawer-heading">
        <h2><Icon name="file" size={19} /> Selected paper</h2>
        <button className="icon-button drawer-close" type="button" aria-label="Close selected paper details" onClick={onClose}>
          <Icon name="close" size={18} />
        </button>
      </div>
      <div className="drawer-scroll">
        <h3 className="drawer-paper-title">{formatValue(paper.title, "Untitled paper")}</h3>
        <div className="drawer-metadata">
          <span>PMID: <a href={pubmedUrl(paper.pmid)} target="_blank" rel="noreferrer">{paper.pmid}</a></span>
          <span>{formatValue(paper.year || paper.publication_date)}</span>
          <span>{formatValue(paper.study_type)}</span>
        </div>
        <div className="drawer-actions">
          <a href={pubmedUrl(paper.pmid)} target="_blank" rel="noreferrer"><Icon name="external" size={15} /> View on PubMed</a>
          {paper.doi && (
            <a href={"https://doi.org/" + encodeURIComponent(paper.doi)} target="_blank" rel="noreferrer">
              <Icon name="external" size={15} /> Publisher DOI
            </a>
          )}
        </div>
        <div className="drawer-tabs" role="group" aria-label="Selected paper views">
          {(isAdmin ? tabs : ["Overview"]).map((tab) => (
            <button
              key={tab}
              type="button"
              aria-pressed={activeTab === tab}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>
        {detailLoading && <div className="detail-loading" role="status"><span className="button-spinner" /> Loading full paper record</div>}
        {activeTab === "Overview" && <PaperOverview paper={paper} loadError={detailError} />}
        {isAdmin && activeTab === "Evidence" && <PaperEvidence paper={paper} evidence={evidence} active={active} />}
        {isAdmin && activeTab === "Provenance" && <PaperProvenance paper={paper} />}
        {isAdmin && activeTab === "Related" && <RelatedPapers paper={paper} papers={papers} onSelect={onSelect} />}
      </div>
    </Modal>
  );
}
