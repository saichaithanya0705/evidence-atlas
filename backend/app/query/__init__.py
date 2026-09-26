"""
backend/app/query
Biomedical Query Understanding and Adaptive Complexity Routing Subsystem (Milestone 2).
Exports:
- PICOModel, NonPICOConcepts, ConceptWeights, DualQueryEmbeddings, SearchFilters, RoutingDecision, QueryPlan
- AcronymSpellingNormalizer, CURATED_ACRONYMS
- MeSHConceptIdentifier, AUGMENTED_MESH_ALIASES
- SearchFilterExtractor
- CanonicalQueryFormulator
- DualQueryEmbeddingGenerator
- PICOExtractor, NonPICOExtractor, IntentClassifier
- AdaptiveComplexityRouter
- QueryAnalysisService, assign_concept_weights
"""
from backend.app.query.models import (
    ComplexityRoute,
    ConceptWeights,
    DualQueryEmbeddings,
    IntentCategory,
    NonPICOConcepts,
    PICOModel,
    QueryPlan,
    RoutingDecision,
    SearchFilters,
)
from backend.app.query.normalizer import (
    COLLOQUIAL_CLINICAL_PHRASES,
    CURATED_ACRONYMS,
    AcronymSpellingNormalizer,
)
from backend.app.query.mesh_mapper import (
    AUGMENTED_MESH_ALIASES,
    MeSHConceptIdentifier,
)
from backend.app.query.filter_extractor import SearchFilterExtractor
from backend.app.query.canonical import CanonicalQueryFormulator
from backend.app.query.embeddings import DualQueryEmbeddingGenerator
from backend.app.query.extractor import (
    IntentClassifier,
    NonPICOExtractor,
    PICOExtractor,
)
from backend.app.query.router import AdaptiveComplexityRouter
from backend.app.query.query_service import (
    QueryAnalysisService,
    assign_concept_weights,
    generate_subqueries_for_route,
)

__all__ = [
    # Models & Types
    "PICOModel",
    "NonPICOConcepts",
    "ConceptWeights",
    "DualQueryEmbeddings",
    "SearchFilters",
    "RoutingDecision",
    "QueryPlan",
    "IntentCategory",
    "ComplexityRoute",
    # Normalization
    "AcronymSpellingNormalizer",
    "CURATED_ACRONYMS",
    "COLLOQUIAL_CLINICAL_PHRASES",
    # MeSH Mapping
    "MeSHConceptIdentifier",
    "AUGMENTED_MESH_ALIASES",
    # Filter Extraction
    "SearchFilterExtractor",
    # Canonical Formulation
    "CanonicalQueryFormulator",
    # Dense Embeddings
    "DualQueryEmbeddingGenerator",
    # Concept & Intent Extraction
    "PICOExtractor",
    "NonPICOExtractor",
    "IntentClassifier",
    # Router
    "AdaptiveComplexityRouter",
    # Orchestrator Service
    "QueryAnalysisService",
    "assign_concept_weights",
    "generate_subqueries_for_route",
]
