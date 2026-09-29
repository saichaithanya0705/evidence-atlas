"""
backend/app/models/request_response.py
Comprehensive Pydantic models for API requests, responses, query plans,
retrieval candidates, evidence records, and research workflows.
Maintains exact compatibility with tests/e2e/e2e_contracts.py.
"""
import re
import math
from typing import Any, Dict, List, Optional, Union
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing_extensions import Literal


class AgentAction(str, Enum):
    RESEARCH = "RESEARCH"
    CLARIFY = "CLARIFY"
    ANSWER_FROM_EVIDENCE = "ANSWER_FROM_EVIDENCE"
    ABSTAIN = "ABSTAIN"


class AnswerStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"
    FAILED = "FAILED"


class PICOModel(BaseModel):
    """PICO biomedical research framework representation."""
    model_config = ConfigDict(extra="ignore")

    population: Optional[str] = Field(default=None, description="Patient population or disease group")
    intervention: Optional[str] = Field(default=None, description="Investigated treatment, drug, or exposure")
    comparator: Optional[str] = Field(default=None, description="Comparison intervention, placebo, or standard care")
    outcome: Optional[str] = Field(default=None, description="Measured clinical or surrogate endpoint")


class QueryPlan(BaseModel):
    """Structured machine-readable representation of user's research query."""
    model_config = ConfigDict(extra="ignore")

    original_query: str = Field(..., description="Preserved immutable user query string")
    clean_query: str = Field(..., description="Spelling and whitespace normalized query")
    canonical_query: str = Field(..., description="Standardized biomedical formulation")
    acronyms_expanded: Dict[str, str] = Field(default_factory=dict, description="Detected acronyms and full names")
    mesh_terms: List[str] = Field(default_factory=list, description="Controlled MeSH descriptors identified")
    pico: PICOModel = Field(default_factory=PICOModel, description="Extracted PICO components")
    concepts: List[str] = Field(default_factory=list, description="High-priority biomedical concepts")
    study_type_filters: List[str] = Field(default_factory=list, description="Target study design filters")
    year_min: Optional[int] = Field(default=None, description="Earliest publication year")
    year_max: Optional[int] = Field(default=None, description="Latest publication year")
    intent: str = Field(default="evidence_summary", description="Classified intent (comparison, effectiveness, etc.)")
    route: Literal["SIMPLE", "MODERATE", "COMPLEX"] = Field(default="SIMPLE", description="Adaptive routing decision")
    router_confidence: float = Field(default=1.0, description="Routing model confidence score [0.0-1.0]")
    router_reasoning: str = Field(default="", description="Human-readable explanation of router choice")
    subqueries: List[str] = Field(default_factory=list, description="Route-expanded subqueries for retrieval")


class RetrievalCandidate(BaseModel):
    """Retrieved candidate paper with multi-channel provenance and ranking scores."""
    model_config = ConfigDict(extra="ignore")

    pmid: str = Field(..., description="PubMed ID")
    title: str = Field(default="", description="Paper title")
    abstract: str = Field(default="", description="Paper abstract")
    journal: Optional[str] = Field(default=None, description="Journal name")
    year: Optional[int] = Field(default=None, description="Publication year")
    authors: List[str] = Field(default_factory=list, description="Author list")
    mesh_terms: List[str] = Field(default_factory=list, description="MeSH terms")
    study_type: Optional[str] = Field(default="Other", description="Study design category")
    channel_ranks: Dict[str, int] = Field(default_factory=dict, description="Rank position per channel")
    channel_scores: Dict[str, float] = Field(default_factory=dict, description="Raw score per channel")
    rrf_score: float = Field(default=0.0, description="Reciprocal Rank Fusion score")
    reranker_score: Optional[float] = Field(default=None, description="MedCPT Cross-Encoder score")
    reranker_mode: Literal["medcpt", "lexical_fallback", "not_run"] = Field(
        default="not_run", description="Ranking implementation used for this candidate"
    )
    fallback_reason: Optional[str] = Field(
        default=None, description="Why a deterministic fallback was used instead of MedCPT"
    )
    graph_path: Optional[List[str]] = Field(default=None, description="Graph path if surfaced by concept graph")
    filter_satisfied: bool = Field(default=True, description="Whether paper complies with all metadata filters")
    retrieval_iteration: Optional[int] = Field(default=None, ge=0, description="First retrieval pass that returned the paper")
    subquestion_ids: List[str] = Field(default_factory=list, description="Research subquestions targeted by retrieval passes")


class RetrievalProvenance(BaseModel):
    """Administrator-visible source ranking metadata copied without fabrication."""

    model_config = ConfigDict(extra="forbid")

    channel_ranks: Dict[str, int] = Field(default_factory=dict)
    channel_scores: Dict[str, float] = Field(default_factory=dict)
    graph_path: Optional[List[str]] = None
    rrf_score: Optional[float] = None
    filter_satisfied: bool = True
    retrieval_iteration: Optional[int] = Field(default=None, ge=0)

    @field_validator("channel_ranks")
    @classmethod
    def validate_ranks(cls, values: Dict[str, int]) -> Dict[str, int]:
        if any(not key.strip() or type(value) is not int or value < 1 for key, value in values.items()):
            raise ValueError("channel ranks require nonblank names and positive integer values")
        return dict(values)

    @field_validator("channel_scores")
    @classmethod
    def validate_scores(cls, values: Dict[str, float]) -> Dict[str, float]:
        if any(not key.strip() or not math.isfinite(float(value)) for key, value in values.items()):
            raise ValueError("channel scores must be finite and have nonblank names")
        return dict(values)

    @field_validator("rrf_score")
    @classmethod
    def validate_rrf_score(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not math.isfinite(value):
            raise ValueError("rrf_score must be finite")
        return value


class EvidenceRecord(BaseModel):
    """Structured extraction of study-level clinical and research facts from an abstract."""
    model_config = ConfigDict(extra="ignore")

    pmid: str = Field(..., description="Source paper PMID")
    title: str = Field(default="", description="Paper title")
    year: Optional[int] = Field(default=None, description="Publication year when available")
    study_design: str = Field(default="Other", description="Standardized study design")
    population: Optional[str] = Field(default=None, description="Specific population analyzed")
    intervention: Optional[str] = Field(default=None, description="Intervention or exposure administered")
    comparator: Optional[str] = Field(default=None, description="Comparator or control group")
    outcome: Optional[str] = Field(default=None, description="Reported clinical outcomes")
    key_findings: str = Field(..., description="Synthesis of primary finding from abstract")
    limitations: Optional[str] = Field(default=None, description="Noted limitations or missing endpoints")
    supporting_text_spans: List[str] = Field(default_factory=list, description="Exact quotes from abstract")
    retrieval_provenance: Optional[RetrievalProvenance] = None
    reranker_score: Optional[float] = None
    reranker_mode: Literal["medcpt", "lexical_fallback", "not_run"] = "not_run"
    subquestion_ids: List[str] = Field(default_factory=list)


class ClaimVerification(BaseModel):
    """Conservative semantic support judgment for one proposed claim."""

    model_config = ConfigDict(extra="forbid", strict=True)

    claim_index: int = Field(ge=0)
    supported: bool
    supporting_pmids: List[str]
    rationale: str = Field(max_length=300)


def _sanitize_evidence_gaps(values: List[str]) -> List[str]:
    normalized = []
    seen = set()
    for value in values[:20]:
        gap = re.sub(r"\s+", " ", str(value or "")).strip()[:500]
        if gap and gap.casefold() not in seen:
            seen.add(gap.casefold())
            normalized.append(gap)
    return normalized


class ResearchResponse(BaseModel):
    """Complete end-to-end response for an agentic literature synthesis request."""
    model_config = ConfigDict(extra="ignore")

    answer_status: AnswerStatus = Field(default=AnswerStatus.SUPPORTED)
    request_id: str = Field(..., description="Unique request identifier")
    query: str = Field(..., description="Original user query")
    canonical_query: str = Field(..., description="Normalized biomedical query formulation")
    route: str = Field(..., description="Executed adaptive route (SIMPLE/MODERATE/COMPLEX)")
    synthesis: str = Field(..., description="Evidence-grounded synthesis narrative with inline [PMID: x] citations")
    evidence_table: List[EvidenceRecord] = Field(default_factory=list, description="Structured evidence comparison")
    cited_pmids: List[str] = Field(default_factory=list, description="All PMIDs cited in synthesis")
    citations_valid: bool = Field(..., description="True if 100% of cited PMIDs exist in retrieved evidence")
    citation_precision: float = Field(..., description="Ratio of valid cited PMIDs to total cited PMIDs")
    consensus_level: Literal["consensus", "mixed", "conflicting", "insufficient"] = Field(
        default="consensus", description="Observed multi-study agreement level"
    )
    evidence_gaps: List[str] = Field(default_factory=list, description="Identified missing evidence or open questions")
    audit_trace_url: str = Field(..., description="URL or relative endpoint to inspect full execution trace")
    retrieved_papers: List[RetrievalCandidate] = Field(default_factory=list, description="Top ranked retrieved abstracts")

    @field_validator("evidence_gaps")
    @classmethod
    def sanitize_gaps(cls, values: List[str]) -> List[str]:
        return _sanitize_evidence_gaps(values)


class PublicSearchCandidate(BaseModel):
    """Paper fields safe for ordinary search responses; excludes ranking provenance."""

    model_config = ConfigDict(extra="ignore")

    pmid: str
    title: str = ""
    abstract: str = ""
    journal: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    mesh_terms: List[str] = Field(default_factory=list)
    study_type: Optional[str] = "Other"


class PublicSearchResponse(BaseModel):
    """Ordinary search results without query analysis, traces, or score details."""

    query: str
    total_results: int
    candidates: List[PublicSearchCandidate] = Field(default_factory=list)


class PublicEvidenceRecord(BaseModel):
    """Useful study summary without exact highlight spans or audit provenance."""

    model_config = ConfigDict(extra="ignore")

    pmid: str
    title: str = ""
    year: Optional[int] = None
    study_design: str = "Other"
    population: Optional[str] = None
    intervention: Optional[str] = None
    comparator: Optional[str] = None
    outcome: Optional[str] = None
    key_findings: str
    limitations: Optional[str] = None
    supporting_text_spans: List[str] = Field(default_factory=list)
    retrieval_channels: List[str] = Field(default_factory=list)
    subquestion_ids: List[str] = Field(default_factory=list)


class PublicResearchResponse(BaseModel):
    """Ordinary research results without the admin audit/ranking surface."""

    model_config = ConfigDict(extra="ignore")

    query: str
    synthesis: str
    evidence_table: List[PublicEvidenceRecord] = Field(default_factory=list)
    evidence_gaps: List[str] = Field(default_factory=list)

    @field_validator("evidence_gaps")
    @classmethod
    def sanitize_gaps(cls, values: List[str]) -> List[str]:
        return _sanitize_evidence_gaps(values)


class AdminVerifyResponse(BaseModel):
    authenticated: Literal[True] = True


# ---------------------------------------------------------------------------
# API Request & Light Response Payloads
# ---------------------------------------------------------------------------
class SearchRequest(BaseModel):
    query: str = Field(..., description="Natural language search query")
    top_k: int = Field(default=10, ge=0, le=100, description="Number of results to return")
    year_min: Optional[int] = Field(default=None, ge=1900, le=2099, description="Minimum publication year")
    year_max: Optional[int] = Field(default=None, ge=1900, le=2099, description="Maximum publication year")
    study_types: Optional[List[str]] = Field(default=None, description="Optional study design filters")
    study_type: Optional[str] = Field(default=None, description="Convenience form for one study design filter")
    route_override: Optional[Literal["SIMPLE", "MODERATE", "COMPLEX"]] = Field(default=None)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Query cannot be empty or whitespace only")
        return value

    @model_validator(mode="after")
    def validate_filters(self):
        if self.year_min is not None and self.year_max is not None and self.year_min > self.year_max:
            raise ValueError("year_min cannot be greater than year_max")
        if self.study_type and not self.study_types:
            self.study_types = [self.study_type]
        return self


class SearchResponse(BaseModel):
    query: str
    canonical_query: str
    total_found: int
    results: List[RetrievalCandidate]
    candidates: List[RetrievalCandidate] = Field(default_factory=list)
    total_results: int = 0


class AnalyzeQueryRequest(BaseModel):
    query: str

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Query cannot be empty or whitespace only")
        return value


class AnalyzeQueryResponse(BaseModel):
    query_plan: QueryPlan


class ResearchRequest(BaseModel):
    query: str = Field(..., description="Natural language medical research query")
    year_min: Optional[int] = Field(default=None, ge=1900, le=2099)
    year_max: Optional[int] = Field(default=None, ge=1900, le=2099)
    study_types: Optional[List[str]] = Field(default=None)
    study_type: Optional[str] = None
    max_loops: int = Field(default=2, ge=0, le=5, description="Maximum CRAG corrective retrieval attempts")

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Query cannot be empty or whitespace only")
        return value

    @model_validator(mode="after")
    def validate_filters(self):
        if self.year_min is not None and self.year_max is not None and self.year_min > self.year_max:
            raise ValueError("year_min cannot be greater than year_max")
        if self.study_type and not self.study_types:
            self.study_types = [self.study_type]
        return self


class PaperDetailResponse(BaseModel):
    pmid: str
    title: str
    abstract: str
    journal: str = ""
    authors: List[str] = Field(default_factory=list)
    publication_date: Optional[str] = None
    year: Optional[int] = None
    mesh_terms: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    study_type: str = "Other"
    doi: Optional[str] = None
    pubmed_url: str = ""


class TraceResponse(BaseModel):
    request_id: str
    timestamp: str
    original_query: str
    query_plan: Dict[str, Any]
    retrieval_iterations: List[Dict[str, Any]]
    final_evidence_pmids: List[str]
    synthesis_metadata: Dict[str, Any]
    citation_audit: Dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    qdrant_connected: bool
    corpus_records_loaded: int
    mesh_service_loaded: bool
    models_cached: bool
