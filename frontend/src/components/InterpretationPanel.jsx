import { useState } from "react";
import Icon from "./Icon.jsx";
import { formatValue } from "../utils.js";

const picoFields = [
  ["Population", "population"],
  ["Intervention", "intervention"],
  ["Comparator", "comparator"],
  ["Outcomes", "outcome"],
];

export default function InterpretationPanel({ queryPlan, loading, error }) {
  const [expanded, setExpanded] = useState(true);
  const pico = queryPlan?.pico || {};
  const meshTerms = queryPlan?.mesh_terms || [];
  const concepts = queryPlan?.concepts || [];

  return (
    <section className="panel interpretation-panel">
      <div className="panel-heading">
        <button
          className="panel-title-button"
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          <Icon name="file" size={19} />
          <span>How this search was understood</span>
          <Icon name="chevron" size={16} className={"disclosure-icon" + (expanded ? " expanded" : "")} />
        </button>
        <span className="panel-heading-action" aria-hidden="true">
          <Icon name="pencil" size={15} />
          <span>Interpretation from query analysis</span>
        </span>
      </div>
      {expanded && (
        <div className="interpretation-content">
          {loading && !queryPlan ? (
            <div className="inline-state" role="status">Interpreting query…</div>
          ) : error && !queryPlan ? (
            <div className="inline-state inline-error" role="alert">
              Query interpretation was unavailable: {error}
            </div>
          ) : !queryPlan ? (
            <div className="interpretation-empty">
              Run a search to inspect the normalized query, extracted PICO concepts, and route returned by the service.
            </div>
          ) : (
            <div className="interpretation-grid">
              <div className="interpreted-query">
                <h3>Natural language query</h3>
                <p>{formatValue(queryPlan.original_query, "Not returned")}</p>
                <h3 className="minor-heading">Normalized query</h3>
                <p>{formatValue(queryPlan.canonical_query, "Not returned")}</p>
              </div>
              <div className="pico-list">
                <h3>PICO terms (extracted)</h3>
                {picoFields.map(([label, key]) => (
                  <div className="pico-row" key={key}>
                    <strong>{label}</strong>
                    <span>{formatValue(pico[key])}</span>
                  </div>
                ))}
                {(meshTerms.length > 0 || concepts.length > 0) && (
                  <div className="concepts-row">
                    <strong>MeSH / concepts</strong>
                    <span>{formatValue([...meshTerms, ...concepts])}</span>
                  </div>
                )}
              </div>
              <div className="route-summary">
                <h3>Search route</h3>
                <div className="route-decision">
                  <span className="route-marker" />
                  <strong>{formatValue(queryPlan.route, "Not returned")}</strong>
                  {Number.isFinite(Number(queryPlan.router_confidence)) && (
                    <span>{Math.round(Number(queryPlan.router_confidence) * 100)}% confidence</span>
                  )}
                </div>
                <p>{formatValue(queryPlan.router_reasoning, "No route explanation was returned.")}</p>
                {queryPlan.intent && <p className="route-intent">Intent: {queryPlan.intent}</p>}
                {queryPlan.subqueries?.length > 0 && (
                  <details className="subquery-details">
                    <summary>View expanded queries ({queryPlan.subqueries.length})</summary>
                    <ul>{queryPlan.subqueries.map((item, index) => <li key={index}>{item}</li>)}</ul>
                  </details>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
