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
    NonPICOConcepts,
    PICOModel,
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

    def build_query_plan(
        self,
        raw_query: str,
        user_filters: Optional[Dict[str, Any]] = None,
        generate_embeddings: bool = False,
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
        user_filters = user_filters or {}

        # 1. FEAT-R3-01 & FEAT-R3-02: Normalize while preserving original query verbatim
        orig_q, clean_q, acronyms = self.normalizer.normalize(raw_query)

        # 2. FEAT-R3-03: MeSH Concept Identification
        mesh_terms, raw_concepts = self.mesh_identifier.identify_concepts(clean_q, orig_q, acronyms)

        # 3. FEAT-R3-05: Search Filter Extraction
        inferred_filters = self.filter_extractor.extract_filters(orig_q)
        final_year_min = user_filters.get("year_min") if user_filters.get("year_min") is not None else inferred_filters.year_min
        final_year_max = user_filters.get("year_max") if user_filters.get("year_max") is not None else inferred_filters.year_max
        final_study_types = user_filters.get("study_types") or inferred_filters.study_type_filters

        # 4. FEAT-R3-07 & FEAT-R3-08: PICO and Non-PICO Extraction
        pico = self.pico_extractor.extract(orig_q, clean_q)
        non_pico = self.non_pico_extractor.extract(orig_q, clean_q)

        # 5. FEAT-R3-09: Research Intent Classification
        intent = self.intent_classifier.classify(orig_q, clean_q, pico)

        # 6. FEAT-R3-10: Concept Weighting
        concept_weights = assign_concept_weights(pico, non_pico, mesh_terms, acronyms, self.mesh_service)
        high_priority_concepts = concept_weights.high_priority or raw_concepts or [clean_q]

        # 7. FEAT-R3-04: Canonical Query Formulation
        canonical_q = self.canonical_formulator.formulate_deterministic(
            original_query=orig_q,
            clean_query=clean_q,
            mesh_terms=mesh_terms,
            pico=pico,
            acronyms_expanded=acronyms,
        )

        # 8. FEAT-R3-11: Adaptive Complexity Routing
        routing_decision = self.router.route_query(
            query=orig_q,
            clean_query=clean_q,
            pico=pico,
            mesh_terms=mesh_terms,
            study_type_filters=final_study_types,
            year_min=final_year_min,
            year_max=final_year_max,
            intent=intent,
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
            router_confidence=routing_decision.confidence,
            router_reasoning=routing_decision.reasoning,
            subqueries=subqueries,
            embeddings=embeddings_model,
        )

        return query_plan, embeddings_model

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
