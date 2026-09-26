import Icon from "./Icon.jsx";
import { exportEvidenceCsv, formatValue, pubmedUrl } from "../utils.js";

export default function EvidenceTable({
  rows,
  activePmids,
  onTraceEvidence,
  hasSearched,
  onExportJson,
}) {
  return (
    <section className="panel evidence-panel" aria-labelledby="evidence-heading">
      <div className="panel-heading evidence-heading">
        <h2 id="evidence-heading"><Icon name="layers" size={19} /> Cross-study evidence</h2>
        <div className="evidence-tools">
          <span>{rows.length ? "Showing " + rows.length + " studies" : "Evidence comparison"}</span>
          <button
            className="text-icon-button"
            type="button"
            disabled={!rows.length}
            onClick={() => exportEvidenceCsv(rows)}
          >
            <Icon name="download" size={16} /> Export CSV
          </button>
          <button
            className="text-icon-button"
            type="button"
            disabled={!rows.length}
            onClick={onExportJson}
          >
            <Icon name="file" size={15} /> JSON
          </button>
        </div>
      </div>
      {rows.length ? (
        <div className="table-scroll" tabIndex="0" aria-label="Cross-study evidence table. Scroll horizontally to see all columns.">
          <table>
            <thead>
              <tr>
                <th scope="col">Study</th>
                <th scope="col">Design</th>
                <th scope="col">Population</th>
                <th scope="col">Intervention / comparator</th>
                <th scope="col">Outcome / key finding</th>
                <th scope="col">Supporting evidence spans</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const active = activePmids.includes(String(row.pmid));
                const spans = row.supporting_text_spans || [];
                return (
                  <tr key={String(row.pmid) + "-" + index} className={active ? "evidence-row-active" : ""}>
                    <td className="study-cell">
                      <a href={pubmedUrl(row.pmid)} target="_blank" rel="noreferrer">
                        PMID: {row.pmid}
                      </a>
                      <span>{formatValue(row.title, "Untitled study")}</span>
                    </td>
                    <td>{formatValue(row.study_design)}</td>
                    <td>{formatValue(row.population)}</td>
                    <td>
                      <strong>{formatValue(row.intervention)}</strong>
                      <span className="table-secondary">vs {formatValue(row.comparator)}</span>
                    </td>
                    <td>
                      <strong>{formatValue(row.outcome)}</strong>
                      <span className="table-secondary">{formatValue(row.key_findings)}</span>
                    </td>
                    <td className="span-cell">
                      {spans.length ? (
                        <div className="evidence-spans">
                          {spans.map((span, spanIndex) => (
                            <button
                              className="evidence-span"
                              type="button"
                              key={spanIndex}
                              onClick={() => onTraceEvidence([String(row.pmid)])}
                            >
                              “{span}”
                            </button>
                          ))}
                        </div>
                      ) : <span className="table-secondary">No supporting span returned.</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-empty">
          {hasSearched
            ? "The service returned no structured evidence records for this run."
            : "Study-level findings and source spans will appear here after a search."}
        </div>
      )}
      {rows.length > 0 && (
        <div className="evidence-legend">
          <span><i className="legend-dot legend-active" />Highlighted source</span>
          <span>Click a quoted span to inspect that paper</span>
        </div>
      )}
    </section>
  );
}
