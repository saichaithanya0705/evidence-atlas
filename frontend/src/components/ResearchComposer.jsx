import { useEffect, useRef, useState } from "react";
import { STUDY_TYPE_OPTIONS } from "../utils.js";
import "./ResearchComposer.css";

const MAX_MESSAGE_LENGTH = 4000;
const currentYear = new Date().getFullYear();
const yearOptions = Array.from({ length: currentYear - 1899 }, (_, index) => currentYear - index);
const initialFilters = { yearMin: "", yearMax: "", studyType: "", maxLoops: "2" };

export default function ResearchComposer({ onSubmit, submitting, isAdmin, draft, onDraftChange, hasConversation = false }) {
  const [internalMessage, setInternalMessage] = useState(draft ?? "");
  const [filters, setFilters] = useState(initialFilters);
  const message = typeof onDraftChange === "function" ? (draft ?? "") : internalMessage;
  const latestMessage = useRef(message);

  useEffect(() => { latestMessage.current = message; }, [message]);

  function updateMessage(value) {
    latestMessage.current = value;
    if (typeof onDraftChange === "function") onDraftChange(value);
    else setInternalMessage(value);
  }

  const minYear = filters.yearMin ? Number(filters.yearMin) : null;
  const maxYear = filters.yearMax ? Number(filters.yearMax) : null;
  const yearError = minYear !== null && maxYear !== null && minYear > maxYear
    ? "The starting year must be earlier than or equal to the ending year."
    : "";
  const hasFilters = Boolean(filters.yearMin || filters.yearMax || filters.studyType || filters.maxLoops !== initialFilters.maxLoops);

  async function submit(event) {
    event.preventDefault();
    const sent = message;
    if (submitting || !sent.trim() || yearError) return;
    const controls = isAdmin ? {
      ...(filters.yearMin ? { year_min: Number(filters.yearMin) } : {}),
      ...(filters.yearMax ? { year_max: Number(filters.yearMax) } : {}),
      ...(filters.studyType ? { study_types: [filters.studyType] } : {}),
      max_loops: Number(filters.maxLoops),
    } : {};
    const completed = await onSubmit(sent, controls);
    if (completed && latestMessage.current === sent) updateMessage("");
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing && !event.nativeEvent?.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      event.currentTarget.form.requestSubmit();
    }
  }

  function resetFilters() { setFilters(initialFilters); }

  return <form className="conversation-composer panel" onSubmit={submit}>
    <label htmlFor="conversation-message">{hasConversation ? "Ask a follow-up" : "Research question"}</label>
    <textarea id="conversation-message" aria-label="Research message" value={message} onChange={event => updateMessage(event.target.value)} onKeyDown={onKeyDown} placeholder="Ask a medical research question or follow up on the evidence" rows={4} maxLength={MAX_MESSAGE_LENGTH} />
    <div className="composer-meta"><span>Enter to search · Shift+Enter for a new line</span><span aria-live="polite">{message.length}/{MAX_MESSAGE_LENGTH}</span></div>
    {isAdmin && <details className="composer-admin-controls">
      <summary>Research filters{hasFilters ? " · active" : ""}</summary>
      <div className="composer-filter-grid">
        <label htmlFor="composer-year-min">Publication year from<select id="composer-year-min" value={filters.yearMin} onChange={event => setFilters(current => ({ ...current, yearMin: event.target.value }))}><option value="">Any year</option>{yearOptions.map(year => <option key={year} value={year}>{year}</option>)}</select></label>
        <label htmlFor="composer-year-max">Publication year to<select id="composer-year-max" value={filters.yearMax} onChange={event => setFilters(current => ({ ...current, yearMax: event.target.value }))}><option value="">Current</option>{yearOptions.map(year => <option key={year} value={year}>{year}</option>)}</select></label>
        <label htmlFor="composer-study-type">Study type<select id="composer-study-type" value={filters.studyType} onChange={event => setFilters(current => ({ ...current, studyType: event.target.value }))}><option value="">All study types</option>{STUDY_TYPE_OPTIONS.map(type => <option key={type} value={type}>{type}</option>)}</select></label>
        <label htmlFor="composer-max-loops">Corrective retrieval attempts<select id="composer-max-loops" value={filters.maxLoops} onChange={event => setFilters(current => ({ ...current, maxLoops: event.target.value }))}>{[0, 1, 2, 3, 4, 5].map(count => <option key={count} value={count}>{count}</option>)}</select></label>
      </div>
      {yearError && <p className="composer-filter-error" role="alert">{yearError}</p>}
      <div className="composer-filter-summary"><span>{yearError ? "Correct the publication year range before searching." : hasFilters ? "These filters apply to the next search." : "All available evidence will be considered."}</span>{hasFilters && <button type="button" onClick={resetFilters}>Reset filters</button>}</div>
    </details>}
    <div className="composer-actions"><span className="composer-status" role="status">{submitting ? "Researching evidence…" : ""}</span><button className="research-button" type="submit" disabled={submitting || !message.trim() || Boolean(yearError)}>{submitting ? "Researching…" : "Search evidence"}</button></div>
  </form>;
}
