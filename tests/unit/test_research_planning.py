import pytest
from pydantic import ValidationError

from backend.app.models.research_plan import (
    CoverageStatus,
    ResearchPlan,
    ResearchSubquestion,
    SubquestionCoverage,
)
from backend.app.models.request_response import RetrievalCandidate
from backend.app.query.models import PICOModel, QueryPlan
from backend.app.workflow.judge import EvidenceSufficiencyJudge
from backend.app.workflow.planning import ResearchPlanner


def make_query_plan(**updates) -> QueryPlan:
    values = {
        "original_query": "empagliflozin for chronic kidney disease",
        "clean_query": "empagliflozin for chronic kidney disease",
        "canonical_query": "empagliflozin for chronic kidney disease",
        "concepts": ["empagliflozin", "chronic kidney disease"],
        "route": "SIMPLE",
        "subqueries": [],
    }
    values.update(updates)
    return QueryPlan(**values)


@pytest.mark.parametrize("route", ["SIMPLE", "MODERATE"])
def test_noncomplex_routes_create_one_root_subquestion(route):
    plan = ResearchPlanner().build(make_query_plan(route=route), max_subqueries=4)

    assert plan.route == route
    assert plan.max_query_budget == 4
    assert [node.id for node in plan.subquestions] == ["sq-1"]
    assert plan.subquestions[0].dependencies == []
    assert plan.subquestions[0].question == "empagliflozin for chronic kidney disease"


def test_complex_comparison_creates_evidence_arms_before_comparison_node():
    plan = ResearchPlanner().build(
        make_query_plan(
            original_query="Compare SGLT2 inhibitors versus GLP-1 agonists for kidney outcomes",
            clean_query="Compare SGLT2 inhibitors versus GLP-1 agonists for kidney outcomes",
            canonical_query="SGLT2 inhibitors compared with GLP-1 agonists for kidney outcomes",
            route="COMPLEX",
            intent="comparison",
            pico=PICOModel(
                intervention="SGLT2 inhibitors",
                comparator="GLP-1 agonists",
                outcome="kidney outcomes",
            ),
        ),
        max_subqueries=5,
    )

    assert [(node.id, node.dependencies) for node in plan.subquestions] == [
        ("sq-1", []),
        ("sq-2", []),
        ("sq-3", ["sq-1", "sq-2"]),
    ]
    assert "SGLT2 inhibitors" in plan.subquestions[0].question
    assert "GLP-1 agonists" in plan.subquestions[1].question
    assert "compar" in plan.subquestions[2].purpose.casefold()


def test_complex_mechanism_and_contradiction_plans_are_bounded_dags():
    mechanism = ResearchPlanner().build(
        make_query_plan(
            original_query="How does KRAS G12C resistance affect sotorasib outcomes?",
            canonical_query="KRAS G12C sotorasib resistance mechanisms and outcomes",
            route="COMPLEX",
            intent="mechanism",
        ),
        max_subqueries=4,
    )
    contradiction = ResearchPlanner().build(
        make_query_plan(
            original_query="Do studies disagree about mRNA vaccine effectiveness?",
            canonical_query="agreement in mRNA vaccine effectiveness evidence",
            route="COMPLEX",
            intent="evidence summary",
        ),
        max_subqueries=4,
    )

    assert [node.purpose for node in mechanism.subquestions] == [
        "mechanism evidence",
        "outcome evidence",
        "mechanism-to-outcome synthesis",
    ]
    assert mechanism.subquestions[-1].dependencies == ["sq-1", "sq-2"]
    assert [node.purpose for node in contradiction.subquestions] == [
        "supporting evidence",
        "challenging evidence",
        "agreement and conflict synthesis",
    ]
    assert contradiction.subquestions[-1].dependencies == ["sq-1", "sq-2"]


def test_generic_complex_plan_uses_unique_subqueries_within_budget():
    plan = ResearchPlanner().build(
        make_query_plan(
            route="COMPLEX",
            intent="evidence summary",
            subqueries=["arm one", " arm one ", "arm two", "arm three", "arm four"],
        ),
        max_subqueries=3,
    )

    assert len(plan.subquestions) == 3
    assert [node.question for node in plan.subquestions[:2]] == ["arm one", "arm two"]
    assert plan.subquestions[-1].dependencies == ["sq-1", "sq-2"]


def test_research_plan_rejects_duplicate_unknown_cyclic_blank_and_oversized_nodes():
    root = {"root_question": "question", "route": "COMPLEX", "max_query_budget": 4}
    with pytest.raises(ValidationError, match="unique"):
        ResearchPlan(**root, subquestions=[
            ResearchSubquestion(id="sq-1", question="one", purpose="arm"),
            ResearchSubquestion(id="sq-1", question="two", purpose="arm"),
        ])
    with pytest.raises(ValidationError, match="unknown"):
        ResearchPlan(**root, subquestions=[
            ResearchSubquestion(id="sq-1", question="one", purpose="arm", dependencies=["sq-9"]),
        ])
    with pytest.raises(ValidationError, match="cycle"):
        ResearchPlan(**root, subquestions=[
            ResearchSubquestion(id="sq-1", question="one", purpose="arm", dependencies=["sq-2"]),
            ResearchSubquestion(id="sq-2", question="two", purpose="arm", dependencies=["sq-1"]),
        ])
    with pytest.raises(ValidationError):
        ResearchSubquestion(id="sq-1", question=" ", purpose="arm")
    with pytest.raises(ValidationError):
        ResearchPlan(**root, subquestions=[
            ResearchSubquestion(id=f"sq-{index}", question=f"question {index}", purpose="arm")
            for index in range(1, 10)
        ])


def test_ready_subquestions_require_covered_dependencies_and_stable_order():
    plan = ResearchPlan(
        root_question="compare A and B",
        route="COMPLEX",
        max_query_budget=4,
        subquestions=[
            ResearchSubquestion(id="sq-1", question="A evidence", purpose="arm"),
            ResearchSubquestion(id="sq-2", question="B evidence", purpose="arm"),
            ResearchSubquestion(
                id="sq-3",
                question="A versus B",
                purpose="comparison",
                dependencies=["sq-1", "sq-2"],
            ),
        ],
    )
    coverage = {
        "sq-1": SubquestionCoverage(
            subquestion_id="sq-1", status=CoverageStatus.COVERED, supporting_pmids=["1"]
        ),
        "sq-2": SubquestionCoverage(
            subquestion_id="sq-2", status=CoverageStatus.PARTIAL, missing_concepts=["outcome"]
        ),
        "sq-3": SubquestionCoverage(subquestion_id="sq-3", status=CoverageStatus.UNCOVERED),
    }

    assert [node.id for node in plan.ready_subquestions(coverage)] == ["sq-2"]
    coverage["sq-2"] = coverage["sq-2"].model_copy(
        update={"status": CoverageStatus.COVERED, "supporting_pmids": ["2"]}
    )
    assert [node.id for node in plan.ready_subquestions(coverage)] == ["sq-3"]


def test_judge_records_pmid_backed_coverage_and_blocks_dependent_nodes():
    query_plan = make_query_plan(
        original_query="Compare empagliflozin with placebo for kidney outcomes",
        canonical_query="empagliflozin versus placebo kidney outcomes",
        route="COMPLEX",
        intent="comparison",
        pico=PICOModel(
            intervention="empagliflozin",
            comparator="placebo",
            outcome="kidney outcomes",
        ),
    )
    research_plan = ResearchPlanner().build(query_plan, max_subqueries=3)
    candidate = RetrievalCandidate(
        pmid="1001",
        title="Empagliflozin kidney outcomes",
        abstract="Empagliflozin improved kidney outcomes in adults with diabetes.",
        rrf_score=0.1,
        reranker_score=0.9,
    )

    grade = EvidenceSufficiencyJudge().judge(
        query_plan, [candidate], research_plan=research_plan
    )
    coverage = {item.subquestion_id: item for item in grade.subquestion_coverage}

    assert coverage["sq-1"].status is CoverageStatus.COVERED
    assert coverage["sq-1"].supporting_pmids == ["1001"]
    assert coverage["sq-2"].status is CoverageStatus.PARTIAL
    assert "placebo" in coverage["sq-2"].missing_concepts
    assert coverage["sq-3"].status is CoverageStatus.BLOCKED
    assert "sq-2" in coverage["sq-3"].reason


def test_model_contracts_forbid_extra_fields():
    with pytest.raises(ValidationError, match="extra"):
        ResearchSubquestion(id="sq-1", question="one", purpose="arm", hidden="no")
    with pytest.raises(ValidationError, match="extra"):
        SubquestionCoverage(subquestion_id="sq-1", status="UNCOVERED", score=0.5)
