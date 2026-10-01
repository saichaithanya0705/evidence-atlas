import { useState } from "react";

export default function ConversationList({ conversations, activeId, onSelect, onNew, loading, error }) {
  const [query, setQuery] = useState("");
  const visible = conversations.filter(item => (item.title || "New conversation").toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <section className="conversation-list panel" aria-label="Conversation list">
    <div className="conversation-list-heading"><h2>Research conversations</h2><button type="button" onClick={onNew}>Start a conversation</button></div>
    <label className="history-search">Find a conversation<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search recent titles…" /></label>
    {loading && <p role="status">Loading conversations…</p>}
    {error && <p role="alert">{error}</p>}
    {!loading && !error && conversations.length === 0 && <p className="empty-list">Your conversations will appear here.</p>}
    {!loading && !error && conversations.length > 0 && !visible.length && <p>No matching conversations in the recent list.</p>}
    <div className="conversation-list-items">{visible.map(item => <button type="button" key={item.conversation_id} aria-current={activeId === item.conversation_id ? "page" : undefined} onClick={() => onSelect(item.conversation_id)}><span>{item.title || "New conversation"}</span><span aria-hidden="true">↗</span></button>)}</div>
  </section>;
}
