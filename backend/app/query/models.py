"""
backend/app/query/models.py
Pydantic data models for Biomedical Query Understanding and Adaptive Routing (Milestone 2).
Maintains full backward and forward compatibility with tests/e2e/e2e_contracts.py.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from typing_extensions import Literal


# Intent categories defined by FEAT-R3-09
IntentCategory = Literal[
    "discovery",
    "comparison",
    "effectiveness",
    "safety",
    "association",
    "mechanism",
    "evidence summary",
]

# Routing complexity categories defined by FEAT-R3-11
ComplexityRoute = Literal["SIMPLE", "MODERATE", "COMPLEX"]


class PICOModel(BaseModel):
    """
    Population, Intervention, Comparator, Outcome (PICO) framework model.
    Enforces Optional[str] with None for missing components (FEAT-R3-07).
    """
    model_config = ConfigDict(extra="ignore")

    population: Optional[str] = Field(
        default=None,
        description="Target patient population, demographic group, or clinical cohort"
    )
    intervention: Optional[str] = Field(
        default=None,
        description="Investigated therapeutic agent, procedure, or diagnostic test"
    )
    comparator: Optional[str] = Field(
        default=None,
        description="Control agent, placebo, alternative active comparator, or standard of care (None if absent)"
    )
    outcome: Optional[str] = Field(
        default=None,
        description="Clinical or biological endpoints, efficacy metrics, or adverse events"
    )


class NonPICOConcepts(BaseModel):
    """
    General biomedical research concepts for non-intervention queries (FEAT-R3-08).
    Captures disease topic, exposure, treatment, population, outcome, relationship, and study type.
    """
    model_config = ConfigDict(extra="ignore")

    disease_topic: Optional[str] = Field(default=None, description="Primary disease, organ, or condition")
    exposure: Optional[str] = Field(default=None, description="Environmental, physiological, or genetic exposure")
    treatment: Optional[str] = Field(default=None, description="Investigated therapy or procedure if mentioned")
    population: Optional[str] = Field(default=None, description="Target host demographic, animal model, or cell line")
    outcome: Optional[str] = Field(default=None, description="Biological or clinical endpoint")
    relationship: Optional[str] = Field(default=None, description="Investigated association, mechanism, or etiology")
    study_type: Optional[str] = Field(default=None, description="Target or mentioned study design methodology")


class ConceptWeights(BaseModel):
    """
    Tiered concept importance weights for hybrid retrieval (FEAT-R3-10).
    Partitions concepts into must-have, high-priority, and optional terms.
    """
    model_config = ConfigDict(extra="ignore")

    must_have: List[str] = Field(
        default_factory=list,
        description="Mandatory terms/concepts (core disease population or primary intervention) that must match"
    )
    high_priority: List[str] = Field(
        default_factory=list,
        description="Key clinical entities (outcomes, controlled MeSH descriptors, biomarkers) heavily weighted"
    )
    optional: List[str] = Field(
        default_factory=list,
        description="Helpful semantic expansions, synonyms, and related MeSH neighbors for recall broadening"
    )


class DualQueryEmbeddings(BaseModel):
    """
    Dual 768-dim dense query representations generated via MedCPT-Query-Encoder (FEAT-R3-06).
    """
    model_config = ConfigDict(extra="ignore")

    original_query_embedding: Optional[List[float]] = Field(
        default=None,
        description="768-dim L2-normalized float32 dense embedding of original user query"
    )
    canonical_query_embedding: Optional[List[float]] = Field(
        default=None,
        description="768-dim L2-normalized float32 dense embedding of canonical biomedical query"
    )


class SearchFilters(BaseModel):
    """
    Structured metadata filters parsed from query or explicitly provided by user (FEAT-R3-05).
    """
    model_config = ConfigDict(extra="ignore")

    year_min: Optional[int] = Field(default=None, description="Earliest publication year [1900-2099]")
    year_max: Optional[int] = Field(default=None, description="Latest publication year [1900-2099]")
    study_type_filters: List[str] = Field(
        default_factory=list,
        description="Standardized study designs (e.g. Randomized Controlled Trial, Systematic Review)"
    )


class RoutingDecision(BaseModel):
    """
    Structured routing decision output from Adaptive Complexity Router (FEAT-R3-11).
    """
    model_config = ConfigDict(extra="ignore")

    route: ComplexityRoute = Field(
        ...,
        description="Execution complexity route (SIMPLE, MODERATE, COMPLEX)"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score in the routing decision [0.0 - 1.0]"
    )
    reasoning: str = Field(
        ...,
        min_length=10,
        description="Human-readable justification for the routing choice"
    )
    rule_applied: Optional[str] = Field(
        default=None,
        description="Identifier of the rule or fallback mechanism triggered"
    )


class QueryPlan(BaseModel):
    """
    Structured machine-readable representation of user's research query (FEAT-R3-10).
    Maintains 100% backward compatibility with tests/e2e/e2e_contracts.py QueryPlan.
    """
    model_config = ConfigDict(extra="ignore")

    # Core Preserved & Normalized Queries (FEAT-R3-01, FEAT-R3-02, FEAT-R3-04)
    original_query: str = Field(..., description="Preserved immutable user query string")
    clean_query: str = Field(..., description="Spelling, acronym, and whitespace normalized query")
    canonical_query: str = Field(..., description="Standardized biomedical formulation")
    acronyms_expanded: Dict[str, str] = Field(default_factory=dict, description="Detected acronyms and full names")

    # Extracted Biomedical Semantics (FEAT-R3-03, FEAT-R3-07, FEAT-R3-08)
    mesh_terms: List[str] = Field(default_factory=list, description="Controlled MeSH descriptors identified")
    pico: PICOModel = Field(default_factory=PICOModel, description="Extracted PICO components")
    non_pico_concepts: Optional[NonPICOConcepts] = Field(default=None, description="Non-PICO biomedical concepts")
    concepts: List[str] = Field(default_factory=list, description="High-priority biomedical concepts")

    # Concept Weighting (FEAT-R3-10)
    concept_weights: ConceptWeights = Field(default_factory=ConceptWeights, description="Tiered concept weighting plan")

    # Search Filters & Constraints (FEAT-R3-05)
    study_type_filters: List[str] = Field(default_factory=list, description="Target study design filters")
    year_min: Optional[int] = Field(default=None, description="Earliest publication year [1900-2099]")
    year_max: Optional[int] = Field(default=None, description="Latest publication year [1900-2099]")
    hard_filters: Dict[str, Any] = Field(default_factory=dict, description="Consolidated dictionary for Qdrant payload filters")

    # Research Intent & Routing (FEAT-R3-09, FEAT-R3-11)
    intent: str = Field(
        default="evidence_summary",
        description="Classified intent (discovery, comparison, effectiveness, safety, association, mechanism, evidence summary)"
    )
    route: ComplexityRoute = Field(
        default="SIMPLE",
        description="Adaptive routing decision (SIMPLE, MODERATE, COMPLEX)"
    )
    router_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Routing model confidence score [0.0-1.0]"
    )
    router_reasoning: str = Field(
        default="",
        description="Human-readable explanation of router choice"
    )

    # Retrieval Execution Plan (FEAT-R4-01)
    subqueries: List[str] = Field(
        default_factory=list,
        description="Route-expanded subqueries for multi-channel retrieval"
    )

    # Dense Embeddings (FEAT-R3-06)
    embeddings: Optional[DualQueryEmbeddings] = Field(
        default=None,
        description="Dual 768-dim MedCPT dense query vectors"
    )
