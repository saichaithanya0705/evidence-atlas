import Icon from "./Icon.jsx";
import { formatValue, pubmedUrl } from "../utils.js";

function PaperRow({ paper, index, selected, onSelect, isAdmin }) {
  const authors = paper.authors || [];
  const authorsText = authors.length > 3
    ? authors.slice(0, 3).join(", ") + " et al."
    : formatValue(authors);
  const mesh = paper.mesh_terms || [];

  return (
    <article className={"paper-row" + (selected ? " is-selected" : "")}>
      <span className="paper-rank" aria-label={"Rank " + (index + 1)}>{index + 1}</span>
      <div className="paper-row-content">
        <button
          className="paper-title-button"
          type="button"
          aria-pressed={selected}
          onClick={() => onSelect(paper)}
        >
          {formatValue(paper.title, "Untitled paper")}
        </button>
        <div className="paper-meta">
          <span>{formatValue(paper.year)}</span>
          <span>{formatValue(paper.study_type)}</span>
          {paper.journal && <span>{paper.journal}</span>}
        </div>
        <p className="paper-authors">{authorsText}</p>
        <p className="paper-abstract">{formatValue(paper.abstract, "No abstract was returned.")}</p>
        {mesh.length > 0 && (
          <p className="paper-mesh"><strong>MeSH</strong> {mesh.slice(0, 4).join(" · ")}</p>
        )}
        <div className="paper-row-links">
          <a href={pubmedUrl(paper.pmid)} target="_blank" rel="noreferrer">
            PMID: {paper.pmid} <Icon name="external" size={13} />
          </a>
          {isAdmin && <button type="button" onClick={() => onSelect(paper)}>Why this paper?</button>}
        </div>
      </div>
    </article>
  );
}

export default function RankedPapers({
  papers,
  total,
  selectedPmid,
  onSelect,
  loading,
  hasSearched,
  isAdmin,
  error,
}) {
  return (
    <section className="panel ranked-panel" aria-labelledby="ranked-heading">
      <div className="panel-heading">
        <h2 id="ranked-heading"><Icon name="file" size={19} /> Ranked papers</h2>
        {hasSearched && papers.length > 0 && (
          <span className="result-count">
            {papers.length} shown{Number.isFinite(Number(total)) ? " of " + total : ""}
          </span>
        )}
      </div>
      <div className="ranked-list" aria-live="polite">
        {loading ? (
          <div className="results-state" role="status">
            <span className="large-spinner" />
            <strong>Retrieving and reviewing evidence</strong>
            <span>The service is processing this research question.</span>
          </div>
        ) : error ? (
          <div className="results-state"><Icon name="alert" size={28} /><strong>Sources could not be loaded</strong><span>This is a request failure, not a finding of no evidence.</span></div>
        ) : papers.length ? (
          papers.map((paper, index) => (
            <PaperRow
              key={paper.pmid}
              paper={paper}
              index={index}
              selected={paper.pmid === selectedPmid}
              onSelect={onSelect}
              isAdmin={isAdmin}
            />
          ))
        ) : hasSearched ? (
          <div className="results-state">
            <Icon name="search" size={25} />
            <strong>No papers matched these filters</strong>
            <span>Try a broader year range or study type, then research again.</span>
          </div>
        ) : (
          <div className="results-state">
            <Icon name="book" size={25} />
            <strong>Your reading list starts here</strong>
            <span>Ask a research question to find and compare relevant papers. Select a source to read its abstract in context.</span>
          </div>
        )}
      </div>
    </section>
  );
}
