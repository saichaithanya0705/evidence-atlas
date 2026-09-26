export const STUDY_TYPE_OPTIONS = [
  "Randomized Controlled Trial",
  "Systematic Review",
  "Meta-Analysis",
  "Observational",
  "Clinical Trial",
  "Review",
  "Preclinical Study",
  "Other",
];

export function formatValue(value, fallback = "Not reported") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(", ") : fallback;
  return String(value);
}

export function formatScore(value) {
  if (value === null || value === undefined || value === "") return "Not returned";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(4) : String(value);
}

export function getCitationPmids(text = "") {
  return Array.from(text.matchAll(/PMID:\s*(\d+)/gi), (match) => match[1]);
}

export function downloadFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(value) {
  const normalized = Array.isArray(value) ? value.join("; ") : value ?? "";
  return '"' + String(normalized).replace(/"/g, '""') + '"';
}

export function exportEvidenceCsv(rows) {
  const columns = [
    ["PMID", "pmid"],
    ["Title", "title"],
    ["Study design", "study_design"],
    ["Population", "population"],
    ["Intervention", "intervention"],
    ["Comparator", "comparator"],
    ["Outcome", "outcome"],
    ["Key findings", "key_findings"],
    ["Limitations", "limitations"],
    ["Supporting text spans", "supporting_text_spans"],
  ];
  const lines = [
    columns.map(([label]) => csvCell(label)).join(","),
    ...rows.map((row) => columns.map(([, key]) => csvCell(row[key])).join(",")),
  ];
  downloadFile("evidence-atlas-evidence.csv", "\uFEFF" + lines.join("\r\n"), "text/csv;charset=utf-8");
}

export function exportResearchJson(research, trace) {
  const payload = {
    request_id: research?.request_id ?? null,
    query: research?.query ?? null,
    canonical_query: research?.canonical_query ?? null,
    audit_trace_url: research?.audit_trace_url ?? null,
    route: research?.route ?? null,
    synthesis: research?.synthesis ?? null,
    cited_pmids: research?.cited_pmids ?? [],
    citations_valid: research?.citations_valid ?? null,
    citation_precision: research?.citation_precision ?? null,
    consensus_level: research?.consensus_level ?? null,
    evidence_gaps: research?.evidence_gaps ?? [],
    retrieved_papers: research?.retrieved_papers ?? [],
    evidence_table: research?.evidence_table ?? [],
    audit_trace: trace ?? null,
  };
  downloadFile(
    "evidence-atlas-research.json",
    JSON.stringify(payload, null, 2),
    "application/json;charset=utf-8",
  );
}

export function pubmedUrl(pmid) {
  return "https://pubmed.ncbi.nlm.nih.gov/" + encodeURIComponent(pmid) + "/";
}
