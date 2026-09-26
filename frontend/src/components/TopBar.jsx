import Icon from "./Icon.jsx";

export default function TopBar({ health, apiUrl, isAdmin, onAdmin, onLogout }) {
  const statusText = health === "checking"
    ? "Connecting to research service"
    : health === "online"
      ? "Research service connected"
      : "Research service unavailable";

  return (
    <header className="topbar">
      <div className="brand-lockup">
        <a className="brand-name" href="/" aria-label="Evidence Atlas home">Evidence Atlas</a>
        <span className="brand-divider" aria-hidden="true" />
        <span className="brand-tagline">Find. Trace. Understand.</span>
      </div>
      <div className="service-status">
        <span className={"status-dot status-" + health} />
        <span>{statusText}</span>
        {health === "offline" && (
          <span className="api-address" title={"Configured API: " + apiUrl}>
            {apiUrl}
          </span>
        )}
        <span className="sr-only" role="status" aria-live="polite">{statusText}</span>
        <Icon name="pulse" size={17} />
        {isAdmin ? (
          <button className="admin-access-button is-active" type="button" onClick={onLogout}>
            Admin · Sign out
          </button>
        ) : (
          <button className="admin-access-button" type="button" onClick={onAdmin}>
            Admin access
          </button>
        )}
      </div>
    </header>
  );
}
