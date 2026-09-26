import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL, analyzeQuery, clearAdminKey, getAdminKey, getHealth, getPaper, getTrace, runResearch, setAdminKey, verifyAdmin } from "./api.js";
import AuditTrail from "./components/AuditTrail.jsx";
import EvidenceTable from "./components/EvidenceTable.jsx";
import InterpretationPanel from "./components/InterpretationPanel.jsx";
import PaperDrawer from "./components/PaperDrawer.jsx";
import RankedPapers from "./components/RankedPapers.jsx";
import SearchBar from "./components/SearchBar.jsx";
import StatusNotice from "./components/StatusNotice.jsx";
import SynthesisPanel from "./components/SynthesisPanel.jsx";
import TopBar from "./components/TopBar.jsx";
import { exportResearchJson } from "./utils.js";

function messageFor(error) {
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}

function validateResearch(data) {
  if (!data || typeof data.synthesis !== "string") {
    throw new Error("The research API response is missing synthesis text.");
  }
  if (!Array.isArray(data.retrieved_papers) || !Array.isArray(data.evidence_table)) {
    throw new Error("The research API response does not match the expected evidence schema.");
  }
  const invalidPaper = data.retrieved_papers.some((paper) =>
    !paper || typeof paper !== "object" || paper.pmid === undefined || paper.pmid === null,
  );
  if (invalidPaper) throw new Error("The research API returned a paper without a PMID; results were not displayed.");
  return data;
}

function validateQueryPlan(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("The query analysis response did not contain a query plan.");
  }
  const plan = data.query_plan && typeof data.query_plan === "object" ? data.query_plan : data;
  if (typeof plan.original_query !== "string" || typeof plan.canonical_query !== "string") {
    throw new Error("The query analysis response did not contain a valid query plan.");
  }
  return plan;
}

export default function App() {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ yearMin: "", yearMax: "", studyType: "", maxLoops: 2 });
  const [health, setHealth] = useState("checking");
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [research, setResearch] = useState(null);
  const [researchError, setResearchError] = useState("");
  const [queryPlan, setQueryPlan] = useState(null);
  const [analysisError, setAnalysisError] = useState("");
  const [selectedPaper, setSelectedPaper] = useState(null);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [activeEvidencePmids, setActiveEvidencePmids] = useState([]);
  const [paperDetails, setPaperDetails] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [trace, setTrace] = useState(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [adminDialogOpen, setAdminDialogOpen] = useState(false);
  const [adminInput, setAdminInput] = useState("");
  const [adminError, setAdminError] = useState("");
  const latestRequest = useRef(null);

  useEffect(() => {
    let active = true;
    getHealth().then(() => {
      if (active) setHealth("online");
    }).catch(() => {
      if (active) setHealth("offline");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!getAdminKey()) return;
    verifyAdmin().then(() => setIsAdmin(true)).catch(() => {
      clearAdminKey();
      setIsAdmin(false);
    });
  }, []);

  const executeResearch = useCallback(async (request) => {
    setLoading(true);
    setHasSearched(true);
    setResearch(null);
    setResearchError("");
    setQueryPlan(null);
    setAnalysisError("");
    setSelectedPaper(null);
    setPaperDetails(null);
    setDetailError("");
    setTrace(null);
    setTraceError("");
    setActiveEvidencePmids([]);
    latestRequest.current = request;

    const [analysisResult, researchResult] = await Promise.allSettled([
      isAdmin ? analyzeQuery(request.query) : Promise.resolve(null),
      runResearch(request),
    ]);

    if (isAdmin && analysisResult.status === "fulfilled" && analysisResult.value) {
      try {
        setQueryPlan(validateQueryPlan(analysisResult.value));
      } catch (error) {
        setAnalysisError(messageFor(error));
      }
    } else if (isAdmin) {
      setAnalysisError(messageFor(analysisResult.reason));
    }

    if (researchResult.status === "rejected") {
      setResearchError(messageFor(researchResult.reason));
      setHealth("offline");
      setLoading(false);
      return;
    }

    try {
      const result = validateResearch(researchResult.value);
      setResearch(result);
      setHealth("online");
      const firstPaper = result.retrieved_papers[0] || null;
      setSelectedPaper(firstPaper);
    } catch (error) {
      setResearchError(messageFor(error));
    } finally {
      setLoading(false);
    }
  }, [isAdmin]);

  function handleResearch(event) {
    event?.preventDefault();
    const cleanQuery = query.trim();
    if (!cleanQuery) return;
    if (filters.yearMin && filters.yearMax && Number(filters.yearMin) > Number(filters.yearMax)) {
      setResearchError("The start year must be earlier than or equal to the end year.");
      return;
    }
    const request = {
      query: cleanQuery,
      yearMin: filters.yearMin,
      yearMax: filters.yearMax,
      studyTypes: filters.studyType ? [filters.studyType] : [],
      maxLoops: filters.maxLoops,
    };
    executeResearch(request);
  }

  function selectPaper(paper) {
    setSelectedPaper(paper);
    setPaperDetails(null);
    setDetailError("");
    setMobileDrawerOpen(true);
  }

  function traceEvidence(pmids) {
    if (!isAdmin) return;
    const sourceIds = [...new Set(pmids.map(String))];
    setActiveEvidencePmids(sourceIds);
    const candidate = research?.retrieved_papers?.find((paper) => sourceIds.includes(String(paper.pmid)));
    if (candidate) {
      selectPaper(candidate);
      return;
    }
    const evidenceRecord = research?.evidence_table?.find((row) => sourceIds.includes(String(row.pmid)));
    if (evidenceRecord) {
      selectPaper({
        ...evidenceRecord,
        title: evidenceRecord.title || "Evidence source " + evidenceRecord.pmid,
        abstract: "",
        study_type: evidenceRecord.study_design || "Not reported",
        authors: [],
        mesh_terms: [],
        channel_scores: {},
        channel_ranks: {},
      });
    } else {
      setMobileDrawerOpen(true);
    }
  }

  function closeDrawer() {
    setSelectedPaper(null);
    setPaperDetails(null);
    setMobileDrawerOpen(false);
  }

  useEffect(() => {
    if (!selectedPaper?.pmid) return undefined;
    let active = true;
    setDetailLoading(true);
    setDetailError("");
    getPaper(selectedPaper.pmid).then((record) => {
      if (active) setPaperDetails(record);
    }).catch((error) => {
      if (active) setDetailError(messageFor(error));
    }).finally(() => {
      if (active) setDetailLoading(false);
    });
    return () => { active = false; };
  }, [selectedPaper?.pmid]);

  async function loadTrace() {
    if (!isAdmin || !research || traceLoading) return;
    setTraceLoading(true);
    setTraceError("");
    try {
      const result = await getTrace(research.audit_trace_url, research.request_id);
      setTrace(result);
    } catch (error) {
      setTraceError(messageFor(error));
    } finally {
      setTraceLoading(false);
    }
  }

  function exportJson() {
    if (research && isAdmin) exportResearchJson(research, trace);
  }

  async function handleAdminSubmit(event) {
    event.preventDefault();
    const candidate = adminInput.trim();
    if (!candidate) return;
    setAdminError("");
    setAdminKey(candidate);
    try {
      await verifyAdmin();
      setIsAdmin(true);
      setAdminDialogOpen(false);
      setAdminInput("");
    } catch (error) {
      clearAdminKey();
      setIsAdmin(false);
      setAdminError(messageFor(error));
    }
  }

  function handleAdminLogout() {
    clearAdminKey();
    setIsAdmin(false);
    setResearch(null);
    setQueryPlan(null);
    setTrace(null);
    setTraceError("");
    setSelectedPaper(null);
    setPaperDetails(null);
    setActiveEvidencePmids([]);
    setMobileDrawerOpen(false);
  }

  const papers = research?.retrieved_papers || [];
  const evidenceRows = research?.evidence_table || [];
  const errorMessage = researchError;

  return (
    <div className="app-shell">
      <TopBar health={health} apiUrl={API_BASE_URL} isAdmin={isAdmin} onAdmin={() => { setAdminError(""); setAdminDialogOpen(true); }} onLogout={handleAdminLogout} />
      {adminDialogOpen && !isAdmin && (
        <div className="admin-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setAdminDialogOpen(false); }}>
          <form className="admin-dialog" onSubmit={handleAdminSubmit} aria-labelledby="admin-dialog-title">
            <h2 id="admin-dialog-title">Administrator access</h2>
            <p>Query interpretation, audit traces, evidence spans, and retrieval provenance are restricted to administrators.</p>
            <label htmlFor="admin-key">Admin key</label>
            <input id="admin-key" type="password" autoComplete="current-password" value={adminInput} onChange={(event) => setAdminInput(event.target.value)} autoFocus />
            {adminError && <div className="inline-error" role="alert">{adminError}</div>}
            <div className="admin-dialog-actions">
              <button className="plain-button" type="button" onClick={() => setAdminDialogOpen(false)}>Cancel</button>
              <button className="research-button" type="submit">Verify access</button>
            </div>
          </form>
        </div>
      )}
      <main className="app-main">
        <SearchBar
          query={query}
          setQuery={setQuery}
          filters={filters}
          setFilters={setFilters}
          onResearch={handleResearch}
          loading={loading}
        />
        <StatusNotice message={errorMessage} onRetry={latestRequest.current ? () => executeResearch(latestRequest.current) : null} />
        <div className="workspace-grid">
          <div className="analysis-column">
            {isAdmin && <InterpretationPanel queryPlan={queryPlan} loading={loading} error={analysisError} />}
            <SynthesisPanel research={research} onTraceEvidence={traceEvidence} isAdmin={isAdmin} />
            {isAdmin && <EvidenceTable
              rows={evidenceRows}
              activePmids={activeEvidencePmids}
              onTraceEvidence={traceEvidence}
              hasSearched={hasSearched}
              onExportJson={exportJson}
            />}
            {isAdmin && <AuditTrail
              research={research}
              trace={trace}
              loading={traceLoading}
              error={traceError}
              onLoad={loadTrace}
              onExport={exportJson}
            />}
          </div>
          <RankedPapers
            papers={papers}
            total={research?.total_found ?? papers.length}
            selectedPmid={selectedPaper?.pmid}
            onSelect={selectPaper}
            loading={loading}
            hasSearched={hasSearched}
            isAdmin={isAdmin}
          />
          <PaperDrawer
            selectedPaper={selectedPaper}
            paperDetails={paperDetails}
            detailLoading={detailLoading}
            detailError={detailError}
            evidence={evidenceRows}
            papers={papers}
            active={activeEvidencePmids.includes(String(selectedPaper?.pmid))}
            mobileOpen={mobileDrawerOpen}
            onSelect={selectPaper}
            onClose={closeDrawer}
            isAdmin={isAdmin}
          />
        </div>
      </main>
    </div>
  );
}
