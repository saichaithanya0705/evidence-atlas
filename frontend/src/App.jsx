import { useEffect, useState } from "react";
import { API_BASE_URL, changePassword, createAccount, getAudit, getHealth, getObservability, getPaper, getSession, listAccounts, listAudits, login, logout, runResearch, updateAccount } from "./api.js";
import PaperDrawer from "./components/PaperDrawer.jsx";
import RankedPapers from "./components/RankedPapers.jsx";
import SearchBar from "./components/SearchBar.jsx";
import StatusNotice from "./components/StatusNotice.jsx";
import SynthesisPanel from "./components/SynthesisPanel.jsx";
import TopBar from "./components/TopBar.jsx";
import { AuditGeneration, ConversationTimeline, EvidenceSnapshot, Facts, Timeline } from "./components/AuditData.jsx";
import ConversationWorkspace from "./components/ConversationWorkspace.jsx";
import EvaluationDashboard from "./components/EvaluationDashboard.jsx";
import useEvidenceWorkspace from "./hooks/useEvidenceWorkspace.js";
import EvidenceWorkspace from "./components/EvidenceWorkspace.jsx";

import { auditDate, auditDuration, auditListUrl, auditRequestParams, readAuditFilters } from "./auditPresentation.js";

function errorText(error) { return error instanceof Error ? error.message : "An unexpected error occurred."; }

function usePath() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  function navigate(next) {
    if (window.location.pathname + window.location.search !== next) window.history.pushState({}, "", next);
    setPath(window.location.pathname);
    window.scrollTo(0, 0);
  }
  return [path, navigate];
}

function InternalLink({ to, navigate, children, ...props }) {
  return <a href={to} onClick={(event) => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigate(to); } }} {...props}>{children}</a>;
}

function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try { const result = await login(username.trim(), password); onLogin(result.account); }
    catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); }
  }
  return <main className="login-layout">
    <section className="login-story"><span className="eyebrow">Evidence Atlas</span><h1>Medical literature,<br /><em>made legible.</em></h1><p>Ask a research question. Follow the evidence to its source. Make room for nuance.</p><div className="login-art" aria-hidden="true"><span /><span /><span /><span /></div><small>Find. Trace. Understand.</small></section>
    <section className="login-card" aria-labelledby="login-title"><div className="login-card-inner"><span className="eyebrow">PRIVATE RESEARCH WORKSPACE</span><h2 id="login-title">Welcome back.</h2><p>Sign in with the account your administrator created for you.</p><form onSubmit={submit}><label htmlFor="username">Username</label><input id="username" autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required /><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /><StatusNotice message={error} /><button className="research-button" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button></form><p className="login-help">Need access? Ask an administrator to create an account.</p></div></section>
  </main>;
}

function PasswordPage({ onDone, required }) {
  const [current, setCurrent] = useState(""); const [next, setNext] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function submit(event) { event.preventDefault(); setBusy(true); setError(""); try { await changePassword(current, next); onDone(); } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); } }
  return <main className="simple-page"><div className="form-card"><span className="eyebrow">ACCOUNT SECURITY</span><h1>Set your password</h1><p>{required ? "Your administrator issued a temporary password. Choose a private password of at least 12 characters before researching." : "Choose a new private password of at least 12 characters. You will sign in again after saving it."}</p><form onSubmit={submit}><label htmlFor="current-password">Current password</label><input id="current-password" type="password" autoComplete="current-password" value={current} onChange={event => setCurrent(event.target.value)} required /><label htmlFor="new-password">New password</label><input id="new-password" type="password" minLength={12} autoComplete="new-password" value={next} onChange={event => setNext(event.target.value)} required /><StatusNotice message={error} /><button className="research-button" disabled={busy}>{busy ? "Saving…" : "Change password"}</button></form></div></main>;
}

function ResearchPage({ isAdmin, navigate, filters, setFilters }) {
  const [query, setQuery] = useState("");
  const [research, setResearch] = useState(null); const [error, setError] = useState(""); const [loading, setLoading] = useState(false); const [searched, setSearched] = useState(false);
  const [selectedPaper, setSelectedPaper] = useState(null); const [paperDetails, setPaperDetails] = useState(null); const [detailError, setDetailError] = useState(""); const [detailLoading, setDetailLoading] = useState(false);
  useEffect(() => { if (!selectedPaper?.pmid) return; let active = true; setPaperDetails(null); setDetailError(""); setDetailLoading(true); getPaper(selectedPaper.pmid).then(data => { if (active) setPaperDetails(data); }).catch(failure => { if (active) setDetailError(errorText(failure)); }).finally(() => { if (active) setDetailLoading(false); }); return () => { active = false; }; }, [selectedPaper?.pmid]);
  async function submit(event) {
    event.preventDefault(); if (loading || !query.trim()) return;
    if (isAdmin && filters.yearMin && filters.yearMax && Number(filters.yearMin) > Number(filters.yearMax)) { setError("The start year must be no later than the end year."); return; }
    setSearched(true); setLoading(true); setError(""); setResearch(null); setSelectedPaper(null);
    try {
      const result = await runResearch({ query: query.trim(), yearMin: filters.yearMin, yearMax: filters.yearMax, studyTypes: filters.studyType ? [filters.studyType] : [], maxLoops: filters.maxLoops }, isAdmin);
      if (!Array.isArray(result.retrieved_papers) || !Array.isArray(result.evidence_table) || typeof result.synthesis !== "string") throw Error("The research response is incomplete.");
      setResearch(result);
    } catch (failure) { setError(errorText(failure)); }
    finally { setLoading(false); }
  }
  const papers = research?.retrieved_papers || [];
  return <main className={"app-main research-workspace " + (isAdmin ? "admin-research" : "user-research")}>
    <SearchBar query={query} setQuery={setQuery} filters={filters} setFilters={setFilters} onResearch={submit} loading={loading} hasSearched={searched} isAdmin={isAdmin} />
    {isAdmin && <div className="workspace-intro"><span className="eyebrow">ADMIN RESEARCH DESK</span><p>Explore the corpus with advanced controls. Query traces and system metrics live in their own workspaces.</p></div>}
    {!isAdmin && <div className="workspace-intro"><span className="eyebrow">YOUR RESEARCH DESK</span><p>Every answer is grounded in retrieved abstracts. Open a source to read it in context.</p></div>}
    {!isAdmin && <p className="privacy-note" role="note">Administrators can review your research questions and query traces.</p>}
    <StatusNotice message={error} />
    {isAdmin && research?.request_id && <div className="result-audit-link"><span>Run recorded · {research.request_id}</span><InternalLink to={"/admin/audits/" + encodeURIComponent(research.request_id)} navigate={navigate}>View query trace →</InternalLink></div>}
    <div className="workspace-grid"><div className="analysis-column"><SynthesisPanel research={research} isAdmin={isAdmin} loading={loading} error={error} /></div><RankedPapers papers={papers} total={research?.total_found ?? papers.length} selectedPmid={selectedPaper?.pmid} onSelect={setSelectedPaper} loading={loading} hasSearched={searched} isAdmin={isAdmin} error={error} /></div>
    <PaperDrawer key={String(selectedPaper?.pmid || "closed")} selectedPaper={selectedPaper} paperDetails={paperDetails} detailLoading={detailLoading} detailError={detailError} evidence={research?.evidence_table || []} papers={papers} active={false} onSelect={setSelectedPaper} onClose={() => setSelectedPaper(null)} isAdmin={isAdmin} />
    <footer className="research-footer"><span>Evidence Atlas / Find. Trace. Understand.</span><p>Research support, not medical advice. Review the original studies.</p></footer>
  </main>;
}

function useLoad(loader, dependencies = []) {
  const [state, setState] = useState({ loading: true, data: null, error: "" });
  useEffect(() => { let active = true; setState({ loading: true, data: null, error: "" }); loader().then(data => { if (active) setState({ loading: false, data, error: "" }); }).catch(error => { if (active) setState({ loading: false, data: null, error: errorText(error) }); }); return () => { active = false; }; }, dependencies);
  return state;
}

function PageFrame({ eyebrow, title, description, children }) { return <main className="admin-page"><div className="admin-page-header"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{children}</main>; }
function LoadingState({ state }) { return state.loading ? <p className="panel page-state" role="status">Loading…</p> : state.error ? <StatusNotice message={state.error} /> : null; }

function AuditsPage({ navigate }) {
  const [initial] = useState(() => readAuditFilters(window.location.search));
  const [query, setQuery] = useState(initial.query || ""); const [account, setAccount] = useState(initial.account || ""); const [status, setStatus] = useState(initial.status || ""); const [fromDate, setFromDate] = useState(initial.from_date || ""); const [toDate, setToDate] = useState(initial.to_date || ""); const [filters, setFilters] = useState(initial); const [offset, setOffset] = useState(initial.offset); const [refresh, setRefresh] = useState(0);
  const state = useLoad(() => listAudits(auditRequestParams(filters, offset)), [filters, offset, refresh]);
  useEffect(() => { window.history.replaceState(window.history.state, "", auditListUrl(filters, offset)); }, [filters, offset]);
  useEffect(() => { const restore = () => { const value = readAuditFilters(window.location.search); setFilters(value); setOffset(value.offset); setQuery(value.query || ""); setAccount(value.account || ""); setStatus(value.status || ""); setFromDate(value.from_date || ""); setToDate(value.to_date || ""); }; window.addEventListener("popstate", restore); return () => window.removeEventListener("popstate", restore); }, []);
  return <PageFrame eyebrow="AUDITABILITY / ALL ACCOUNTS" title="Query audit logs" description="A durable, attributed record of every research request, including rejected and failed attempts.">
    <form className="audit-filters panel" onSubmit={event => { event.preventDefault(); setOffset(0); setFilters({ ...(query ? { query } : {}), ...(account ? { account } : {}), ...(status ? { status } : {}), ...(fromDate ? { from_date: fromDate } : {}), ...(toDate ? { to_date: toDate } : {}) }); }}><label>Question contains<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search questions" /></label><label>Username<input value={account} onChange={event => setAccount(event.target.value)} placeholder="Any account" /></label><label>Status<select value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="rejected">Rejected</option><option value="interrupted">Interrupted</option></select></label><label>From date<input type="date" value={fromDate} max={toDate || undefined} onChange={event => setFromDate(event.target.value)} /></label><label>To date<input type="date" value={toDate} min={fromDate || undefined} onChange={event => setToDate(event.target.value)} /></label><button className="research-button" type="submit">Apply filters</button></form>
    <div className="page-toolbar"><p>Dates and times use {Intl.DateTimeFormat().resolvedOptions().timeZone}; the To date is inclusive.</p><button type="button" onClick={() => setRefresh(current => current + 1)} disabled={state.loading}>Refresh logs</button><button type="button" onClick={() => { setQuery(""); setAccount(""); setStatus(""); setFromDate(""); setToDate(""); setOffset(0); setFilters({}); }}>Clear filters</button></div>
    <LoadingState state={state} />
    {state.data && <><div className="table-card panel"><div className="table-heading"><h2>Recorded activity</h2><span>{state.data.total} runs</span></div><div className="table-scroll"><table><thead><tr><th>Question</th><th>Conversation / turn</th><th>Account</th><th>Operation</th><th>Status</th><th>Answer</th><th>Time</th><th>Duration</th><th></th></tr></thead><tbody>{state.data.items.map(item => { const auditPath = "/admin/audits/" + encodeURIComponent(item.id) + window.location.search; return <tr key={item.id}><td className="query-cell">{item.query || "No question submitted"}</td><td>{item.conversation_id ? <><InternalLink to={"/admin/research/" + encodeURIComponent(item.conversation_id)} navigate={navigate}>Open conversation</InternalLink><br /><InternalLink to={auditPath} navigate={navigate}>{item.turn_id ? `Turn ${item.turn_id.slice(0, 8)}` : "Turn"}</InternalLink></> : "—"}</td><td>{item.username}</td><td>{item.operation}</td><td><span className={"status-pill status-pill-" + item.status}>{item.status}</span></td><td>{item.answer_status || "—"}</td><td>{auditDate(item.started_at)}</td><td>{item.duration_ms == null ? "—" : auditDuration(item.duration_ms)}</td><td><InternalLink to={auditPath} navigate={navigate}>View trace</InternalLink></td></tr>; })}</tbody></table></div>{state.data.items.length === 0 && <p className="empty-list">No query runs match these filters.</p>}</div><div className="pagination"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button><span>{state.data.total ? `${offset + 1}–${Math.min(offset + 25, state.data.total)} of ${state.data.total}` : "0 runs"}</span><button disabled={offset + 25 >= state.data.total} onClick={() => setOffset(offset + 25)}>Next</button></div></>}
  </PageFrame>;
}

function AuditDetailPage({ id, navigate }) {
  const state = useLoad(() => getAudit(id), [id]); const run = state.data;
  const summary = run && {
    conversation_id: run.conversation_id, turn_id: run.turn_id, agent_action: run.agent_action,
    agent_complexity_hint: run.agent_complexity_hint, rule_route: run.rule_route,
    final_route: run.final_route, answer_status: run.answer_status,
    correction_count: run.correction_count, request_duration: auditDuration(run.duration_ms),

  };
  return <PageFrame eyebrow="AUDITABILITY / QUERY TRACE" title="Query trace" description="Request context, pipeline events, response snapshot, and citation checks for this run."><InternalLink className="back-link" to={"/admin/audits" + window.location.search} navigate={navigate}>← All audit logs</InternalLink><LoadingState state={state} />{run && <><div className="detail-summary panel"><div><span className="eyebrow">QUESTION</span><h2>{run.query || "No question submitted"}</h2><p>Requested by {run.username} · {run.operation} · {run.started_at ? auditDate(run.started_at) : "Time not recorded"}</p></div><span className={"status-pill status-pill-" + run.status}>{run.status}</span></div>{run.error && <StatusNotice message={run.error} />}<div className="detail-grid"><Facts title="Conversation trace summary" value={summary} empty="No linked conversation metadata" /><Facts title="Evidence gaps" value={{ gaps: run.evidence_gaps || [] }} empty="No evidence gaps recorded" /><Facts title="Requested controls" value={run.requested_controls} empty="No advanced controls requested" /><Facts title="Applied controls" value={run.applied_controls} empty="No advanced controls applied" /><Facts title="Citation validation" value={run.trace?.citation_audit} empty="No citation check was recorded" /></div><AuditGeneration run={run} />{run.conversation_id || run.turn_id ? <ConversationTimeline events={run.events} mode={run.trace?.execution_mode} action={run.agent_action} /> : <Timeline events={run.events} />}<EvidenceSnapshot response={run.response} /></>}</PageFrame>;
}

function ObservabilityPage() {
  const [days, setDays] = useState(30); const state = useLoad(() => getObservability(days), [days]); const data = state.data;
  return <PageFrame eyebrow="SYSTEM / OBSERVABILITY" title="System observability" description="A focused view of research traffic, outcomes, and processing time across all accounts."><div className="page-toolbar"><label>Period <select value={days} onChange={event => setDays(Number(event.target.value))}><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option></select></label></div><LoadingState state={state} />{data && <><div className="metric-grid"><article className="panel metric-card"><span>Total queries</span><strong>{data.total_queries}</strong><small>Last {days} days</small></article><article className="panel metric-card"><span>Average time</span><strong>{data.average_duration_ms == null ? "—" : `${Math.round(data.average_duration_ms)} ms`}</strong><small>Completed and attempted runs</small></article><article className="panel metric-card"><span>95th percentile</span><strong>{data.p95_duration_ms == null ? "—" : `${Math.round(data.p95_duration_ms)} ms`}</strong><small>End-to-end processing</small></article></div><div className="metric-breakdown"><section className="panel"><h2>Outcomes</h2>{Object.entries(data.by_status || {}).map(([label, value]) => <div className="breakdown-row" key={label}><span>{label}</span><strong>{value}</strong></div>)}</section><section className="panel"><h2>Request types</h2>{Object.entries(data.by_operation || {}).map(([label, value]) => <div className="breakdown-row" key={label}><span>{label}</span><strong>{value}</strong></div>)}</section></div></>}</PageFrame>;
}

function AccountRow({ item, onToggle, onReset, onRole }) {
  const [resetOpen, setResetOpen] = useState(false);
  const [temporaryPassword, setTemporaryPassword] = useState("");
  return <tr><td><strong>{item.display_name}</strong><small>{item.username}</small></td><td><select className="row-role" aria-label={`Role for ${item.username}`} value={item.role} onChange={event => onRole(item, event.target.value)}><option value="user">User</option><option value="admin">Administrator</option></select></td><td>{item.active ? "Active" : "Disabled"}{item.must_change_password ? " · Password change due" : ""}</td><td><div className="row-actions"><button type="button" onClick={() => setResetOpen(value => !value)}>{resetOpen ? "Cancel reset" : "Reset password"}</button><button type="button" onClick={() => onToggle(item)}>{item.active ? "Disable" : "Enable"}</button></div>{resetOpen && <form className="reset-form" onSubmit={async event => { event.preventDefault(); if (await onReset(item, temporaryPassword)) { setTemporaryPassword(""); setResetOpen(false); } }}><label htmlFor={`reset-${item.id}`}>New temporary password</label><input id={`reset-${item.id}`} type="password" autoComplete="new-password" value={temporaryPassword} onChange={event => setTemporaryPassword(event.target.value)} required minLength={12} /><button className="research-button" type="submit">Save reset</button></form>}</td></tr>;
}

function AccountsPage() {
  const [version, setVersion] = useState(0); const [offset, setOffset] = useState(0); const pageSize = 25; const state = useLoad(() => listAccounts({ offset, limit: pageSize }), [version, offset]); const [form, setForm] = useState({ username: "", display_name: "", role: "user", temporary_password: "" }); const [error, setError] = useState(""); const [notice, setNotice] = useState(""); const [busy, setBusy] = useState(false);
  async function create(event) { event.preventDefault(); setBusy(true); setError(""); setNotice(""); try { await createAccount(form); setForm({ username: "", display_name: "", role: "user", temporary_password: "" }); setNotice("Account created. Share the temporary password securely; it will not be shown again."); setVersion(version + 1); } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); } }
  async function toggle(item) { setError(""); setNotice(""); try { await updateAccount(item.id, { active: !item.active }); setVersion(version + 1); } catch (failure) { setError(errorText(failure)); } }
  async function reset(item, temporary_password) { try { await updateAccount(item.id, { temporary_password }); setNotice("Temporary password set. Share it securely with the account holder."); setVersion(value => value + 1); return true; } catch (failure) { setError(errorText(failure)); return false; } }
  async function changeRole(item, role) { try { await updateAccount(item.id, { role }); setNotice(`${item.username} is now ${role === "admin" ? "an administrator" : "a user"}.`); setVersion(value => value + 1); } catch (failure) { setError(errorText(failure)); } }
  return <PageFrame eyebrow="ACCESS / ADMINISTRATION" title="Accounts" description="Create invitation-free accounts, manage access, and require a password change at first sign-in."><div className="account-layout"><section className="panel account-form"><h2>Create an account</h2><p>No public sign-up is available. New users receive a temporary password from an administrator.</p><form onSubmit={create}><label>Username<input value={form.username} onChange={event => setForm({ ...form, username: event.target.value })} required /></label><label>Display name<input value={form.display_name} onChange={event => setForm({ ...form, display_name: event.target.value })} required /></label><label>Role<select value={form.role} onChange={event => setForm({ ...form, role: event.target.value })}><option value="user">User</option><option value="admin">Administrator</option></select></label><label>Temporary password<input type="password" minLength={12} autoComplete="new-password" value={form.temporary_password} onChange={event => setForm({ ...form, temporary_password: event.target.value })} required /></label><button className="research-button" disabled={busy}>Create account</button></form><StatusNotice message={error} />{notice && <p role="status" className="success-notice">{notice}</p>}</section><section className="panel table-card"><div className="table-heading"><h2>People with access</h2><span>{state.data?.total ?? "—"} accounts</span></div><LoadingState state={state} />{state.data && <><div className="table-scroll"><table><thead><tr><th>Account</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead><tbody>{state.data.items.map(item => <AccountRow key={item.id} item={item} onToggle={toggle} onReset={reset} onRole={changeRole} />)}</tbody></table></div><div className="pagination"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button><span>{state.data.total ? `${offset + 1}–${Math.min(offset + pageSize, state.data.total)} of ${state.data.total}` : "0 accounts"}</span><button disabled={offset + pageSize >= state.data.total} onClick={() => setOffset(offset + pageSize)}>Next</button></div></>}</section></div></PageFrame>;
}

export default function App() {
  const [path, navigate] = usePath(); const [account, setAccount] = useState(undefined); const [health, setHealth] = useState("checking"); const [authError, setAuthError] = useState("");
  const [filters, setFilters] = useState({ yearMin: "", yearMax: "", studyType: "", maxLoops: 2 });
  const isAdminForRoute = account?.role === "admin";
  const researchBaseForRoute = isAdminForRoute ? "/admin/research" : "/research";
  const normalizedPath = !isAdminForRoute && path.startsWith("/admin") ? "/research" : path;
  const researchConversationId = normalizedPath.startsWith(researchBaseForRoute + "/") ? decodeURIComponent(normalizedPath.slice(researchBaseForRoute.length + 1)) : null;
  const evidenceWorkspace = useEvidenceWorkspace(researchConversationId);
  useEffect(() => {
    let active = true;
    let healthTimer;
    getSession().then(result => { if (active) setAccount(result.account); }).catch(() => { if (active) setAccount(null); });
    async function refreshHealth() {
      let healthy = false;
      try {
        const result = await getHealth();
        healthy = result.status === "healthy";
        if (active) setHealth(healthy ? "online" : "degraded");
      } catch {
        if (active) setHealth("offline");
      }
      if (active) healthTimer = window.setTimeout(refreshHealth, healthy ? 30000 : 3000);
    }
    refreshHealth();
    return () => { active = false; window.clearTimeout(healthTimer); };
  }, []);
  useEffect(() => { const expired = () => { setAccount(null); navigate("/login"); }; window.addEventListener("evidence-session-expired", expired); return () => window.removeEventListener("evidence-session-expired", expired); }, []);
  useEffect(() => {
    if (!account || account.must_change_password) return;
    if (account.role !== "admin" && (path.startsWith("/admin") || path === "/login" || path === "/")) navigate("/research");
    if (account.role === "admin" && (path === "/login" || path === "/" || path === "/research")) navigate("/admin/research");
  }, [account, path]);
  async function signOut() { setAuthError(""); try { await logout(); setAccount(null); navigate("/login"); } catch (error) { setAuthError(`Could not sign out: ${errorText(error)}`); } }
  if (account === undefined) return <div className="boot-screen" role="status">Opening Evidence Atlas…</div>;
  if (!account) return <LoginPage onLogin={value => { setAccount(value); navigate(value.must_change_password ? "/account/password" : value.role === "admin" ? "/admin/research" : "/research"); }} />;
  if (account.must_change_password || path === "/account/password") return <PasswordPage required={!!account.must_change_password} onDone={() => { setAccount(null); navigate("/login"); }} />;
  const isAdmin = account.role === "admin";
  const activePath = !isAdmin && path.startsWith("/admin") ? "/research" : path;
  const researchBase = isAdmin ? "/admin/research" : "/research";
  const researchId = activePath.startsWith(researchBase + "/") ? decodeURIComponent(activePath.slice(researchBase.length + 1)) : null;
  const inConversationWorkspace = activePath === researchBase || !!researchId;
  const evaluationRunMatch = activePath.match(/^\/admin\/evaluations\/([^/]+)$/);
  return <div className={"app-shell " + (isAdmin ? "admin-shell" : "user-shell")}><a className="skip-link" href="#main-content">Skip to main content</a><TopBar health={health} apiUrl={API_BASE_URL} isAdmin={isAdmin} account={account} onLogout={signOut} evidenceWorkspace={evidenceWorkspace} evidenceSourceCount={evidenceWorkspace.tabs.length - 1} showEvidenceWorkspace={inConversationWorkspace} /><StatusNotice message={authError} /><div id="main-content" className={inConversationWorkspace ? `evidence-layout${evidenceWorkspace.isOpen ? " evidence-is-open" : ""}` : undefined} style={inConversationWorkspace ? { "--evidence-workspace-width": `${evidenceWorkspace.panelWidth}px` } : undefined}>{isAdmin && <nav className="admin-nav" aria-label="Administrator"><InternalLink to="/admin/research" navigate={navigate} className={activePath === "/admin/research" || activePath.startsWith("/admin/research/") || activePath === "/" ? "active" : ""}>Research</InternalLink><InternalLink to="/admin/audits" navigate={navigate} className={activePath.startsWith("/admin/audits") ? "active" : ""}>Audit logs</InternalLink><InternalLink to="/admin/observability" navigate={navigate} className={activePath === "/admin/observability" ? "active" : ""}>Observability</InternalLink><InternalLink to="/admin/evaluations" navigate={navigate} className={activePath.startsWith("/admin/evaluations") ? "active" : ""}>Evaluations</InternalLink><InternalLink to="/admin/accounts" navigate={navigate} className={activePath === "/admin/accounts" ? "active" : ""}>Accounts</InternalLink></nav>}{isAdmin && evaluationRunMatch ? <EvaluationDashboard runId={decodeURIComponent(evaluationRunMatch[1])} navigate={navigate} /> : isAdmin && activePath === "/admin/evaluations" ? <EvaluationDashboard navigate={navigate} /> : isAdmin && activePath.startsWith("/admin/audits/") ? <AuditDetailPage id={decodeURIComponent(activePath.split("/").pop())} navigate={navigate} /> : isAdmin && activePath === "/admin/audits" ? <AuditsPage navigate={navigate} /> : isAdmin && activePath === "/admin/observability" ? <ObservabilityPage /> : isAdmin && activePath === "/admin/accounts" ? <AccountsPage /> : activePath === researchBase || researchId ? <ConversationWorkspace conversationId={researchId} isAdmin={isAdmin} navigate={navigate} evidenceWorkspace={evidenceWorkspace} /> : <ResearchPage isAdmin={isAdmin} navigate={navigate} filters={filters} setFilters={setFilters} />}{inConversationWorkspace && <EvidenceWorkspace workspace={evidenceWorkspace} />}</div></div>;
}
