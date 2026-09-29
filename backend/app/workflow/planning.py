"""Deterministic research-plan generation for adaptive retrieval."""

from __future__ import annotations

import re
from typing import Iterable

from backend.app.models.research_plan import ResearchPlan, ResearchSubquestion
from backend.app.query.models import QueryPlan


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _unique(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _clean(raw)
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


class ResearchPlanner:
    """Create a bounded DAG from the router's structured query plan."""

    @staticmethod
    def _concepts(plan: QueryPlan) -> list[str]:
        weights = getattr(plan, "concept_weights", None)
        pico = getattr(plan, "pico", None)
        return _unique(
            list(getattr(weights, "must_have", []) or [])
            + list(getattr(weights, "high_priority", []) or [])
            + list(getattr(plan, "concepts", []) or [])
            + list(getattr(plan, "mesh_terms", []) or [])
            + [
                getattr(pico, "population", None),
                getattr(pico, "intervention", None),
                getattr(pico, "comparator", None),
                getattr(pico, "outcome", None),
            ]
        )[:20]

    @staticmethod
    def _single(plan: QueryPlan, budget: int) -> ResearchPlan:
        question = _clean(plan.canonical_query or plan.original_query)
        return ResearchPlan(
            root_question=plan.original_query,
            route=plan.route,
            max_query_budget=budget,
            subquestions=[
                ResearchSubquestion(
                    id="sq-1",
                    question=question,
                    purpose="primary evidence",
                    required_concepts=ResearchPlanner._concepts(plan),
                )
            ],
        )

    @staticmethod
    def _comparison(plan: QueryPlan, budget: int) -> ResearchPlan:
        pico = getattr(plan, "pico", None)
        intervention = _clean(getattr(pico, "intervention", None))
        comparator = _clean(getattr(pico, "comparator", None))
        outcome = _clean(getattr(pico, "outcome", None)) or "reported outcomes"
        if not intervention or not comparator:
            return ResearchPlanner._generic(plan, budget)
        nodes = [
            ResearchSubquestion(
                id="sq-1",
                question=f"What evidence reports {outcome} for {intervention}?",
                purpose="intervention evidence",
                required_concepts=_unique([intervention, outcome]),
            ),
            ResearchSubquestion(
                id="sq-2",
                question=f"What evidence reports {outcome} for {comparator}?",
                purpose="comparator evidence",
                required_concepts=_unique([comparator, outcome]),
            ),
            ResearchSubquestion(
                id="sq-3",
                question=f"What direct evidence compares {intervention} with {comparator} for {outcome}?",
                purpose="direct comparison evidence",
                dependencies=["sq-1", "sq-2"],
                required_concepts=_unique([intervention, comparator, outcome]),
            ),
        ]
        return ResearchPlan(
            root_question=plan.original_query,
            route=plan.route,
            max_query_budget=budget,
            subquestions=nodes[:budget],
        )

    @staticmethod
    def _mechanism(plan: QueryPlan, budget: int) -> ResearchPlan:
        concepts = ResearchPlanner._concepts(plan)
        canonical = _clean(plan.canonical_query or plan.original_query)
        nodes = [
            ResearchSubquestion(
                id="sq-1",
                question=f"What mechanisms are reported for {canonical}?",
                purpose="mechanism evidence",
                required_concepts=concepts,
            ),
            ResearchSubquestion(
                id="sq-2",
                question=f"What outcomes are reported for {canonical}?",
                purpose="outcome evidence",
                required_concepts=concepts,
            ),
            ResearchSubquestion(
                id="sq-3",
                question=f"How does the reported mechanism relate to outcomes for {canonical}?",
                purpose="mechanism-to-outcome synthesis",
                dependencies=["sq-1", "sq-2"],
                required_concepts=concepts,
            ),
        ]
        return ResearchPlan(
            root_question=plan.original_query,
            route=plan.route,
            max_query_budget=budget,
            subquestions=nodes[:budget],
        )

    @staticmethod
    def _contradiction(plan: QueryPlan, budget: int) -> ResearchPlan:
        concepts = ResearchPlanner._concepts(plan)
        canonical = _clean(plan.canonical_query or plan.original_query)
        nodes = [
            ResearchSubquestion(
                id="sq-1",
                question=f"What evidence supports the proposed finding in {canonical}?",
                purpose="supporting evidence",
                required_concepts=concepts,
            ),
            ResearchSubquestion(
                id="sq-2",
                question=f"What evidence challenges or contradicts the proposed finding in {canonical}?",
                purpose="challenging evidence",
                required_concepts=concepts,
            ),
            ResearchSubquestion(
                id="sq-3",
                question=f"Where do studies agree or conflict for {canonical}?",
                purpose="agreement and conflict synthesis",
                dependencies=["sq-1", "sq-2"],
                required_concepts=concepts,
            ),
        ]
        return ResearchPlan(
            root_question=plan.original_query,
            route=plan.route,
            max_query_budget=budget,
            subquestions=nodes[:budget],
        )

    @staticmethod
    def _generic(plan: QueryPlan, budget: int) -> ResearchPlan:
        concepts = ResearchPlanner._concepts(plan)
        subqueries = _unique(getattr(plan, "subqueries", []) or [])
        if budget < 3 or len(subqueries) < 2:
            return ResearchPlanner._single(plan, budget)
        arms = subqueries[: budget - 1]
        nodes = [
            ResearchSubquestion(
                id=f"sq-{index}",
                question=query,
                purpose="evidence arm",
                required_concepts=concepts,
            )
            for index, query in enumerate(arms, 1)
        ]
        dependencies = [node.id for node in nodes]
        nodes.append(
            ResearchSubquestion(
                id=f"sq-{len(nodes) + 1}",
                question=f"What combined evidence answers {plan.original_query}?",
                purpose="cross-arm synthesis",
                dependencies=dependencies,
                required_concepts=concepts,
            )
        )
        return ResearchPlan(
            root_question=plan.original_query,
            route=plan.route,
            max_query_budget=budget,
            subquestions=nodes,
        )

    def build(self, query_plan: QueryPlan, *, max_subqueries: int) -> ResearchPlan:
        budget = min(8, max(1, int(max_subqueries)))
        if query_plan.route != "COMPLEX" or budget < 3:
            return self._single(query_plan, budget)

        query_text = f"{query_plan.original_query} {query_plan.canonical_query}".casefold()
        intent = str(getattr(query_plan, "intent", "") or "").casefold()
        if intent == "comparison":
            return self._comparison(query_plan, budget)
        if intent == "mechanism" or "mechanism" in query_text or "pathway" in query_text:
            return self._mechanism(query_plan, budget)
        if any(term in query_text for term in ("disagree", "contradict", "conflict", "agree")):
            return self._contradiction(query_plan, budget)
        return self._generic(query_plan, budget)
