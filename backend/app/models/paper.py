"""
backend/app/models/paper.py
Canonical Pydantic models for PubMed paper metadata, indexing, and retrieval.
Satisfies: FEAT-R2-01, FEAT-R2-02, FEAT-R2-03.
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class StudyType(str, Enum):
    """Controlled vocabulary for biomedical study designs."""
    RCT = "Randomized Controlled Trial"
    SYSTEMATIC_REVIEW = "Systematic Review"
    META_ANALYSIS = "Meta-Analysis"
    OBSERVATIONAL = "Observational"
    CLINICAL_TRIAL = "Clinical Trial"
    REVIEW = "Review"
    PRECLINICAL = "Preclinical Study"
    OTHER = "Other"


class Paper(BaseModel):
    """Canonical representation of an ingested and cleaned PubMed paper."""
    model_config = ConfigDict(coerce_numbers_to_str=True, frozen=True)

    pmid: str = Field(..., description="Unique PubMed Identifier (string of digits)")
    title: str = Field(..., description="Normalized paper title")
    abstract: str = Field(default="", description="Normalized abstract text")
    embedding_text: str = Field(..., description="Combined Title + Abstract used for dense encoding")
    authors: List[str] = Field(default_factory=list, description="List of author names")
    journal: str = Field(default="", description="Journal name or ISO abbreviation")
    pubdate_raw: str = Field(default="", description="Raw date string from source")
    publication_date: Optional[str] = Field(default=None, description="ISO formatted date (YYYY-MM-DD or YYYY-01-01)")
    year: Optional[int] = Field(default=None, description="Standardized 4-digit publication year")
    mesh_terms: List[str] = Field(default_factory=list, description="Normalized MeSH base descriptors")
    mesh_qualifiers: List[str] = Field(default_factory=list, description="MeSH descriptors with subheadings")
    keywords: List[str] = Field(default_factory=list, description="Author-provided keywords")
    publication_types: List[str] = Field(default_factory=list, description="Raw publication type strings")
    study_type: str = Field(default=StudyType.OTHER.value, description="Standardized study design category")
    doi: Optional[str] = Field(default=None, description="Digital Object Identifier")


class PaperMetadata(BaseModel):
    """Lightweight metadata payload stored in Qdrant and used in UI paper cards."""
    model_config = ConfigDict(coerce_numbers_to_str=True)

    pmid: str
    title: str
    year: Optional[int] = None
    publication_date: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    journal: str = ""
    study_type: str = StudyType.OTHER.value
    mesh_terms: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    doi: Optional[str] = None
