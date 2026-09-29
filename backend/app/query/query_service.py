"""
backend/app/query/query_service.py
Biomedical Query Understanding and QueryPlan Coordination Service.
Coordinates:
- FEAT-R3-01: Immutable Original Query Preservation
- FEAT-R3-02: Biomedical Acronym & Spelling Normalization
- FEAT-R3-03: MeSH Concept Identification
- FEAT-R3-04: Canonical Query Formulation
- FEAT-R3-05: Search Filter Extraction
- FEAT-R3-06: Dual Query Embedding Generation
- FEAT-R3-07: PICO Concept Extraction
- FEAT-R3-08: Non-PICO Biomedical Concept Extraction
- FEAT-R3-09: Research Intent Classification
- FEAT-R3-10: Concept Weighting & QueryPlan Assembly
- FEAT-R3-11: Adaptive Complexity Router
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.app.query.canonical import CanonicalQueryFormulator
from backend.app.query.embeddings import DualQueryEmbeddingGenerator
from backend.app.query.extractor import IntentClassifier, NonPICOExtractor, PICOExtractor
from backend.app.query.filter_extractor import SearchFilterExtractor
from backend.app.query.mesh_mapper import MeSHConceptIdentifier
from backend.app.query.models import (
    ComplexityRoute,
    ConceptWeights,
    DualQueryEmbeddings,
    EnhancedQuery,
    NonPICOConcepts,
    PICOModel,
    QueryFilters,
    QueryPlan,
    SearchFilters,
)
from backend.app.query.normalizer import AcronymSpellingNormalizer
from backend.app.query.router import AdaptiveComplexityRouter
from backend.app.services.mesh_service import MeshDictionaryService

logger = logging.getLogger(__name__)


def assign_concept_weights(
    pico: PICOModel,
    non_pico: Optional[NonPICOConcepts],
    mesh_terms: List[str],
    acronyms_expanded: Dict[str, str],
    mesh_service: Optional[MeshDictionaryService] = None,
) -> ConceptWeights:
    """
    Partitions concepts into must-have, high-priority, and optional tiers (FEAT-R3-10).
    Ensures hybrid retrieval prioritizes mandatory clinical intent over semantic expansions.
    """
    must_have: List[str] = []
    high_priority: List[str] = []
    optional: List[str] = []

    # 1. Must-Have Concepts (Core population + primary interventions)
    if pico.population:
        must_have.append(pico.population.strip())
    elif non_pico and non_pico.disease_topic:
        must_have.append(non_pico.disease_topic.strip())

    if pico.intervention:
        must_have.append(pico.intervention.strip())
    elif non_pico and non_pico.treatment:
        must_have.append(non_pico.treatment.strip())

    if pico.comparator:
        must_have.append(pico.comparator.strip())

    # 2. High-Priority Concepts (Endpoints, controlled MeSH terms, acronym expansions)
    if pico.outcome:
        high_priority.append(pico.outcome.strip())
    elif non_pico and non_pico.outcome:
        high_priority.append(non_pico.outcome.strip())

    for term in mesh_terms:
        if term not in must_have and term not in high_priority:
            high_priority.append(term)

    for expansion in acronyms_expanded.values():
        if expansion not in must_have and expansion not in high_priority:
            high_priority.append(expansion)

    # 3. Optional Concepts (Synonyms and related terms)
    if mesh_service:
        for term in mesh_terms:
            synonyms = mesh_service.get_synonyms(term)
            for syn in synonyms:
                if syn not in must_have and syn not in high_priority and syn not in optional:
                    optional.append(syn)

    # Deduplicate while preserving order (case-insensitive)
    def dedupe(items: List[str]) -> List[str]:
        seen = set()
        result = []
        for x in items:
            key = x.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(x.strip())
        return result

    return ConceptWeights(
        must_have=dedupe(must_have),
        high_priority=dedupe(high_priority),
        optional=dedupe(optional),
    )


def generate_subqueries_for_route(
    clean_query: str,
    canonical_query: str,
    route: ComplexityRoute,
    pico: PICOModel,
    intent: str,
) -> List[str]:
    """Generates route-appropriate retrieval subqueries."""
    if route == "SIMPLE":
        return [clean_query]

    if route == "MODERATE":
        subs = [clean_query, canonical_query]
        if pico.population and pico.intervention:
            subs.append(f"{pico.intervention} in {pico.population} clinical outcomes")
        else:
            subs.append(f"{clean_query} clinical outcomes and trials")
        return subs[:3]

    # COMPLEX Route (comparative or mechanistic)
    subs = []
    if pico.intervention and pico.comparator:
        pop = pico.population or "patients"
        subs.append(f"{pico.intervention} in {pop}")
        subs.append(f"{pico.comparator} in {pop}")
        subs.append(f"Comparative efficacy and safety of {pico.intervention} versus {pico.comparator}")
        subs.append(canonical_query)
    elif intent == "mechanism":
        subs.append(clean_query)
        subs.append(f"{clean_query} downstream signaling pathways")
        subs.append(f"{clean_query} secondary resistance mutations")
        subs.append(canonical_query)
    else:
        subs.append(clean_query)
        subs.append(canonical_query)
        subs.append(f"{clean_query} clinical trials and evidence")
        subs.append(f"{clean_query} systematic review")

    return subs[:4]


class QueryAnalysisService:
    """
    Coordinates end-to-end biomedical query understanding, structured concept extraction,
    concept weighting, dual embeddings, and adaptive complexity routing.
    """

    def __init__(
        self,
        normalizer: Optional[AcronymSpellingNormalizer] = None,
        mesh_identifier: Optional[MeSHConceptIdentifier] = None,
        filter_extractor: Optional[SearchFilterExtractor] = None,
        pico_extractor: Optional[PICOExtractor] = None,
        non_pico_extractor: Optional[NonPICOExtractor] = None,
        intent_classifier: Optional[IntentClassifier] = None,
        canonical_formulator: Optional[CanonicalQueryFormulator] = None,
        embedding_generator: Optional[DualQueryEmbeddingGenerator] = None,
        router: Optional[AdaptiveComplexityRouter] = None,
        mesh_service: Optional[MeshDictionaryService] = None,
    ):
        self.normalizer = normalizer or AcronymSpellingNormalizer()
        self.mesh_service = mesh_service or MeshDictionaryService()
        self.mesh_identifier = mesh_identifier or MeSHConceptIdentifier(self.mesh_service)
        self.filter_extractor = filter_extractor or SearchFilterExtractor()
        self.pico_extractor = pico_extractor or PICOExtractor()
        self.non_pico_extractor = non_pico_extractor or NonPICOExtractor()
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.canonical_formulator = canonical_formulator or CanonicalQueryFormulator()
        self.embedding_generator = embedding_generator or DualQueryEmbeddingGenerator()
        self.router = router or AdaptiveComplexityRouter()

    @staticmethod
    def _coerce_filters(filters: Any) -> Optional[QueryFilters]:
        if filters is None:
            return None
        if hasattr(filters, "model_dump"):
            data = filters.model_dump(exclude_none=True)
        else:
            data = dict(filters)
        if "study_type_filters" not in data and "study_types" in data:
            data["study_type_filters"] = data.pop("study_types")
        return QueryFilters(**data)

    def _prepare_enhancement(
        self,
        raw_query: str,
        *,
        agent_rewrite: Optional[str] = None,
        explicit_filters: Any = None,
    ) -> EnhancedQuery:
        combined_query = raw_query
        notes = ["Preserved the verbatim user query."]
        if agent_rewrite and agent_rewrite.strip():
            combined_query = f"{raw_query} {agent_rewrite.strip()}"
            notes.append("Added the agent rewrite alongside the raw query for concept coverage.")

        # Analyze both inputs together so a rewrite cannot erase concepts from
        # the user's original wording.
        _, clean_q, acronyms = self.normalizer.normalize(combined_query)
        mesh_terms, raw_concepts = self.mesh_identifier.identify_concepts(
            clean_q, combined_query, acronyms
        )
        inferred_filters = self.filter_extractor.extract_filters(raw_query)
        selected_filters = self._coerce_filters(explicit_filters)
        final_year_min = (
            selected_filters.year_min
            if selected_filters and selected_filters.year_min is not None
            else inferred_filters.year_min
        )
        final_year_max = (
            selected_filters.year_max
            if selected_filters and selected_filters.year_max is not None
            else inferred_filters.year_max
        )
        final_study_types = (
            selected_filters.study_type_filters
            if selected_filters and selected_filters.study_type_filters
            else inferred_filters.study_type_filters
        )
        final_filters = QueryFilters(
            year_min=final_year_min,
            year_max=final_year_max,
            study_type_filters=final_study_types,
        )

        pico = self.pico_extractor.extract(combined_query, clean_q)
        non_pico = self.non_pico_extractor.extract(combined_query, clean_q)
        intent = self.intent_classifier.classify(combined_query, clean_q, pico)
        concept_weights = assign_concept_weights(
            pico, non_pico, mesh_terms, acronyms, self.mesh_service
        )
        canonical_q = self.canonical_formulator.formulate_deterministic(
            original_query=combined_query,
            clean_query=clean_q,
            mesh_terms=mesh_terms,
            pico=pico,
            acronyms_expanded=acronyms,
        )
        for concept in concept_weights.must_have:
            if concept.casefold() not in canonical_q.casefold():
                canonical_q = f"{canonical_q}; required concept: {concept}"
                notes.append(f"Retained required concept: {concept}.")

        enhanced = EnhancedQuery(
            raw_query=raw_query,
            agent_rewrite=agent_rewrite,
            clean_query=clean_q,
            canonical_query=canonical_q,
            acronyms_expanded=acronyms,
            mesh_terms=mesh_terms,
            pico=pico,
            non_pico_concepts=non_pico,
            concepts=concept_weights.high_priority or raw_concepts or [clean_q],
            must_have_concepts=concept_weights.must_have,
            optional_expansions=concept_weights.optional,
            concept_weights=concept_weights,
            filters=final_filters,
            intent=intent,
            transformation_notes=notes,
        )
        return enhanced

    def enhance_query(
        self,
        raw_query: str,
        *,
        agent_rewrite: Optional[str] = None,
        explicit_filters: Optional[QueryFilters] = None,
    ) -> EnhancedQuery:
        """Preserve raw and rewritten text while extracting guarded query intent."""
        return self._prepare_enhancement(
            raw_query,
            agent_rewrite=agent_rewrite,
            explicit_filters=explicit_filters,
        )

    def build_query_plan(
        self,
        raw_query: str,
        user_filters: Optional[Dict[str, Any]] = None,
        generate_embeddings: bool = False,
        *,
        agent_rewrite: Optional[str] = None,
        agent_complexity_hint: Optional[str] = None,
        route_floor: Optional[str] = None,
        explicit_filters: Optional[QueryFilters] = None,
    ) -> Tuple[QueryPlan, Optional[DualQueryEmbeddings]]:
        """
        Synchronously executes the complete query understanding pipeline.

        Args:
            raw_query: Verbatim user query string.
            user_filters: Optional explicit filter overrides from user request.
            generate_embeddings: Whether to compute 768-dim MedCPT dense vectors.

        Returns:
            Tuple of (QueryPlan, Optional[DualQueryEmbeddings]).
        """
        valid_routes = {"SIMPLE", "MODERATE", "COMPLEX"}
        agent_complexity_hint = (
            str(agent_complexity_hint).strip().upper()
            if agent_complexity_hint is not None else None
        )
        route_floor = str(route_floor).strip().upper() if route_floor is not None else None
        if agent_complexity_hint not in valid_routes:
            agent_complexity_hint = None
        if route_floor not in valid_routes:
            route_floor = None
        filter_input = explicit_filters if explicit_filters is not None else user_filters
        # This structured result is both the public enhancement output and the
        # complete snapshot consumed by plan assembly and routing.
        enhanced = self.enhance_query(
            raw_query,
            agent_rewrite=agent_rewrite,
            explicit_filters=filter_input,
        )
        orig_q = raw_query
        clean_q = enhanced.clean_query
        acronyms = enhanced.acronyms_expanded
        mesh_terms = enhanced.mesh_terms
        pico = enhanced.pico
        non_pico = enhanced.non_pico_concepts
        concept_weights = enhanced.concept_weights
        high_priority_concepts = enhanced.concepts
        intent = enhanced.intent
        canonical_q = enhanced.canonical_query
        final_year_min = enhanced.filters.year_min
        final_year_max = enhanced.filters.year_max
        final_study_types = enhanced.filters.study_type_filters

        # 8. FEAT-R3-11: Adaptive Complexity Routing
        rule_decision = self.router.route_query(
            query=orig_q,
            clean_query=clean_q,
            pico=pico,
            mesh_terms=mesh_terms,
            study_type_filters=final_study_types,
            year_min=final_year_min,
            year_max=final_year_max,
            intent=intent,
        )
        routing_decision = self.router.arbitrate(
            rule_decision,
            agent_hint=agent_complexity_hint,
            route_floor=route_floor,
        )

        # 9. Subquery expansion based on routing complexity
        subqueries = generate_subqueries_for_route(
            clean_query=clean_q,
            canonical_query=canonical_q,
            route=routing_decision.route,
            pico=pico,
            intent=intent,
        )

        # 10. FEAT-R3-06: Dual Query Dense Embeddings
        embeddings_model: Optional[DualQueryEmbeddings] = None
        if generate_embeddings:
            embeddings_model = self.embedding_generator.generate_dual_model(orig_q, canonical_q)

        # 11. Assemble final complete QueryPlan
        hard_filters: Dict[str, Any] = {}
        if final_year_min is not None:
            hard_filters["year_min"] = final_year_min
        if final_year_max is not None:
            hard_filters["year_max"] = final_year_max
        if final_study_types:
            hard_filters["study_type_filters"] = final_study_types

        query_plan = QueryPlan(
            original_query=orig_q,
            clean_query=clean_q,
            canonical_query=canonical_q,
            acronyms_expanded=acronyms,
            mesh_terms=mesh_terms,
            pico=pico,
            non_pico_concepts=non_pico,
            concepts=high_priority_concepts,
            concept_weights=concept_weights,
            study_type_filters=final_study_types,
            year_min=final_year_min,
            year_max=final_year_max,
            hard_filters=hard_filters,
            intent=intent,
            route=routing_decision.route,
            agent_complexity_hint=agent_complexity_hint,
            rule_route=rule_decision.route,
            route_floor=route_floor,
            route_source=self._route_source(
                rule_decision.route,
                routing_decision.route,
                agent_complexity_hint,
                route_floor,
            ),
            router_confidence=routing_decision.confidence,
            router_reasoning=routing_decision.reasoning,
            subqueries=subqueries,
            embeddings=embeddings_model,
        )

        return query_plan, embeddings_model

    @staticmethod
    def _route_source(
        rule_route: ComplexityRoute,
        final_route: ComplexityRoute,
        agent_hint: Optional[str],
        route_floor: Optional[str],
    ) -> str:
        if final_route == rule_route:
            return "rule"
        sources = []
        if agent_hint and str(agent_hint).upper() == final_route:
            sources.append("agent_hint")
        if route_floor and str(route_floor).upper() == final_route:
            sources.append("route_floor")
        return "+".join(sources) or "rule"

    async def analyze(
        self,
        raw_query: str,
        user_filters: Optional[Dict[str, Any]] = None,
        generate_embeddings: bool = False,
    ) -> Tuple[QueryPlan, Optional[DualQueryEmbeddings]]:
        """
        Asynchronously executes query understanding pipeline with potential LLM fallback.
        """
        # Build deterministic baseline
        plan, emb = self.build_query_plan(raw_query, user_filters, generate_embeddings)
        return plan, emb
