import Icon from "./Icon.jsx";
import { exportEvidenceCsv, formatValue } from "../utils.js";

const coverageLabels = {
  COVERED: "Covered",
  PARTIAL: "Partially covered",
  UNCOVERED: "Not covered",
  BLOCKED: "Could not assess",
};

export default function EvidenceTable({
  rows = [],
  activePmids = [],
  onTraceEvidence = () => {},
  turnId,
  coverageStatuses = [],
  hasSearched = true,
  onExportJson = () => {},
}) {
  const coverageById = new Map(coverageStatuses.map(item => [item.subquestion_id, item.status]));
  const headingId = `evidence-heading-${encodeURIComponent(turnId || "unknown")}`;
  return (
    <section className="panel evidence-panel" aria-labelledby={headingId}>
      <div className="panel-heading evidence-heading">
        <h2 id={headingId}><Icon name="layers" size={19} /> Evidence from cited papers</h2>
        <div className="evidence-tools">
          <span>{rows.length ? `Showing ${rows.length} studies` : "Evidence comparison"}</span>
          <button className="text-icon-button" type="button" disabled={!rows.length} onClick={() => exportEvidenceCsv(rows)}>
            <Icon name="download" size={16} /> Export CSV
          </button>
          <button className="text-icon-button" type="button" disabled={!rows.length} onClick={onExportJson}>
            <Icon name="file" size={15} /> JSON
          </button>
        </div>
      </div>
      {rows.length ? (
        <div className="table-scroll" tabIndex="0" aria-label="Evidence table. Scroll horizontally to see all columns.">
          <table className="evidence-table">
            <thead><tr>
              <th scope="col">Study</th>
              <th scope="col">Design</th>
              <th scope="col">Population</th>
              <th scope="col">Intervention / comparator</th>
              <th scope="col">Outcome / key finding</th>
              <th scope="col">Retrieval channels</th>
              <th scope="col">Subquestion coverage</th>
              <th scope="col">Exact supporting spans</th>
            </tr></thead>
            <tbody>{rows.map((row, index) => {
              const pmid = String(row.pmid);
              const active = activePmids.includes(pmid);
              const spans = row.supporting_text_spans || [];
              const channels = row.retrieval_channels || [];
              const subquestionIds = row.subquestion_ids || [];
              return (
                <tr key={`${pmid}-${index}`} className={active ? "evidence-row-active" : ""}>
                  <td className="study-cell">
                    <button className="evidence-study-link" type="button" onClick={() => onTraceEvidence(pmid, { turnId, evidenceId: `${turnId}:${index}`, evidenceRecord: row })}>PMID: {pmid}</button>
                    <span>{formatValue(row.title, "Untitled study")}</span>
                  </td>
                  <td>{formatValue(row.study_design)}</td>
                  <td>{formatValue(row.population)}</td>
                  <td><strong>{formatValue(row.intervention)}</strong><span className="table-secondary">vs {formatValue(row.comparator)}</span></td>
                  <td><strong>{formatValue(row.outcome)}</strong><span className="table-secondary">{formatValue(row.key_findings)}</span></td>
                  <td>{channels.length ? channels.map(channel => <span className="qualitative-chip" key={channel}>{channel}</span>) : <span className="table-secondary">Not returned</span>}</td>
                  <td>{subquestionIds.length ? subquestionIds.map(id => (
                    <span className="coverage-chip" key={id}>
                      <span>{id}</span>
                      <strong>{coverageLabels[coverageById.get(id)] || "Status not returned"}</strong>
                    </span>
                  )) : <span className="table-secondary">Not linked to a planned subquestion</span>}</td>
                  <td className="span-cell">{spans.length ? (
                    <div className="evidence-spans">{spans.map((span, spanIndex) => (
                      <button className="evidence-span" type="button" key={spanIndex} onClick={() => onTraceEvidence(pmid, { turnId, evidenceId: `${turnId}:${index}:${spanIndex}`, spanText: span, evidenceRecord: row })}>
                        “{span}”
                      </button>
                    ))}</div>
                  ) : <span className="table-secondary">No supporting span returned.</span>}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      ) : (
        <div className="table-empty">{hasSearched ? "The service returned no structured evidence records for this run." : "Study-level findings and source spans will appear here after a search."}</div>
      )}
      {rows.length > 0 && <div className="evidence-legend"><span><i className="legend-dot legend-active" />Highlighted source</span><span>Choose a source or exact span to inspect that paper</span></div>}
    </section>
  );
}
