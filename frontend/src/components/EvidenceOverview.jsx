export default function EvidenceOverview({ sourceCount, onOpenFirst }) {
  return <section className="evidence-overview" aria-label="Evidence workspace overview">
    <span className="eyebrow">CONVERSATION SOURCES</span>
    <h2>{sourceCount ? `${sourceCount} source${sourceCount === 1 ? "" : "s"} in this conversation` : "Your evidence, in context"}</h2>
    <p>Open a citation, evidence finding, or ranked paper to keep its abstract, supporting passages, and retrieval context together.</p>
    {sourceCount > 0 ? <button type="button" onClick={onOpenFirst}>Return to the last paper</button> : <p className="drawer-muted">No papers have been opened in this conversation yet.</p>}
  </section>;
}
