import { useState } from "react";
import { STUDY_TYPE_OPTIONS } from "../utils.js";

const currentYear = new Date().getFullYear();
const yearOptions = Array.from({ length: currentYear - 1899 }, (_, index) => currentYear - index);

export default function ResearchComposer({ onSubmit, submitting, isAdmin }) {
  const [message, setMessage] = useState("");
  const [filters, setFilters] = useState({ yearMin: "", yearMax: "", studyType: "", maxLoops: 2 });
  async function submit(event) {
    event.preventDefault();
    if (submitting || !message.trim()) return;
    const sent = message;
    const controls = isAdmin ? {
      ...(filters.yearMin ? { year_min: Number(filters.yearMin) } : {}),
      ...(filters.yearMax ? { year_max: Number(filters.yearMax) } : {}),
      ...(filters.studyType ? { study_types: [filters.studyType] } : {}),
      max_loops: Number(filters.maxLoops),
    } : {};
    const completed = await onSubmit(sent, controls);
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
    {isAdmin && <fieldset className="composer-admin-controls"><legend>Advanced research controls</legend>
      <label>Publication year from<select aria-label="Publication year from" value={filters.yearMin} onChange={event => setFilters(current => ({ ...current, yearMin: event.target.value }))}><option value="">Any year</option>{yearOptions.map(year => <option key={year} value={year}>{year}</option>)}</select></label>
      <label>Publication year to<select aria-label="Publication year to" value={filters.yearMax} onChange={event => setFilters(current => ({ ...current, yearMax: event.target.value }))}><option value="">Current</option>{yearOptions.map(year => <option key={year} value={year}>{year}</option>)}</select></label>
      <label>Study type<select aria-label="Study type" value={filters.studyType} onChange={event => setFilters(current => ({ ...current, studyType: event.target.value }))}><option value="">All study types</option>{STUDY_TYPE_OPTIONS.map(type => <option key={type} value={type}>{type}</option>)}</select></label>
      <label>Corrective retrieval attempts<select aria-label="Corrective retrieval attempts" value={filters.maxLoops} onChange={event => setFilters(current => ({ ...current, maxLoops: event.target.value }))}>{[0, 1, 2, 3, 4, 5].map(count => <option key={count} value={count}>{count}</option>)}</select></label>
    </fieldset>}
    <div className="composer-actions"><span>Enter to send · Shift+Enter for a new line</span><button className="research-button" type="submit" disabled={submitting || !message.trim()}>{submitting ? "Researching…" : "Send"}</button></div>
  </form>;
}
