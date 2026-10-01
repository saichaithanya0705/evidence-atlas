import { auditDate, auditDuration } from '../auditPresentation.js';
import { normalizeTraceIteration } from '../auditTrace.js';

function labelFor(key) {
  return key.replace(/_/g, " ").replace(/\b\w/g, character => character.toUpperCase());
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(item => typeof item === "object" ? JSON.stringify(item) : String(item)).join(", ") : "None";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const EVENT_LABELS = {
  action: "Action", complexity_hint: "Complexity hint", accepted: "Accepted", iteration: "Iteration",
  route_floor: "Route floor", rewrite_applied: "Rewrite applied", route: "Route", rule_route: "Rule route",
  agent_complexity_hint: "Agent complexity hint", status: "Status", duration_ms: "Duration",
  candidate_count: "Candidate count", grade: "Grade", missing_count: "Missing concepts",
  conflict_count: "Conflicts", stop_reason: "Stop reason", reason: "Reason", claim_count: "Claims",
  supported_count: "Supported claims", unsupported_count: "Unsupported claims", gap_count: "Evidence gaps",
  evidence_count: "Evidence records",
  preserved_claims: "Preserved claims", repaired_claims: "Repaired claims", pruned_claims: "Pruned claims", attempt_count: "Repair attempts", referenced_turn_count: "Referenced turns",
};

function eventSummary(payload = {}) {
  return Object.entries(payload).filter(([key]) => Object.hasOwn(EVENT_LABELS, key));
}

export function Facts({ title, value, empty = "No information recorded" }) {
  const entries = value && typeof value === "object" && !Array.isArray(value) ? Object.entries(value) : [];
  return <section className="panel audit-facts"><h2>{title}</h2>{entries.length ? <dl>{entries.map(([key, item]) => <div key={key}><dt>{labelFor(key)}</dt><dd>{formatValue(item)}</dd></div>)}</dl> : <p className="audit-empty">{empty}</p>}</section>;
}

export function Timeline({ events = [], stages = [] }) {
  const items = events.length ? events.map(item => ({ stage: item.stage, timestamp: item.timestamp, payload: item.payload })) : stages.map(item => ({ stage: item.stage || item.name || "Workflow stage", payload: item }));
  return <section className="panel audit-timeline"><h2>Workflow timeline</h2>{items.length ? <ol>{items.map((item, index) => <li key={index}><span className="timeline-marker">{String(index + 1).padStart(2, "0")}</span><div><h3>{labelFor(item.stage || "Stage")}</h3><time dateTime={item.timestamp || undefined}>{auditDate(item.timestamp)}</time><dl>{eventSummary(item.payload).map(([key, value]) => <div key={key}><dt>{EVENT_LABELS[key]}</dt><dd>{key === 'duration_ms' ? auditDuration(value) : formatValue(value)}</dd></div>)}</dl></div></li>)}</ol> : <p className="audit-empty">No workflow events were captured for this run.</p>}</section>;
}

export function ConversationTimeline({ events = [], mode, action }) {
  return <><p className="panel audit-mode" role="status">{mode === 'prior_evidence' || action === 'ANSWER_FROM_EVIDENCE' ? 'Previous evidence reused: no new retrieval was performed. Only executed stages appear below.' : ['CLARIFY','ABSTAIN'].includes(action) ? 'This turn did not execute the research pipeline. Only recorded decision events appear below.' : 'Events are shown in recorded execution order, including repeated retrieval and correction attempts.'}</p><Timeline events={events} /></>;
}

export function AuditGeneration({ run }) {
  const trace = run.trace && Object.keys(run.trace).length && run.trace_availability !== 'not_recorded' ? run.trace : null;
  const timings = trace?.timings_ms?.stages || Object.entries(run.stage_durations_ms || {}).map(([stage,duration_ms]) => ({stage,duration_ms}));
  return <>
    {!trace && <p className="panel detail-warning" role="status">Detailed trace snapshot was not retained for this run. The stored events and response remain available; missing details are not reconstructed.</p>}
    <div className="detail-grid"><Facts title="Request times" value={{started:auditDate(run.started_at),finished:auditDate(run.finished_at),request_duration:auditDuration(run.duration_ms),timezone:Intl.DateTimeFormat().resolvedOptions().timeZone}} />
      <Facts title="Answer generation" value={trace ? {execution_mode:trace.execution_mode || 'Not recorded',synthesis_mode:trace.synthesis_metadata?.mode || 'Not recorded',fallback_used:trace.synthesis_metadata?.fallback_used ?? 'Not recorded',stop_reason:trace.stop_reason || 'Not recorded',workflow_duration:auditDuration(trace.timings_ms?.total),generation_duration:auditDuration(trace.synthesis_metadata?.timings_ms?.generation)} : null} empty="Generation metadata was not retained" /></div>
    {trace?.query_plan && <Facts title="Query processing" value={{original_query:trace.original_query,canonical_query:trace.query_plan.canonical_query,subqueries:trace.query_plan.subqueries}} />}
    <section className="panel audit-facts"><h2>Stage timings</h2>{timings.length ? <dl>{timings.map((item,index) => <div key={index}><dt>{labelFor(item.stage)}{item.iteration != null ? ` · attempt ${item.iteration + 1}` : ''}</dt><dd>{auditDuration(item.duration_ms)}</dd></div>)}</dl> : <p className="audit-empty">Stage durations were not recorded for this run.</p>}</section>
    {(trace?.retrieval_iterations || []).map((raw,index) => {
      const item = normalizeTraceIteration(raw);
      return <Facts key={index} title={`Retrieval attempt ${(item.iteration ?? index) + 1}`} value={{queries:item.queries,channels:item.channels,candidate_count:item.pmids.length,candidate_pmids:item.pmids,grade:item.grade || 'Not recorded'}} />;
    })}
  </>;
}

export function EvidenceSnapshot({ response }) {
  if (!response) return <section className="panel audit-evidence"><h2>Evidence and response</h2><p className="audit-empty">No response snapshot was produced. Review the error and workflow events above.</p></section>;
  const papers = Array.isArray(response.retrieved_papers) ? response.retrieved_papers : [];
  const evidence = Array.isArray(response.evidence_table) ? response.evidence_table : [];
  return <section className="panel audit-evidence"><div className="audit-section-heading"><h2>Evidence and response</h2><span>{papers.length} papers · {evidence.length} evidence rows</span></div>{typeof response.synthesis === "string" && <div className="audit-synthesis"><span className="eyebrow">RECORDED SYNTHESIS</span><p>{response.synthesis}</p></div>}{papers.length > 0 && <div className="audit-paper-list"><h3>Retrieved sources</h3>{papers.slice(0, 20).map((paper, index) => <article key={paper.pmid || index}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{paper.title || "Untitled paper"}</strong><p>PMID {paper.pmid}{paper.year ? ` · ${paper.year}` : ""}{paper.study_type ? ` · ${paper.study_type}` : ""}</p></div></article>)}</div>}{evidence.length > 0 && <div className="audit-paper-list"><h3>Evidence rows</h3>{evidence.slice(0, 20).map((row, index) => <article key={index}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{row.title || `PMID ${row.pmid || "not recorded"}`}</strong><p>{formatValue(row.supporting_text_spans || row.study_design)}</p></div></article>)}</div>}</section>;
}
