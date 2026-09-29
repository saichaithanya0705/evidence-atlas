import { useState } from "react";
import { STUDY_TYPE_OPTIONS } from "../utils.js";
import Icon from "./Icon.jsx";

const currentYear = new Date().getFullYear();
const yearOptions = Array.from({ length: currentYear - 1899 }, (_, index) => currentYear - index);

export default function SearchBar({
  query,
  setQuery,
  filters,
  setFilters,
  onResearch,
  loading,
  hasSearched,
  isAdmin = false,
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);

  function updateFilter(name, value) {
    setFilters((current) => ({ ...current, [name]: value }));
  }

  return (
    <section className={"search-section" + (hasSearched ? " has-results" : "")} aria-labelledby="page-title">
      <div className="search-introduction">
        <h1 id="page-title">Medical evidence.<br /><em>A clearer perspective.</em></h1>
        <p>Ask a focused question. Explore the literature. Read the evidence in context.</p>
      </div>
      <form className="search-form" onSubmit={onResearch}>
        <div className="query-field">
          <Icon name="search" size={20} />
          <label className="sr-only" htmlFor="research-query">Research question</label>
          <input
            id="research-query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ask a medical research question"
            autoComplete="off"
            required
          />
          {query && (
            <button
              className="icon-button clear-query"
              type="button"
              aria-label="Clear research question"
              onClick={() => setQuery("")}
            >
              <Icon name="close" size={16} />
            </button>
          )}
        </div>
        <button className="research-button" type="submit" disabled={loading || !query.trim()}>
          {loading ? <span className="button-spinner" /> : null}
          {loading ? "Researching" : "Research"}
          {!loading && <Icon name="arrow" size={19} />}
        </button>
        {isAdmin && <div className="search-filters">
        <label className="filter-field">
          <span>From year</span>
          <select
            value={filters.yearMin}
            onChange={(event) => updateFilter("yearMin", event.target.value)}
            aria-label="Publication year from"
          >
            <option value="">Any year</option>
            {yearOptions.map((year) => <option key={year} value={year}>{year}</option>)}
          </select>
        </label>
        <label className="filter-field">
          <span>To year</span>
          <select
            value={filters.yearMax}
            onChange={(event) => updateFilter("yearMax", event.target.value)}
            aria-label="Publication year to"
          >
            <option value="">Current</option>
            {yearOptions.map((year) => <option key={year} value={year}>{year}</option>)}
          </select>
        </label>
        <label className="filter-field study-filter">
          <span>Study type</span>
          <select
            value={filters.studyType}
            onChange={(event) => updateFilter("studyType", event.target.value)}
            aria-label="Study type"
          >
            <option value="">All study types</option>
            {STUDY_TYPE_OPTIONS.map((studyType) => (
              <option key={studyType} value={studyType}>{studyType}</option>
            ))}
          </select>
        </label>
        <button
          className={"advanced-toggle" + (advancedOpen ? " is-open" : "")}
          type="button"
          aria-expanded={advancedOpen}
          aria-controls="advanced-options"
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          <Icon name="filter" size={18} />
          Advanced filters
          <Icon name="chevron" size={14} className="advanced-chevron" />
        </button>
        </div>}
      </form>
      {isAdmin && advancedOpen && (
        <div className="advanced-options" id="advanced-options">
          <label className="filter-field compact-field">
            <span>Corrective retrieval attempts</span>
            <select
              value={filters.maxLoops}
              onChange={(event) => updateFilter("maxLoops", Number(event.target.value))}
            >
              {[1, 2, 3, 4, 5].map((count) => (
                <option key={count} value={count}>{count}</option>
              ))}
            </select>
          </label>
          <p>The search will apply these filters and pass the requested retrieval budget to the API.</p>
        </div>
      )}
      {!hasSearched && <div className="example-questions">
        <span>Try an example question:</span>
        {["SGLT2 inhibitors and kidney outcomes", "Exercise and blood pressure"].map(example =>
          <button type="button" key={example} onClick={() => {
            setQuery(example);
            document.getElementById("research-query")?.focus();
          }}>{example}<Icon name="arrow" size={14} /></button>)}
      </div>}
    </section>
  );
}
