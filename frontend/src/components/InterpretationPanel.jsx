import { useState } from "react";
import Icon from "./Icon.jsx";
import { formatValue } from "../utils.js";

const picoFields = [
  ["Population", "population"],
  ["Intervention", "intervention"],
  ["Comparator", "comparator"],
  ["Outcomes", "outcome"],
];

const routeLabels = {
  SIMPLE: "Focused search",
  MODERATE: "Expanded search",
  COMPLEX: "Broad search",
};

const coverageLabels = {
  COVERED: "Covered",
  PARTIAL: "Partially covered",
  UNCOVERED: "Not covered",
  BLOCKED: "Could not assess",
};

export default function InterpretationPanel({ interpretation, isAdmin = false }) {
  const [expanded, setExpanded] = useState(true);
  const pico = interpretation?.pico || {};
  const concepts = interpretation?.mesh_concepts || [];
  const subquestions = interpretation?.subquestions || [];

  return (
    <section className="panel interpretation-panel" aria-label="Research question interpretation" data-viewer={isAdmin ? "administrator" : "researcher"}>
      <div className="panel-heading">
        <button
          className="panel-title-button"
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded(value => !value)}
        >
          <Icon name="file" size={19} />
          <span>How this search was understood</span>
          <Icon name="chevron" size={16} className={"disclosure-icon" + (expanded ? " expanded" : "")} />
        </button>
        <span className="panel-heading-action" aria-hidden="true">
          <Icon name="pencil" size={15} />
          <span>Question interpretation</span>
        </span>
      </div>
      {expanded && (
        <div className="interpretation-content">
          {!interpretation ? (
            <div className="interpretation-empty">A question interpretation was not returned for this turn.</div>
          ) : (
            <div className="interpretation-grid">
              <div className="interpreted-query">
                <h3>Canonical question</h3>
                <p>{formatValue(interpretation.canonical_question, "Not returned")}</p>
              </div>
              <div className="pico-list">
                <h3>PICO concepts</h3>
                {picoFields.map(([label, key]) => (
                  <div className="pico-row" key={key}>
                    <strong>{label}</strong>
                    <span>{formatValue(pico[key])}</span>
                  </div>
                ))}
                {concepts.length > 0 && (
                  <div className="concepts-row">
                    <strong>MeSH concepts</strong>
                    <span>{formatValue(concepts)}</span>
                  </div>
                )}
              </div>
              <div className="route-summary">
                <h3>Search approach</h3>
                <div className="route-decision">
                  <span className="route-marker" />
                  <strong>{routeLabels[interpretation.route] || "Search approach not returned"}</strong>
                </div>
                {subquestions.length > 0 && (
                  <div className="planned-subquestions">
                    <h4>Planned subquestions</h4>
                    <ul>{subquestions.map(item => <li key={item.id}>{item.question}</li>)}</ul>
                  </div>
                )}
                {interpretation.coverage_statuses?.length > 0 && (
                  <div className="qualitative-coverage">
                    <h4>Evidence coverage</h4>
                    <ul>{interpretation.coverage_statuses.map(item => (
                      <li key={item.subquestion_id}>
                        <span>{subquestions.find(question => question.id === item.subquestion_id)?.question || item.subquestion_id}</span>
                        <strong>{coverageLabels[item.status] || "Status not returned"}</strong>
                      </li>
                    ))}</ul>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
