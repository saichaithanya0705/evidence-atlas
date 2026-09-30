import { useEffect, useState } from "react";
import { getEvaluation, getEvaluations } from "../api.js";
import StatusNotice from "./StatusNotice.jsx";

const ABLATION_VARIANTS = ["dense_only", "hybrid", "reranked", "agentic"];

function display(value) {
  if (value == null) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function ReportList({ reports, navigate }) {
  return <div className="table-card panel evaluation-report-list"><div className="table-heading"><h2>Promoted reports</h2><span>{reports.length} reports</span></div><div className="table-scroll"><table><thead><tr><th>Run</th><th>Queries</th><th>Benchmark checksum</th><th>Report checksum</th><th></th></tr></thead><tbody>{reports.map(report => <tr key={report.run_id}><td>{report.run_id}</td><td>{report.query_count}</td><td><code>{report.benchmark_checksum}</code></td><td><code>{report.report_checksum}</code></td><td><a href={`/admin/evaluations/${encodeURIComponent(report.run_id)}`} onClick={event => { event.preventDefault(); navigate(`/admin/evaluations/${encodeURIComponent(report.run_id)}`); }}>View report</a></td></tr>)}</tbody></table></div>{reports.length === 0 && <p className="empty-list">No completed evaluation reports have been promoted.</p>}</div>;
}

function MetricTable({ report }) {
  const variants = ABLATION_VARIANTS;
  const metricNames = [...new Set(Object.keys(report.metrics || {}).map(name => name.includes(".") ? name.slice(name.indexOf(".") + 1) : name))].sort();
  return <section className="panel evaluation-section"><h2>Four-variant ablation</h2><div className="table-scroll"><table><thead><tr><th>Metric</th>{variants.map(variant => <th key={variant}>{variant}</th>)}</tr></thead><tbody>{metricNames.map(metricName => <tr key={metricName}><th scope="row">{metricName}</th>{variants.map(variant => { const result = report.metrics[`${variant}.${metricName}`]; const missingVariant = !report.variants?.includes(variant); return <td key={variant}>{result ? <><span className={`status-pill status-pill-${result.status}`}>{result.status}</span><span className="evaluation-value">{display(result.value)}</span>{result.reason && <small>{result.reason}</small>}</> : missingVariant ? <><span className="status-pill status-pill-not_run">not_run</span><small>variant was not included in this evaluation run</small></> : "—"}</td>; })}</tr>)}</tbody></table></div></section>;
}

function QueryFailures({ queries, variants }) {
  const failures = [];
  for (const query of queries || []) for (const variant of variants || []) {
    const details = query.variants?.[variant];
    for (const diagnostic of details?.diagnostics || []) failures.push({ queryId: query.query_id, variant, ...diagnostic });
  }
  return <section className="panel evaluation-section"><h2>Per-query failures</h2><div className="table-scroll"><table><thead><tr><th>Query</th><th>Variant</th><th>Failure</th><th>Reason</th></tr></thead><tbody>{failures.map((failure, index) => <tr key={`${failure.queryId}-${failure.variant}-${index}`}><td>{failure.queryId}</td><td>{failure.variant}</td><td>{failure.category}</td><td>{failure.reason || "—"}</td></tr>)}</tbody></table></div>{failures.length === 0 && <p className="empty-list">No per-query failures were recorded.</p>}</section>;
}

function RobustnessTable({ report }) {
  const rows = [];
  for (const [variant, result] of Object.entries(report.robustness || {})) {
    for (const [scenario, details] of Object.entries(result.value?.scenarios || {})) {
      for (const [metric, delta] of Object.entries(details || {})) rows.push({ variant, scenario, metric, delta });
    }
  }
  for (const query of report.queries || []) for (const [variant, details] of Object.entries(query.variants || {})) {
    for (const [scenario, deltas] of Object.entries(details.robustness?.scenarios || {})) for (const [metric, delta] of Object.entries(deltas || {})) rows.push({ variant, scenario, metric, delta, queryId: query.query_id });
  }
  return <section className="panel evaluation-section"><h2>Robustness deltas</h2><div className="table-scroll"><table><thead><tr><th>Variant</th><th>Query</th><th>Scenario</th><th>Metric</th><th>Delta</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.variant}-${row.queryId || "all"}-${row.scenario}-${row.metric}-${index}`}><td>{row.variant}</td><td>{row.queryId || "Aggregate"}</td><td>{row.scenario}</td><td>{row.metric}</td><td>{display(row.delta)}</td></tr>)}</tbody></table></div>{rows.length === 0 && <p className="empty-list">No robustness deltas were recorded.</p>}</section>;
}

export default function EvaluationDashboard({ runId, navigate }) {
  const [state, setState] = useState({ loading: true, data: null, error: "" });
  useEffect(() => {
    let active = true;
    setState({ loading: true, data: null, error: "" });
    const load = runId ? getEvaluation(runId) : getEvaluations();
    load.then(data => { if (active) setState({ loading: false, data, error: "" }); })
      .catch(error => { if (active) setState({ loading: false, data: null, error: error.message || "Evaluation reports could not be loaded." }); });
    return () => { active = false; };
  }, [runId]);
  const report = runId ? state.data : null;
  return <main className="admin-page evaluation-dashboard"><div className="admin-page-header"><span className="eyebrow">ADMINISTRATION / EVALUATION</span><h1>{runId ? `Evaluation report ${runId}` : "Evaluation reports"}</h1><p>Completed, promoted benchmark runs and their administrator-only metrics.</p></div>
    {runId && <a className="back-link" href="/admin/evaluations" onClick={event => { event.preventDefault(); navigate("/admin/evaluations"); }}>← All evaluation reports</a>}
    {state.loading && <p className="panel page-state" role="status">Loading evaluation reports…</p>}
    {state.error && <StatusNotice message={state.error} />}
    {!runId && state.data && <ReportList reports={state.data.items || []} navigate={navigate} />}
    {report && <><section className="panel evaluation-metadata"><div><span>Benchmark checksum</span><code>{report.benchmark_checksum}</code></div><div><span>Corpus checksum</span><code>{report.corpus_checksum}</code></div><div><span>Configuration checksum</span><code>{report.configuration_checksum}</code></div><div><span>Report checksum</span><code>{report.report_checksum}</code></div><div><span>Query count</span><strong>{report.query_count}</strong></div><div><span>Variants</span><strong>{(report.variants || []).join(", ")}</strong></div></section>
      <MetricTable report={report} />
      <section className="panel evaluation-section"><h2>Failure categories</h2>{Object.keys(report.failure_categories || {}).length ? Object.entries(report.failure_categories).map(([name, value]) => <div className="breakdown-row" key={name}><span>{name}</span><strong>{value}</strong></div>) : <p className="empty-list">No failure categories were recorded.</p>}</section>
      <QueryFailures queries={report.queries} variants={report.variants} />
      <RobustnessTable report={report} />
      {report.limitations?.length > 0 && <section className="panel evaluation-section"><h2>Limitations</h2><ul>{report.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></section>}
    </>}
  </main>;
}
