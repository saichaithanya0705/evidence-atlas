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
  agent_complexity_hint: "Agent complexity hint", status: "Status", duration_ms: "Duration ms",
  candidate_count: "Candidate count", grade: "Grade", missing_count: "Missing concepts",
  conflict_count: "Conflicts", stop_reason: "Stop reason", reason: "Reason", claim_count: "Claims",
  supported_count: "Supported claims", unsupported_count: "Unsupported claims", gap_count: "Evidence gaps",
  evidence_count: "Evidence records",
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
  return <section className="panel audit-timeline"><h2>Workflow timeline</h2>{items.length ? <ol>{items.map((item, index) => <li key={index}><span className="timeline-marker">{String(index + 1).padStart(2, "0")}</span><div><h3>{labelFor(item.stage || "Stage")}</h3>{item.timestamp && <time>{new Date(item.timestamp).toLocaleString()}</time>}<dl>{eventSummary(item.payload).map(([key, value]) => <div key={key}><dt>{EVENT_LABELS[key]}</dt><dd>{formatValue(value)}</dd></div>)}</dl></div></li>)}</ol> : <p className="audit-empty">No workflow events were captured for this run.</p>}</section>;
}

const PHASES = [
  { title: "Agent decision", stages: ["agent_decision"] },
  { title: "Query enhanced", stages: ["query_enhanced"] },
  { title: "Route arbitrated", stages: ["route_arbitrated", "query_analysis"] },
  { title: "Retrieval/Judge loop", stages: ["retrieval_attempt", "retrieve", "judge", "evidence_judged", "correct", "correction_stopped"] },
  { title: "Claim verification", stages: ["claim_verified", "semantic_verification"] },
  { title: "Release", stages: ["answer_released"] },
];

export function ConversationTimeline({ events = [] }) {
  return <section className="panel audit-timeline"><h2>Conversation phase timeline</h2><ol>{PHASES.map((phase, index) => {
    const items = events.filter(event => phase.stages.includes(event.stage));
    return <li key={phase.title}><span className="timeline-marker">{String(index + 1).padStart(2, "0")}</span><div><h3>{phase.title}</h3>{items.length ? items.map((item, itemIndex) => <div className="audit-phase-event" key={`${item.stage}-${itemIndex}`}><span>{labelFor(item.stage)}</span>{eventSummary(item.payload).map(([key, value]) => <span key={key}>{EVENT_LABELS[key]}: {formatValue(value)}</span>)}</div>) : <p className="audit-empty">No event recorded</p>}</div></li>;
  })}</ol></section>;
}

export function EvidenceSnapshot({ response }) {
  if (!response) return <section className="panel audit-evidence"><h2>Evidence and response</h2><p className="audit-empty">No response snapshot was produced. Review the error and workflow events above.</p></section>;
  const papers = Array.isArray(response.retrieved_papers) ? response.retrieved_papers : [];
  const evidence = Array.isArray(response.evidence_table) ? response.evidence_table : [];
  return <section className="panel audit-evidence"><div className="audit-section-heading"><h2>Evidence and response</h2><span>{papers.length} papers · {evidence.length} evidence rows</span></div>{typeof response.synthesis === "string" && <div className="audit-synthesis"><span className="eyebrow">RECORDED SYNTHESIS</span><p>{response.synthesis}</p></div>}{papers.length > 0 && <div className="audit-paper-list"><h3>Retrieved sources</h3>{papers.slice(0, 20).map((paper, index) => <article key={paper.pmid || index}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{paper.title || "Untitled paper"}</strong><p>PMID {paper.pmid}{paper.year ? ` · ${paper.year}` : ""}{paper.study_type ? ` · ${paper.study_type}` : ""}</p></div></article>)}</div>}{evidence.length > 0 && <div className="audit-paper-list"><h3>Evidence rows</h3>{evidence.slice(0, 20).map((row, index) => <article key={index}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{row.title || `PMID ${row.pmid || "not recorded"}`}</strong><p>{formatValue(row.supporting_text_spans || row.study_design)}</p></div></article>)}</div>}</section>;
}
