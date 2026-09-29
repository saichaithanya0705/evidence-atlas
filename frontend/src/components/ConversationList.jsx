export default function ConversationList({ conversations, activeId, onSelect, onNew, loading, error }) {
  return <section className="conversation-list panel" aria-label="Conversation list">
    <div className="conversation-list-heading"><h2>Recent conversations</h2><button type="button" onClick={onNew}>Start a conversation</button></div>
    {loading && <p role="status">Loading conversations…</p>}
    {error && <p role="alert">{error}</p>}
    {!loading && !error && conversations.length === 0 && <p className="empty-list">Your conversations will appear here.</p>}
    <div className="conversation-list-items">{conversations.map(item => <button type="button" key={item.conversation_id} aria-current={activeId === item.conversation_id ? "page" : undefined} onClick={() => onSelect(item.conversation_id)}>{item.title || "New conversation"}</button>)}</div>
  </section>;
}
