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

export function Facts({ title, value, empty = "No information recorded", raw = false }) {
  const entries = value && typeof value === "object" && !Array.isArray(value) ? Object.entries(value) : [];
  return <section className="panel audit-facts"><h2>{title}</h2>{entries.length ? <dl>{entries.map(([key, item]) => <div key={key}><dt>{labelFor(key)}</dt><dd>{formatValue(item)}</dd></div>)}</dl> : <p className="audit-empty">{empty}</p>}{raw && entries.length > 0 && <details className="raw-disclosure"><summary>Inspect original data</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>}</section>;
}

export function Timeline({ events = [], stages = [] }) {
  const items = events.length ? events.map(item => ({ stage: item.stage, timestamp: item.timestamp, payload: item.payload })) : stages.map(item => ({ stage: item.stage || item.name || "Workflow stage", payload: item }));
  return <section className="panel audit-timeline"><h2>Workflow timeline</h2>{items.length ? <ol>{items.map((item, index) => <li key={index}><span className="timeline-marker">{String(index + 1).padStart(2, "0")}</span><div><h3>{labelFor(item.stage || "Stage")}</h3>{item.timestamp && <time>{new Date(item.timestamp).toLocaleString()}</time>}<dl>{Object.entries(item.payload || {}).slice(0, 6).map(([key, value]) => <div key={key}><dt>{labelFor(key)}</dt><dd>{formatValue(value)}</dd></div>)}</dl></div></li>)}</ol> : <p className="audit-empty">No workflow events were captured for this run.</p>}</section>;
}

export function EvidenceSnapshot({ response }) {
  if (!response) return <section className="panel audit-evidence"><h2>Evidence and response</h2><p className="audit-empty">No response snapshot was produced. Review the error and workflow events above.</p></section>;
  const papers = response.retrieved_papers || response.candidates || [];
  const evidence = response.evidence_table || [];
  return <section className="panel audit-evidence"><div className="audit-section-heading"><h2>Evidence and response</h2><span>{papers.length} papers · {evidence.length} evidence rows</span></div>{response.synthesis && <div className="audit-synthesis"><span className="eyebrow">RECORDED SYNTHESIS</span><p>{response.synthesis}</p></div>}{papers.length > 0 && <div className="audit-paper-list"><h3>Retrieved sources</h3>{papers.slice(0, 20).map((paper, index) => <article key={paper.pmid || index}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{paper.title || "Untitled paper"}</strong><p>PMID {paper.pmid}{paper.year ? ` · ${paper.year}` : ""}{paper.study_type ? ` · ${paper.study_type}` : ""}</p></div></article>)}</div>}{evidence.length > 0 && <div className="audit-paper-list"><h3>Evidence rows</h3>{evidence.slice(0, 20).map((row, index) => <article key={index}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{row.title || `PMID ${row.pmid || "not recorded"}`}</strong><p>{formatValue(row.supporting_text_spans || row.supporting_span || row.study_design)}</p></div></article>)}</div>}<details className="raw-disclosure"><summary>Inspect full response snapshot</summary><pre>{JSON.stringify(response, null, 2)}</pre></details></section>;
}
