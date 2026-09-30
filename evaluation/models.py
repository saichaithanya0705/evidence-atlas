"""Typed models for the versioned biomedical relevance benchmark."""

from __future__ import annotations

from datetime import date
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RelevanceJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pmid: str = Field(min_length=1)
    title: str = Field(min_length=1)
    title_match: bool
    relevance: int = Field(ge=0, le=3)
    rationale: str = Field(min_length=20)
    source_url: str = Field(min_length=1)
    adjudicated_on: date

    @field_validator("pmid", mode="before")
    @classmethod
    def stringify_pmid(cls, value):
        return str(value)

    @field_validator("source_url")
    @classmethod
    def require_http_source(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("source_url must be an HTTPS URL")
        return value

    @model_validator(mode="after")
    def require_verified_title(self):
        if not self.title_match:
            raise ValueError("judgments must directly match the PubMed PMID and title")
        source = urlparse(self.source_url)
        if source.hostname != "pubmed.ncbi.nlm.nih.gov" or source.path.rstrip("/") != f"/{self.pmid}":
            raise ValueError("source_url must point to this PMID's PubMed record")
        return self


class BenchmarkEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    query: str = Field(min_length=5)
    category: str = Field(min_length=1)
    expected_route: Literal["SIMPLE", "MODERATE", "COMPLEX"]
    study_type: str = Field(min_length=1)
    judgments: list[RelevanceJudgment] = Field(min_length=1)
    relevant_pmids: list[str] = Field(min_length=1)

    @field_validator("relevant_pmids", mode="before")
    @classmethod
    def stringify_relevant_pmids(cls, value):
        return [str(pmid) for pmid in value]

    @model_validator(mode="after")
    def reference_fields_match_judgments(self):
        judgment_pmids = [judgment.pmid for judgment in self.judgments]
        if len(judgment_pmids) != len(set(judgment_pmids)):
            raise ValueError("judgment PMIDs must be unique within an entry")
        expected = [judgment.pmid for judgment in self.judgments if judgment.relevance > 0]
        if not expected:
            raise ValueError("each query must have at least one relevant PMID")
        if self.relevant_pmids != expected:
            raise ValueError("relevant_pmids must match judgments with relevance greater than zero")
        return self


class BenchmarkDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    corpus_path: str = Field(min_length=1)
    corpus_record_count: int = Field(gt=0)
    entries: list[BenchmarkEntry] = Field(min_length=1)
