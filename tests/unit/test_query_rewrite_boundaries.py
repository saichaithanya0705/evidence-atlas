from backend.app.query.query_service import QueryAnalysisService
from backend.app.workflow.judge import EvidenceSufficiencyJudge
from backend.app.evidence.extraction import _controlled_source_alias


def test_pdf_question_and_rewrite_do_not_become_one_intervention():
    raw = "Find recent research on effectiveness of mRNA vaccines against respiratory infections"
    rewrite = "What is the effectiveness of mRNA vaccines against respiratory infections in recent research?"
    enhanced = QueryAnalysisService().enhance_query(raw, agent_rewrite=rewrite)

    assert enhanced.raw_query == raw
    assert enhanced.pico.intervention.casefold() == "messenger ribonucleic acid vaccines"
    assert enhanced.pico.population is None
    assert all("what is" not in term.casefold() for term in enhanced.must_have_concepts)


def test_followup_rewrite_can_supply_missing_intervention():
    enhanced = QueryAnalysisService().enhance_query(
        "What are its adverse effects?",
        agent_rewrite="Safety of empagliflozin in patients with type 2 diabetes",
    )
    assert "empagliflozin" in " ".join(enhanced.must_have_concepts).casefold()
    assert enhanced.pico.intervention.casefold() == "empagliflozin"


def test_mrna_expansion_matches_source_acronym_without_relaxing_coverage():
    assert EvidenceSufficiencyJudge._appears(
        "Messenger Ribonucleic Acid vaccines", "mRNA vaccines against respiratory viruses"
    )
    assert not EvidenceSufficiencyJudge._appears(
        "Messenger Ribonucleic Acid vaccines", "DNA vaccines against respiratory viruses"
    )


def test_mrna_intervention_alias_preserves_only_source_wording():
    assert _controlled_source_alias(
        "Messenger Ribonucleic Acid vaccines", ["mRNA vaccines reduced severe disease."]
    ) == "mRNA vaccines"
    assert _controlled_source_alias(
        "Messenger Ribonucleic Acid vaccines", ["Vaccines reduced severe disease."]
    ) is None
