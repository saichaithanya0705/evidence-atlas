import { useState } from "react";

export default function ResearchComposer({ onSubmit, submitting }) {
  const [message, setMessage] = useState("");
  async function submit(event) {
    event.preventDefault();
    if (submitting || !message.trim()) return;
    const sent = message;
    const completed = await onSubmit(sent);
    if (completed) setMessage("");
  }
  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form.requestSubmit();
    }
  }
  return <form className="conversation-composer panel" onSubmit={submit}>
    <label htmlFor="conversation-message">Your research message</label>
    <textarea id="conversation-message" aria-label="Research message" value={message} onChange={event => setMessage(event.target.value)} onKeyDown={onKeyDown} placeholder="Ask a medical research question or follow up on the evidence" rows={3} maxLength={4000} />
    <div className="composer-actions"><span>Enter to send · Shift+Enter for a new line</span><button className="research-button" type="submit" disabled={submitting || !message.trim()}>{submitting ? "Researching…" : "Send"}</button></div>
  </form>;
}
