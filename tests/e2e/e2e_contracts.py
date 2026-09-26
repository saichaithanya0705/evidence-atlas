import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from typing_extensions import Literal

# ---------------------------------------------------------------------------
# Canonical Pydantic Schema Contracts (per PROJECT.md §4)
# ---------------------------------------------------------------------------
class PICOModel(BaseModel):
    population: Optional[str] = None
    intervention: Optional[str] = None
    comparator: Optional[str] = None
    outcome: Optional[str] = None


class QueryPlan(BaseModel):
    original_query: str
    clean_query: str
    canonical_query: str
    acronyms_expanded: Dict[str, str] = Field(default_factory=dict)
    mesh_terms: List[str] = Field(default_factory=list)
    pico: PICOModel = Field(default_factory=PICOModel)
    concepts: List[str] = Field(default_factory=list)
    study_type_filters: List[str] = Field(default_factory=list)
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    intent: str
    route: Literal["SIMPLE", "MODERATE", "COMPLEX"]
    router_confidence: float
    router_reasoning: str


class RetrievalCandidate(BaseModel):
    pmid: str
    title: str
    abstract: str
    journal: Optional[str] = None
    year: Optional[int] = None
    mesh_terms: List[str] = Field(default_factory=list)
    channel_ranks: Dict[str, int] = Field(default_factory=dict)
    channel_scores: Dict[str, float] = Field(default_factory=dict)
    rrf_score: float = 0.0
    reranker_score: Optional[float] = None
    graph_path: Optional[List[str]] = None
    filter_satisfied: bool = True


class EvidenceRecord(BaseModel):
    pmid: str
    title: str
    study_design: str
    population: Optional[str] = None
    intervention: Optional[str] = None
    comparator: Optional[str] = None
    outcome: Optional[str] = None
    key_findings: str
    limitations: Optional[str] = None
    supporting_text_spans: List[str] = Field(default_factory=list)


class ResearchResponse(BaseModel):
    request_id: str
    query: str
    canonical_query: str
    route: str
    synthesis: str
    evidence_table: List[EvidenceRecord]
    cited_pmids: List[str]
    citations_valid: bool
    citation_precision: float
    consensus_level: Literal["consensus", "mixed", "conflicting", "insufficient"]
    evidence_gaps: List[str] = Field(default_factory=list)
    audit_trace_url: str


# ---------------------------------------------------------------------------
# Reference Helpers & Invariant Evaluators
# ---------------------------------------------------------------------------
def extract_cited_pmids(synthesis_text: str) -> List[str]:
    """Extract all [PMID: <id>] or PMID: <id> citation instances."""
    matches = re.findall(r"PMID:\s*(\d+)", synthesis_text, re.IGNORECASE)
    return list(dict.fromkeys(matches))  # deduplicate preserving order


def verify_citation_integrity(cited_pmids: List[str], evidence_pmids: List[str]) -> Tuple[bool, float, List[str]]:
    """
    Evaluates 100% Deterministic Citation Precision:
    Cited PMIDs MUST be a subset of EvidencePack PMIDs.
    Returns: (is_valid, precision, hallucinated_pmids)
    """
    if not cited_pmids:
        return True, 1.0, []
    
    evidence_set = set(str(p).strip() for p in evidence_pmids)
    hallucinated = [p for p in cited_pmids if str(p).strip() not in evidence_set]
    valid_count = len(cited_pmids) - len(hallucinated)
    precision = valid_count / len(cited_pmids)
    is_valid = (len(hallucinated) == 0) and (precision == 1.0)
    return is_valid, precision, hallucinated


def compute_rrf_score(channel_rankings: Dict[str, List[str]], k: int = 60) -> Dict[str, float]:
    """
    Reciprocal Rank Fusion over multiple channels.
    RRF(d) = sum_{channel} (1.0 / (k + rank_{channel}(d)))
    """
    scores: Dict[str, float] = {}
    for channel, pmid_list in channel_rankings.items():
        for rank_idx, pmid in enumerate(pmid_list, start=1):
            scores[pmid] = scores.get(pmid, 0.0) + (1.0 / (k + rank_idx))
    return scores


def normalize_mesh_string(raw: str) -> List[str]:
    """Splits semicolon/comma delimited MeSH strings and trims whitespace."""
    if not raw or not isinstance(raw, str):
        return []
    if ";" in raw:
        parts = raw.split(";")
    else:
        parts = raw.split(",")
    return [p.strip() for p in parts if p.strip()]


def clean_text_field(text: str) -> str:
    """Normalizes Unicode whitespace and control characters without altering clinical terminology."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()
