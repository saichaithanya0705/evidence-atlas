"""
backend/app/query/router.py
Adaptive Complexity Router (FEAT-R3-11).
Classifies user queries into SIMPLE, MODERATE, or COMPLEX execution routes using
a deterministic 7-rule fast path with confidence scoring (>= 0.85) and detailed reasoning (> 10 chars),
augmented with NVIDIA NIM LLM fallback for borderline cases.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from backend.app.query.models import ComplexityRoute, PICOModel, RoutingDecision

logger = logging.getLogger(__name__)

COMPARISON_REGEX = re.compile(
    r"\b(?:vs\.?|versus|compared\s+(?:with|to)|comparison\s+of|head-to-head|superiority\s+of|non-inferiority)\b",
    re.IGNORECASE
)

MECHANISM_REGEX = re.compile(
    r"\b(?:resistance\s+mechanisms?|molecular\s+pathway|bypass\s+signaling|secondary\s+mutations?|"
    r"signaling\s+cascade|downstream\s+cascade|oncogenic\s+mechanism|mutation\s+profile|"
    r"pharmacodynamics|pharmacokinetics|target\s+engagement)\b",
    re.IGNORECASE
)

HYPOTHESIS_REVERSAL_REGEX = re.compile(
    r"\b(?:revers(?:e|es|ed|ing|al)|clear(?:ance|ing)|eradica(?:te|tion)|restor(?:e|ation))\b.*"
    r"\b(?:advanced|stage|pathology|disease|damage|fibrosis|aggregation|tangles?|lesions?|deficit)\b",
    re.IGNORECASE
)

ROUTER_LLM_PROMPT = """You are an expert biomedical research query router.
Analyze the user's research query and classify it into exactly one complexity category:
- SIMPLE: Single biomedical concept, direct single-drug clinical inquiry, or factual definition lookup. Needs 1 direct hybrid retrieval pass.
- MODERATE: Multi-concept query, specific demographic cohort with temporal or study design constraints, or synonym-rich query needing 2-4 subquery expansions.
- COMPLEX: Multi-arm drug/treatment comparison ('vs', 'versus'), biological mechanism/resistance pathways, or controversial reversal hypothesis requiring decomposed subquestion DAG and iterative CRAG loops.

Output strict JSON conforming to:
{
  "route": "SIMPLE" | "MODERATE" | "COMPLEX",
  "confidence": float between 0.85 and 1.0,
  "reasoning": string of at least 15 characters explaining why this route was selected
}
"""


class AdaptiveComplexityRouter:
    """
    Adaptive Complexity Router for biomedical research queries.
    Implements 7-rule fast-path heuristics and LLM fallback (FEAT-R3-11).
    """

    def route_query(
        self,
        query: str,
        clean_query: str,
        pico: Optional[PICOModel] = None,
        mesh_terms: Optional[List[str]] = None,
        study_type_filters: Optional[List[str]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        intent: Optional[str] = None,
    ) -> RoutingDecision:
        """
        Routes query through deterministic 7-rule priority tree.

        Args:
            query: Raw user query.
            clean_query: Normalized clean query.
            pico: Extracted PICO model.
            mesh_terms: Identified MeSH terms.
            study_type_filters: Study type filters.
            year_min: Minimum publication year.
            year_max: Maximum publication year.
            intent: Classified research intent.

        Returns:
            RoutingDecision object with route, confidence, reasoning, and rule_applied.
        """
        q_raw = query.strip()
        q_clean = clean_query.strip().lower()
        words = q_raw.split()

        # Rule 1: Single-Word / Minimal Query Fast Path -> SIMPLE
        # Guaranteed by test_bva_single_word_or_minimal_queries
        if len(words) <= 1 or (len(words) == 2 and len(q_raw) <= 12):
            return RoutingDecision(
                route="SIMPLE",
                confidence=0.98,
                reasoning="Single biomedical term or minimal query; routed to direct hybrid retrieval pass.",
                rule_applied="RULE_1_SINGLE_TERM"
            )

        # Rule 2: Head-to-head comparisons require decomposition.
        is_comparative = (
            COMPARISON_REGEX.search(q_raw) is not None
            or intent == "comparison"
            or (pico is not None and pico.intervention is not None and pico.comparator is not None)
        )
        if is_comparative:
            return RoutingDecision(
                route="COMPLEX",
                confidence=0.95,
                reasoning="Multi-arm drug or intervention comparison requiring decomposed subquestions and cross-study contrast.",
                rule_applied="RULE_2_HEAD_TO_HEAD_COMPARISON"
            )

        # Rule 3: Biological mechanism/resistance questions require pathway coverage.
        is_mechanistic = (
            MECHANISM_REGEX.search(q_raw) is not None
            or intent == "mechanism"
            or "resistance" in q_clean
        )
        if is_mechanistic:
            return RoutingDecision(
                route="COMPLEX",
                confidence=0.92,
                reasoning="Biological mechanism inquiry requiring multi-pathway investigation and potential corrective search.",
                rule_applied="RULE_3_BIOLOGICAL_MECHANISM"
            )

        # Rule 4: Strong reversal hypotheses need strict evidence grading.
        is_reversal = HYPOTHESIS_REVERSAL_REGEX.search(q_raw) is not None
        if is_reversal:
            return RoutingDecision(
                route="COMPLEX",
                confidence=0.88,
                reasoning="Hypothesis testing on advanced pathology reversal requiring strict evidence grading.",
                rule_applied="RULE_4_PATHOLOGY_REVERSAL"
            )

        # Rule 5: Filtered Clinical Query Fast Path -> MODERATE
        has_temporal_filter = (year_min is not None or year_max is not None)
        has_study_type_filter = bool(study_type_filters and len(study_type_filters) > 0)
        cohort_matches = [w for w in ["pediatric", "infants", "children", "geriatric", "elderly"] if w in q_clean]
        has_cohort_filter = len(cohort_matches) > 0

        if (has_temporal_filter and (has_study_type_filter or has_cohort_filter)) or intent == "safety":
            reasons: List[str] = []
            if has_temporal_filter:
                if year_min is not None and year_max is not None:
                    reasons.append(f"temporal constraint enforcement ({year_min}-{year_max})")
                elif year_min is not None:
                    reasons.append(f"temporal constraint enforcement (after {year_min - 1})")
                else:
                    reasons.append(f"temporal constraint enforcement (up to {year_max})")
            if has_study_type_filter and study_type_filters:
                reasons.append(f"study design filtering ({', '.join(study_type_filters)})")
            if has_cohort_filter:
                reasons.append(f"demographic cohort scoping ({', '.join(cohort_matches)})")
            if intent == "safety":
                reasons.append("safety and adverse event surveillance")

            # Entity-aware expansion description
            if any(w in q_clean for w in ["vaccine", "vaccines", "mrna", "immunization"]):
                reasons.append("immunization multi-query expansion")
            elif pico and pico.intervention:
                reasons.append(f"multi-query expansion for {pico.intervention}")
            else:
                reasons.append("multi-query clinical expansion")

            reasoning = f"Filtered clinical query requiring {', '.join(reasons)}."
            return RoutingDecision(
                route="MODERATE",
                confidence=0.94,
                reasoning=reasoning,
                rule_applied="RULE_5_FILTERED_CLINICAL_QUERY"
            )

        # Rule 6: Direct single-intervention inquiries use one hybrid pass.
        is_direct_intervention = (
            (pico is not None and pico.intervention is not None and pico.comparator is None)
            or intent in ("discovery", "effectiveness")
        )
        if is_direct_intervention and not (has_temporal_filter or has_study_type_filter):
            return RoutingDecision(
                route="SIMPLE",
                confidence=0.97,
                reasoning="Direct single-intervention clinical inquiry with clear acronym expansion and fast hybrid retrieval.",
                rule_applied="RULE_6_DIRECT_INTERVENTION"
            )

        # Rule 7: Multi-Concept Synonym Expansion Query -> MODERATE
        concept_count = len(mesh_terms or [])
        if concept_count >= 3 or (len(words) >= 8 and (has_study_type_filter or has_temporal_filter)):
            return RoutingDecision(
                route="MODERATE",
                confidence=0.86,
                reasoning="Multi-concept query benefiting from multi-query synonym expansion and merged retrieval.",
                rule_applied="RULE_7_MULTI_CONCEPT_EXPANSION"
            )

        # Default fallback
        return RoutingDecision(
            route="SIMPLE",
            confidence=0.85,
            reasoning="Standard single hybrid retrieval pass for general literature exploration.",
            rule_applied="RULE_DEFAULT_SIMPLE"
        )

    async def route_with_llm_fallback(
        self,
        query: str,
        clean_query: str,
        pico: Optional[PICOModel] = None,
        mesh_terms: Optional[List[str]] = None,
        study_type_filters: Optional[List[str]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        intent: Optional[str] = None,
        llm_client: Optional[Any] = None,
        model_name: str = "meta/llama-3.3-70b-instruct",
        llm_mode: str = "mock",
    ) -> RoutingDecision:
        """
        Fast-path routing with LLM fallback for ambiguous borderline cases.
        """
        decision = self.route_query(
            query=query,
            clean_query=clean_query,
            pico=pico,
            mesh_terms=mesh_terms,
            study_type_filters=study_type_filters,
            year_min=year_min,
            year_max=year_max,
            intent=intent,
        )

        # Only invoke LLM if borderline (confidence == 0.85) and active LLM is available
        if decision.confidence <= 0.85 and llm_mode in ("nim", "openai") and llm_client:
            try:
                response = await llm_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": ROUTER_LLM_PROMPT},
                        {"role": "user", "content": f"Query: {query}"}
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    timeout=5.0
                )
                data = json.loads(response.choices[0].message.content)
                route = data.get("route", "SIMPLE")
                conf = float(data.get("confidence", 0.90))
                reasoning = data.get("reasoning", "LLM-assisted complexity routing determination.")
                if route in ("SIMPLE", "MODERATE", "COMPLEX") and len(reasoning) > 10:
                    return RoutingDecision(
                        route=route,
                        confidence=max(0.85, min(1.0, conf)),
                        reasoning=reasoning,
                        rule_applied="LLM_FALLBACK"
                    )
            except Exception as e:
                logger.warning("Router LLM fallback failed (%s); using heuristic decision.", e)

        return decision
