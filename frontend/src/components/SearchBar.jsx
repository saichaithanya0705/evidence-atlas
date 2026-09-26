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
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);

  function updateFilter(name, value) {
    setFilters((current) => ({ ...current, [name]: value }));
  }

  return (
    <section className="search-section" aria-labelledby="page-title">
      <h1 id="page-title">Search medical evidence, not just abstracts</h1>
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
        </button>
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
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          <Icon name="filter" size={18} />
          Advanced
          <Icon name="chevron" size={14} className="advanced-chevron" />
        </button>
      </form>
      {advancedOpen && (
        <div className="advanced-options">
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
    </section>
  );
}
