import { useState } from "react";
import Icon from "./Icon.jsx";
import { formatValue } from "../utils.js";
import { normalizeTraceIteration } from "../auditTrace.js";

function SummaryField({ label, value }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="audit-summary-field">
      <span>{label}</span>
      <strong>{Array.isArray(value) ? formatValue(value) : String(value)}</strong>
    </div>
  );
}

function IterationCard({ item, index }) {
  const normalized = normalizeTraceIteration(item);
  const iteration = normalized.iteration === undefined ? index + 1 : normalized.iteration + 1;
  const subqueries = normalized.queries;
  const pmids = normalized.pmids;
  const channel = normalized.channels;
  return (
    <article className="audit-iteration">
      <strong>Retrieval attempt {iteration}</strong>
      {subqueries.length > 0 && <p><span>Queries:</span> {formatValue(subqueries)}</p>}
      {channel.length > 0 && <p><span>Channels:</span> {formatValue(channel)}</p>}
      {pmids.length > 0 && <p><span>Evidence PMIDs:</span> {formatValue(pmids)}</p>}
      {normalized.grade && <p><span>Evidence grade:</span> {normalized.grade}</p>}
      {item.reason && <p><span>Trigger:</span> {item.reason}</p>}
      {item.corrective_search && <p><span>Corrective search:</span> {String(item.corrective_search)}</p>}
      {!subqueries.length && !pmids.length && !channel.length && !item.reason && !item.corrective_search && (
        <pre>{JSON.stringify(item, null, 2)}</pre>
      )}
    </article>
  );
}

export default function AuditTrail({
  research,
  trace,
  loading,
  error,
  onLoad,
  onExport,
}) {
  const [expanded, setExpanded] = useState(false);
  const queryPlan = trace?.query_plan || {};
  const iterations = trace?.retrieval_iterations || [];

  function toggle() {
    const next = !expanded;
    setExpanded(next);
    if (next && !trace && !loading && !error) onLoad();
  }

  return (
    <section className="panel audit-panel">
      <div className="panel-heading">
        <button
          className="panel-title-button"
          type="button"
          aria-expanded={expanded}
          onClick={toggle}
        >
          <Icon name="clock" size={19} />
          <span>Research audit trail</span>
          <Icon name="chevron" size={16} className={"disclosure-icon" + (expanded ? " expanded" : "")} />
        </button>
        <div className="audit-heading-actions">
          {research?.request_id && <span>Request {research.request_id}</span>}
          {trace && (
            <button className="text-icon-button" type="button" onClick={onExport}>
              <Icon name="download" size={15} /> Export JSON
            </button>
          )}
        </div>
      </div>
      {expanded && (
        <div className="audit-content">
          {loading ? (
            <div className="inline-state" role="status"><span className="button-spinner" /> Loading audit trace…</div>
          ) : error ? (
            <div className="inline-state inline-error" role="alert">
              <p>Audit trace could not be loaded: {error}</p>
              <button className="plain-button" type="button" onClick={onLoad}>Try again</button>
            </div>
          ) : trace ? (
            <>
              <div className="audit-summary-grid">
                <SummaryField label="Original query" value={trace.original_query} />
                <SummaryField label="Canonical query" value={queryPlan.canonical_query || research?.canonical_query} />
                <SummaryField label="Route" value={queryPlan.route || research?.route} />
                <SummaryField label="Evidence considered for synthesis" value={trace.final_evidence_pmids} />
                <SummaryField label="Cited PMIDs" value={trace.citation_audit?.cited_pmids || trace.cited_pmids} />
                <SummaryField label="Stop reason" value={trace.stop_reason} />
                <SummaryField label="Generated at" value={trace.timestamp} />
              </div>
              {queryPlan.subqueries?.length > 0 && (
                <div className="audit-section">
                  <h3>Expanded queries</h3>
                  <ol>{queryPlan.subqueries.map((query, index) => <li key={index}>{query}</li>)}</ol>
                </div>
              )}
              <div className="audit-section">
                <h3>Retrieval iterations {Array.isArray(trace.retrieval_iterations) && <span>({iterations.length})</span>}</h3>
                {iterations.length
                  ? <div className="audit-iterations">{iterations.map((item, index) => <IterationCard key={index} item={item} index={index} />)}</div>
                  : <p className="audit-muted">{trace.execution_mode === "prior_evidence"
                    ? "This follow-up reused validated evidence from earlier turns; no new retrieval was performed."
                    : "Detailed retrieval history was not retained for this request; this does not mean no retrieval occurred."}</p>}
              </div>
              {(trace.stages || trace.events)?.length > 0 && <div className="audit-section">
                <h3>Recorded execution stages</h3>
                <ol>{(trace.stages || trace.events).map((event, index) => <li key={index}>
                  {event.stage} — {event.payload?.status || event.status || "recorded"}
                </li>)}</ol>
              </div>}
              {trace.synthesis_metadata && (
                <details className="audit-raw-details">
                  <summary>Synthesis and model metadata</summary>
                  <pre>{JSON.stringify(trace.synthesis_metadata, null, 2)}</pre>
                </details>
              )}
              {trace.citation_audit && (
                <details className="audit-raw-details">
                  <summary>Citation validation details</summary>
                  <pre>{JSON.stringify(trace.citation_audit, null, 2)}</pre>
                </details>
              )}
            </>
          ) : (
            <div className="audit-empty">
              <p>Expand the audit trail to load the service trace for this request.</p>
              <button className="plain-button" type="button" onClick={onLoad} disabled={!research?.request_id}>
                Load audit details
              </button>
              {!research?.request_id && <span>This response did not include a request ID.</span>}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
