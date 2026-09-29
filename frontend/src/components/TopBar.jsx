export default function TopBar({ health, apiUrl, isAdmin, account, onLogout, evidenceWorkspace, evidenceSourceCount = 0, showEvidenceWorkspace }) {
  const statusText = health === "checking" ? "Connecting to research service" : health === "degraded" ? "Research service not ready" : health === "online" ? "Research service connected" : "Research service unavailable";
  return <header className="topbar">
    <div className="brand-lockup"><a className="brand-name" href={isAdmin ? "/admin/research" : "/research"} aria-label="Evidence Atlas home">Evidence Atlas</a><span className="brand-divider" aria-hidden="true" /><span className="brand-tagline">Find. Trace. Understand.</span></div>
    <div className="service-status"><span className={`status-dot status-${health}`} /><span>{statusText}</span>{health === "offline" && <span className="api-address" title={`Configured API: ${apiUrl}`}>{apiUrl}</span>}<span className="sr-only" role="status" aria-live="polite">{statusText}</span><span className="account-label">{account?.display_name || account?.username}{isAdmin ? " · Admin" : ""}</span>
      {showEvidenceWorkspace && <button className="evidence-toggle" type="button" aria-label={`Evidence workspace, ${evidenceSourceCount} sources`} aria-expanded={evidenceWorkspace.isOpen} onClick={evidenceWorkspace.toggle}>Evidence <span>{evidenceSourceCount}</span></button>}
      <a className="account-password-link" href="/account/password">Change password</a><button className="admin-access-button" type="button" onClick={onLogout}>Sign out</button>
    </div>
  </header>;
}
