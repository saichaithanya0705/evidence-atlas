"""Strict dependency-aware research-plan contracts."""

from __future__ import annotations

import re
from enum import Enum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Literal


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class CoverageStatus(str, Enum):
    UNCOVERED = "UNCOVERED"
    PARTIAL = "PARTIAL"
    COVERED = "COVERED"
    BLOCKED = "BLOCKED"


class ResearchSubquestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^sq-[1-8]$")
    question: str = Field(min_length=1, max_length=500)
    purpose: str = Field(min_length=1, max_length=120)
    dependencies: list[str] = Field(default_factory=list, max_length=8)
    required_concepts: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("question", "purpose")
    @classmethod
    def trim_text(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned

    @field_validator("dependencies", "required_concepts")
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = _clean(raw)
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result


class SubquestionCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subquestion_id: str = Field(pattern=r"^sq-[1-8]$")
    status: CoverageStatus = CoverageStatus.UNCOVERED
    supporting_pmids: list[str] = Field(default_factory=list, max_length=100)
    missing_concepts: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(default="", max_length=300)

    @field_validator("supporting_pmids", "missing_concepts")
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = _clean(raw)
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        return _clean(value)


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_question: str = Field(min_length=1, max_length=4000)
    route: Literal["SIMPLE", "MODERATE", "COMPLEX"]
    max_query_budget: int = Field(ge=1, le=8)
    subquestions: list[ResearchSubquestion] = Field(min_length=1, max_length=8)

    @field_validator("root_question")
    @classmethod
    def trim_root_question(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("root_question must not be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_graph(self):
        ids = [node.id for node in self.subquestions]
        if len(ids) != len(set(ids)):
            raise ValueError("subquestion IDs must be unique")
        known = set(ids)
        for node in self.subquestions:
            if node.id in node.dependencies:
                raise ValueError("research-plan dependency cycle detected")
            unknown = [dependency for dependency in node.dependencies if dependency not in known]
            if unknown:
                raise ValueError(f"unknown subquestion dependencies: {unknown}")

        visiting: set[str] = set()
        visited: set[str] = set()
        dependencies = {node.id: node.dependencies for node in self.subquestions}

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("research-plan dependency cycle detected")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in dependencies[node_id]:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in ids:
            visit(node_id)
        return self

    def ready_subquestions(
        self,
        coverage: Mapping[str, SubquestionCoverage],
    ) -> list[ResearchSubquestion]:
        """Return actionable nodes in stable plan order."""
        ready: list[ResearchSubquestion] = []
        for node in self.subquestions:
            item = coverage.get(node.id)
            status = item.status if item is not None else CoverageStatus.UNCOVERED
            if status not in {CoverageStatus.UNCOVERED, CoverageStatus.PARTIAL}:
                continue
            if all(
                coverage.get(dependency) is not None
                and coverage[dependency].status == CoverageStatus.COVERED
                for dependency in node.dependencies
            ):
                ready.append(node)
        return ready
