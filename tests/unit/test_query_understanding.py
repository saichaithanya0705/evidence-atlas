"""
tests/unit/test_query_understanding.py
Unit tests for Milestone 2: Biomedical Query Understanding & Adaptive Router.
Covers FEAT-R3-01 through FEAT-R3-11:
- FEAT-R3-01: Immutable Original Query Preservation
- FEAT-R3-02: Biomedical Acronym & Spelling Normalization
- FEAT-R3-03: MeSH Concept Identification
- FEAT-R3-04: Canonical Query Formulation
- FEAT-R3-05: Search Filter Extraction
- FEAT-R3-06: Dual Query Dense Embeddings
- FEAT-R3-07: PICO Concept Extraction (with strict None for missing)
- FEAT-R3-08: Non-PICO Biomedical Concept Extraction
- FEAT-R3-09: Research Intent Classification (7 closed categories)
- FEAT-R3-10: Concept Weighting & QueryPlan Assembly
- FEAT-R3-11: Adaptive Complexity Router (7 fast-path rules)
"""
import pytest
import numpy as np
from typing import Dict, List, Optional

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
    AcronymSpellingNormalizer,
    CURATED_ACRONYMS,
    COLLOQUIAL_CLINICAL_PHRASES,
)
from backend.app.query.mesh_mapper import (
    MeSHConceptIdentifier,
    AUGMENTED_MESH_ALIASES,
)
from backend.app.query.filter_extractor import (
    SearchFilterExtractor,
    STUDY_TYPE_PATTERNS,
)
from backend.app.query.canonical import (
    CanonicalQueryFormulator,
)
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


# ===========================================================================
# 1. FEAT-R3-01: Original Query Preservation
# ===========================================================================
class TestOriginalQueryPreservation:
    @pytest.mark.parametrize("raw_query", [
        "T2D heart attack risk reduction with metformin",
        "  Leading and trailing whitespace query  ",
        "<script>alert('xss')</script>",
        "SELECT * FROM papers WHERE pmid = 1; --",
        "🧬💊🩺💉 COVID-19 & T2D",
        "Query with \x00 null bytes and \u202e RTL override",
        "Metformin",
        "?",
    ])
    def test_original_query_preserved_verbatim(self, raw_query):
        """Original query must be preserved immutably across normalization and service pipeline."""
        normalizer = AcronymSpellingNormalizer()
        orig, clean, acronyms = normalizer.normalize(raw_query)
        assert orig == raw_query, "Original query was mutated by normalizer"

        service = QueryAnalysisService()
        plan, _ = service.build_query_plan(raw_query)
        assert plan.original_query == raw_query, "Original query was mutated in QueryPlan"


# ===========================================================================
# 2. FEAT-R3-02: Acronym & Spelling Normalization
# ===========================================================================
class TestAcronymAndSpellingNormalization:
    @pytest.mark.parametrize("acronym, expected_expansion", [
        ("T2D", "Type 2 Diabetes Mellitus"),
        ("T2DM", "Type 2 Diabetes Mellitus"),
        ("T1D", "Type 1 Diabetes Mellitus"),
        ("CKD", "Chronic Kidney Disease"),
        ("NSCLC", "Non-Small Cell Lung Cancer"),
        ("HBOT", "Hyperbaric Oxygen Therapy"),
        ("RCT", "Randomized Controlled Trial"),
        ("MACE", "Major Adverse Cardiovascular Events"),
        ("GLP1", "Glucagon-Like Peptide-1"),
        ("SGLT2", "Sodium-Glucose Cotransporter-2"),
        ("ARIA", "Amyloid-Related Imaging Abnormalities"),
        ("BP", "Blood Pressure"),
        ("eGFR", "Estimated Glomerular Filtration Rate"),
        ("AD", "Alzheimer Disease"),
        ("PD", "Parkinson Disease"),
        ("RSV", "Respiratory Syncytial Virus"),
        ("mRNA", "Messenger Ribonucleic Acid"),
        ("JAK", "Janus Kinase"),
        ("HTN", "Hypertension"),
        ("MI", "Myocardial Infarction"),
        ("HF", "Heart Failure"),
        ("CAD", "Coronary Artery Disease"),
        ("AF", "Atrial Fibrillation"),
        ("RA", "Rheumatoid Arthritis"),
        ("SLE", "Systemic Lupus Erythematosus"),
        ("COPD", "Chronic Obstructive Pulmonary Disease"),
        ("UC", "Ulcerative Colitis"),
    ])
    def test_curated_acronym_expansions(self, acronym, expected_expansion):
        """Curated acronyms must map directly to their clinical expansions."""
        assert CURATED_ACRONYMS[acronym] == expected_expansion

    @pytest.mark.parametrize("colloquial, expected_formal", [
        ("heart attack", "Myocardial Infarction"),
        ("high blood pressure", "Hypertension"),
        ("kidney damage", "Chronic Kidney Disease"),
        ("lung cancer", "Non-Small Cell Lung Cancer"),
    ])
    def test_colloquial_phrase_mapping(self, colloquial, expected_formal):
        """Colloquial lay expressions must map to formal clinical terms."""
        normalizer = AcronymSpellingNormalizer()
        query = f"Patient with {colloquial} treated with medication"
        orig, clean, acronyms = normalizer.normalize(query)
        assert orig == query
        assert expected_formal.lower() in clean.lower()
        assert colloquial in acronyms

    @pytest.mark.parametrize("typo_query, expected_word", [
        ("metfromin in diabetes", "metformin"),
        ("empagliflozen in CKD", "empagliflozin"),
        ("hypertenstion treatment", "hypertension"),
        ("cardiovascualr risk reduction", "cardiovascular"),
        ("alzhiemer memory loss", "alzheimer"),
    ])
    def test_spelling_corrections(self, typo_query, expected_word):
        """Common biomedical typos must be corrected in clean_query."""
        normalizer = AcronymSpellingNormalizer()
        _, clean, _ = normalizer.normalize(typo_query)
        assert expected_word.lower() in clean.lower()

    def test_empty_or_whitespace_query_raises_value_error(self):
        """Empty or whitespace-only queries must raise ValueError."""
        normalizer = AcronymSpellingNormalizer()
        with pytest.raises(ValueError):
            normalizer.normalize("")
        with pytest.raises(ValueError):
            normalizer.normalize("   \t\n  ")


# ===========================================================================
# 3. FEAT-R3-03: MeSH Concept Identification
# ===========================================================================
class TestMeSHConceptIdentification:
    @pytest.mark.parametrize("query_text, expected_mesh", [
        ("T2D with kidney damage", ["Diabetes Mellitus, Type 2", "Renal Insufficiency, Chronic"]),
        ("KRAS G12C lung cancer", ["Carcinoma, Non-Small-Cell Lung", "Mutation"]),
        ("pediatric mRNA immunization", ["mRNA Vaccines", "Child, Preschool"]),
        ("high blood pressure treatment", ["Hypertension"]),
        ("Alzheimer memory loss", ["Alzheimer Disease"]),
        ("severe asthma biologics", ["Asthma"]),
        ("metastatic breast cancer HER2", ["Breast Neoplasms"]),
        ("resistant hypertension catheter ablation", ["Hypertension", "Catheter Ablation"]),
        ("myocardial infarction risk in diabetes", ["Myocardial Infarction", "Diabetes Mellitus, Type 2"]),
        ("ulcerative colitis remission induction", ["Colitis, Ulcerative"]),
    ])
    def test_mesh_concept_mapping_contract(self, query_text, expected_mesh):
        """Maps query concepts to controlled MeSH descriptors for all 10 benchmark queries."""
        identifier = MeSHConceptIdentifier()
        normalizer = AcronymSpellingNormalizer()
        orig, clean, acronyms = normalizer.normalize(query_text)
        mesh_terms, concepts = identifier.identify_concepts(clean, orig, acronyms)

        for expected in expected_mesh:
            assert expected in mesh_terms, f"Expected MeSH term '{expected}' not found in {mesh_terms}"
        assert len(concepts) > 0

    def test_mesh_subsumption_pruning(self):
        """Generic ancestor terms must be pruned when specific child terms are present."""
        identifier = MeSHConceptIdentifier()
        normalizer = AcronymSpellingNormalizer()
        orig, clean, acronyms = normalizer.normalize("T2D heart attack risk reduction")
        mesh_terms, _ = identifier.identify_concepts(clean, orig, acronyms)
        # Should contain 'Diabetes Mellitus, Type 2' and NOT generic 'Diabetes Mellitus'
        assert "Diabetes Mellitus, Type 2" in mesh_terms
        assert "Diabetes Mellitus" not in mesh_terms


# ===========================================================================
# 4. FEAT-R3-04: Canonical Query Formulation
# ===========================================================================
class TestCanonicalQueryFormulation:
    @pytest.mark.parametrize("query, required_terms", [
        (
            "T2D heart attack risk reduction with metformin",
            ["type 2 diabetes mellitus", "myocardial infarction", "metformin"]
        ),
        (
            "Efficacy of GLP-1 RA vs SGLT2 inhibitors in T2D with CKD",
            ["glucagon-like peptide-1 receptor agonists", "sodium-glucose cotransporter-2", "chronic kidney disease"]
        ),
        (
            "Sotorasib resistance mechanisms in KRAS G12C NSCLC",
            ["sotorasib", "resistance", "non-small cell lung cancer"]
        ),
    ])
    def test_canonical_query_normalizes_terms_without_inventing_details(self, query, required_terms):
        """Canonicalization expands controlled terms without canned scenario answers."""
        formulator = CanonicalQueryFormulator()
        canon = formulator.formulate_deterministic(query, query)
        for term in required_terms:
            assert term in canon.lower()
        assert "monotherapy" not in canon.lower()
        assert "acquired" not in canon.lower()
        assert len(canon) > 15
        assert canon != query or len(canon) > 20

    def test_canonical_query_generalizes_to_unseen_acronyms(self):
        formulator = CanonicalQueryFormulator()
        canon = formulator.formulate_deterministic("COPD RCT outcomes", "COPD RCT outcomes")
        assert "chronic obstructive pulmonary disease" in canon.lower()
        assert "randomized controlled trial" in canon.lower()

    def test_canonical_query_generic_fallback(self):
        """Generic queries produce valid expanded canonical query meeting length invariants."""
        formulator = CanonicalQueryFormulator()
        canon = formulator.formulate_deterministic("short query", "short query", mesh_terms=["Neoplasms"])
        assert len(canon) > 15
        assert canon != "short query" or len(canon) > 20

    @pytest.mark.parametrize("query, forbidden_terms", [
        ("pediatric asthma", ["mrna", "vaccine", "2022"]),
        ("metformin in PCOS", ["myocardial infarction", "monotherapy", "heart attack"]),
    ])
    def test_canonical_query_no_mock_catalog_hijacking(self, query, forbidden_terms):
        """Canonicalization does not hijack arbitrary queries to benchmark scenarios."""
        formulator = CanonicalQueryFormulator()
        canon = formulator.formulate_deterministic(query, query)
        for term in forbidden_terms:
            assert term not in canon.lower()
        assert len(canon) > 15


# ===========================================================================
# 5. FEAT-R3-05: Search Filter Extraction
# ===========================================================================
class TestSearchFilterExtraction:
    @pytest.mark.parametrize("query_phrase, expected_year_min, expected_design", [
        ("Randomized trials after 2022", 2023, "Randomized Controlled Trial"),
        ("Cohort studies published after 2020", 2021, "Observational Cohort Study"),
        ("Systematic reviews after 2021", 2022, "Systematic Review"),
        ("Phase 3 trials after 2023", 2024, "Randomized Controlled Trial"),
        ("Meta-analyses since 2019", 2020, "Systematic Review"),
        ("Clinical trials after 2018", 2019, "Randomized Controlled Trial"),
        ("Observational studies after 2023", 2024, "Observational Cohort Study"),
        ("Randomized controlled trials after 2021", 2022, "Randomized Controlled Trial"),
        ("Systematic reviews after 2017", 2018, "Systematic Review"),
        ("Randomized trials after 2015", 2016, "Randomized Controlled Trial"),
    ])
    def test_temporal_offset_and_study_design_extraction(self, query_phrase, expected_year_min, expected_design):
        """Evaluates offset arithmetic ('after YYYY' -> year_min = YYYY + 1) and study design mapping."""
        extractor = SearchFilterExtractor()
        filters = extractor.extract_filters(query_phrase)
        assert filters.year_min == expected_year_min
        assert expected_design in filters.study_type_filters

    @pytest.mark.parametrize("query_phrase, expected_year_min, expected_year_max", [
        ("Studies before 2020", None, 2019),
        ("Trials published between 2018 and 2023", 2018, 2023),
        ("Meta-analysis 2015-2022", 2015, 2022),
        ("Studies in the last 5 years", 2021, None),
    ])
    def test_date_range_and_relative_temporal_parsing(self, query_phrase, expected_year_min, expected_year_max):
        """Evaluates before, range, and relative 'last N years' parsing (anchored to 2026)."""
        extractor = SearchFilterExtractor(reference_year=2026)
        filters = extractor.extract_filters(query_phrase)
        assert filters.year_min == expected_year_min
        assert filters.year_max == expected_year_max

    @pytest.mark.parametrize("invalid_year_query", [
        ("Studies after 1850", None),
        ("Trials published after 2150", None),
        ("Papers from 1200 to 1400", None),
    ])
    def test_year_boundary_clamping(self, invalid_year_query):
        """Years outside [1900, 2099] must be rejected (set to None)."""
        query, expected = invalid_year_query
        extractor = SearchFilterExtractor()
        filters = extractor.extract_filters(query)
        assert filters.year_min is None


# ===========================================================================
# 6. FEAT-R3-06: Dual Query Dense Embeddings
# ===========================================================================
class TestDualQueryDenseEmbeddings:
    def test_dual_embeddings_dimension_and_norm(self):
        """Dual embeddings must each be 768-dim float32 unit-norm vectors."""
        generator = DualQueryEmbeddingGenerator()
        orig_q = "T2D heart attack risk reduction with metformin"
        canon_q = "Type 2 diabetes mellitus myocardial infarction risk reduction with metformin monotherapy"

        orig_vec, canon_vec = generator.generate_embeddings(orig_q, canon_q)

        assert orig_vec.shape == (768,)
        assert canon_vec.shape == (768,)
        assert orig_vec.dtype == np.float32
        assert canon_vec.dtype == np.float32

        # Unit norm checks
        assert abs(np.linalg.norm(orig_vec) - 1.0) < 1e-5
        assert abs(np.linalg.norm(canon_vec) - 1.0) < 1e-5

        # Pydantic model representation
        dual_model = generator.generate_dual_model(orig_q, canon_q)
        assert len(dual_model.original_query_embedding) == 768
        assert len(dual_model.canonical_query_embedding) == 768


# ===========================================================================
# 7. FEAT-R3-07: PICO Concept Extraction
# ===========================================================================
class TestPICOConceptExtraction:
    def test_comparative_query_pico_has_comparator(self):
        """Head-to-head comparative queries must have non-null intervention and comparator."""
        extractor = PICOExtractor()
        q = "Efficacy and cardiovascular outcomes of GLP-1 RA vs SGLT2 inhibitors in T2D with CKD"
        pico = extractor.extract(q)
        assert pico.intervention is not None
        assert pico.comparator is not None
        assert pico.population is not None
        assert pico.outcome is not None

    def test_single_intervention_query_comparator_is_strictly_none(self):
        """Single-intervention queries must have comparator = None."""
        extractor = PICOExtractor()
        q = "Sotorasib resistance mechanisms in KRAS G12C mutated NSCLC"
        pico = extractor.extract(q)
        assert pico.intervention is not None
        assert pico.comparator is None, f"Expected comparator to be None, got '{pico.comparator}'"
        assert pico.population is not None
        assert pico.outcome is not None

    def test_pico_null_boundary_handling(self):
        """PICO model gracefully handles missing components."""
        pico = PICOModel(population=None, intervention=None, comparator=None, outcome=None)
        assert pico.population is None
        assert pico.intervention is None
        assert pico.comparator is None
        assert pico.outcome is None

    def test_generic_pathology_outcome_not_hijacked(self):
        """Generic pathology query does not yield tau pathology."""
        extractor = PICOExtractor()
        pico = extractor.extract("Bone pathology in osteoporosis")
        assert "tau" not in str(pico).lower()
        assert pico.outcome == "Bone pathology"


# ===========================================================================
# 8. FEAT-R3-08: Non-PICO Biomedical Concept Extraction
# ===========================================================================
class TestNonPICOConceptExtraction:
    def test_non_pico_mechanistic_query(self):
        """Extracts disease topic, exposure, treatment, and relationship for non-PICO queries."""
        extractor = NonPICOExtractor()
        q = "Sotorasib resistance mechanisms in KRAS G12C NSCLC"
        non_pico = extractor.extract(q)
        assert non_pico.disease_topic == "Non-Small Cell Lung Cancer"
        assert non_pico.exposure == "KRAS G12C mutation"
        assert non_pico.treatment == "Sotorasib"
        assert non_pico.relationship == "Molecular resistance mechanism"

    def test_non_pico_generalization_without_benchmark_assumptions(self):
        """NonPICO concepts generalize to distinct mutations and diseases without assuming benchmark defaults."""
        extractor = NonPICOExtractor()
        np1 = extractor.extract("KRAS G12D in pancreatic cancer")
        assert np1.exposure == "KRAS G12D mutation"
        assert np1.disease_topic == "Pancreatic Cancer"

        np2 = extractor.extract("Type 1 diabetes in children")
        assert np2.disease_topic == "Type 1 Diabetes Mellitus"
        assert np2.population == "Pediatric cohort"

        np3 = extractor.extract("mRNA splicing mechanisms in muscular dystrophy")
        assert np3.exposure != "mRNA vaccine exposure"


# ===========================================================================
# 9. FEAT-R3-09: Research Intent Classification
# ===========================================================================
class TestResearchIntentClassification:
    @pytest.mark.parametrize("query, expected_intent", [
        ("T2D heart attack risk reduction with metformin", "discovery"),
        ("Efficacy and cardiovascular outcomes of GLP-1 vs SGLT2 inhibitors in T2D with CKD", "comparison"),
        ("Sotorasib resistance mechanisms in KRAS G12C NSCLC", "mechanism"),
        ("Randomized controlled trials of mRNA vaccines in pediatric cohorts after 2022", "discovery"),
        ("Renal denervation versus sham in resistant hypertension", "comparison"),
        ("Systematic review and meta-analysis of dual RAAS blockade", "evidence summary"),
        ("Association between blood pressure variability and dementia", "association"),
    ])
    def test_intent_classification_taxonomy(self, query, expected_intent):
        """Maps clinical queries into the 7 canonical intent categories."""
        classifier = IntentClassifier()
        intent = classifier.classify(query)
        assert intent == expected_intent


# ===========================================================================
# 10. FEAT-R3-10: Concept Weighting & QueryPlan Assembly
# ===========================================================================
class TestConceptWeightingAndQueryPlanAssembly:
    def test_concept_weights_partitioning(self):
        """Partitions extracted concepts into must-have, high-priority, and optional tiers."""
        pico = PICOModel(
            population="Patients with T2D",
            intervention="Metformin",
            comparator=None,
            outcome="Myocardial infarction risk reduction"
        )
        weights = assign_concept_weights(
            pico=pico,
            non_pico=None,
            mesh_terms=["Diabetes Mellitus, Type 2", "Myocardial Infarction"],
            acronyms_expanded={"T2D": "Type 2 Diabetes Mellitus"},
        )

        assert "Patients with T2D" in weights.must_have
        assert "Metformin" in weights.must_have
        assert "Myocardial infarction risk reduction" in weights.high_priority
        assert "Diabetes Mellitus, Type 2" in weights.high_priority

    def test_query_plan_assembly_full_contract(self):
        """QueryPlan assembled by service complies with e2e_contracts.QueryPlan schema."""
        service = QueryAnalysisService()
        plan, emb = service.build_query_plan(
            "T2D heart attack risk reduction with metformin",
            generate_embeddings=True
        )

        assert plan.original_query == "T2D heart attack risk reduction with metformin"
        assert len(plan.clean_query) > 0
        assert len(plan.canonical_query) > 15
        assert plan.route == "SIMPLE"
        assert plan.router_confidence >= 0.85
        assert len(plan.router_reasoning) > 10
        assert len(plan.subqueries) >= 1
        assert emb is not None
        assert len(emb.original_query_embedding) == 768


# ===========================================================================
# 11. FEAT-R3-11: Adaptive Complexity Router
# ===========================================================================
class TestAdaptiveComplexityRouter:
    @pytest.mark.parametrize("query, expected_route, expected_min_conf", [
        ("Metformin", "SIMPLE", 0.95),
        ("Sotorasib", "SIMPLE", 0.95),
        ("T2D heart attack risk reduction with metformin", "SIMPLE", 0.90),
        ("Randomized controlled trials of mRNA vaccines in pediatric cohorts after 2022", "MODERATE", 0.90),
        ("Efficacy and cardiovascular outcomes of GLP-1 vs SGLT2 inhibitors in T2D with CKD", "COMPLEX", 0.90),
        ("Sotorasib resistance mechanisms in KRAS G12C NSCLC", "COMPLEX", 0.90),
        ("Hyperbaric oxygen therapy efficacy in reversing advanced Stage IV Alzheimer's tau", "COMPLEX", 0.85),
    ])
    def test_adaptive_router_fast_path(self, query, expected_route, expected_min_conf):
        """Fast-path decision tree routes clinical queries correctly with confidence >= 0.85."""
        router = AdaptiveComplexityRouter()
        service = QueryAnalysisService(router=router)
        plan, _ = service.build_query_plan(query)

        assert plan.route == expected_route
        assert plan.router_confidence >= expected_min_conf
        assert len(plan.router_reasoning) > 10
        assert plan.router_confidence >= 0.85

    def test_single_word_queries_route_to_simple(self):
        """Single biomedical terms route safely to SIMPLE per Tier 2 BVA specification."""
        router = AdaptiveComplexityRouter()
        for term in ["Metformin", "Sotorasib", "COVID-19", "Hypertension", "Lecanemab", "A", "?"]:
            decision = router.route_query(term, term)
            assert decision.route == "SIMPLE"
            assert decision.confidence >= 0.95
            assert len(decision.reasoning) > 10

    def test_rule_5_dynamic_reasoning_for_non_vaccine_safety(self):
        """Rule 5 reasoning dynamically adapts without canned multi-vaccine expansion phrasing."""
        router = AdaptiveComplexityRouter()
        decision = router.route_query(
            "Aspirin bleeding safety in elderly",
            "aspirin bleeding safety in elderly",
            intent="safety"
        )
        assert decision.route == "MODERATE"
        assert decision.confidence >= 0.85
        assert len(decision.reasoning) > 10
        assert "vaccine" not in decision.reasoning.lower()
        assert "safety" in decision.reasoning.lower()

    def test_arbitration_never_allows_agent_hint_to_lower_rule_route(self):
        router = AdaptiveComplexityRouter()
        rule = RoutingDecision(
            route="COMPLEX",
            confidence=0.93,
            reasoning="A comparison requires decomposed evidence review.",
            rule_applied="RULE_2_HEAD_TO_HEAD_COMPARISON",
        )

        decision = router.arbitrate(rule, agent_hint="SIMPLE")

        assert decision.route == "COMPLEX"
        assert decision.confidence == 0.93
        assert decision.rule_applied == rule.rule_applied

    def test_arbitration_allows_valid_agent_hint_to_raise_rule_route(self):
        router = AdaptiveComplexityRouter()
        rule = RoutingDecision(
            route="SIMPLE",
            confidence=0.85,
            reasoning="Standard direct hybrid retrieval pass.",
            rule_applied="RULE_DEFAULT_SIMPLE",
        )

        decision = router.arbitrate(rule, agent_hint="COMPLEX")

        assert decision.route == "COMPLEX"
        assert decision.confidence == 0.85
        assert decision.rule_applied == rule.rule_applied
        assert "agent" in decision.reasoning.lower()

    def test_arbitration_preserves_prior_route_floor_and_ignores_invalid_hint(self):
        router = AdaptiveComplexityRouter()
        rule = RoutingDecision(
            route="SIMPLE",
            confidence=0.86,
            reasoning="Standard direct hybrid retrieval pass.",
            rule_applied="RULE_DEFAULT_SIMPLE",
        )

        decision = router.arbitrate(rule, agent_hint="not-a-route", route_floor="COMPLEX")

        assert decision.route == "COMPLEX"
        assert decision.confidence == 0.86
        assert "floor" in decision.reasoning.lower()

    def test_arbitration_without_hint_keeps_legacy_decision(self):
        router = AdaptiveComplexityRouter()
        rule = RoutingDecision(
            route="MODERATE",
            confidence=0.91,
            reasoning="Temporal and cohort constraints require expansion.",
            rule_applied="RULE_5_FILTERED_CLINICAL_QUERY",
        )

        decision = router.arbitrate(rule)

        assert decision.model_dump() == rule.model_dump()


def test_query_enhancement_preserves_rewrite_raw_must_have_and_explicit_filters():
    service = QueryAnalysisService()
    raw = "Sotorasib resistance mechanisms in KRAS G12C NSCLC"
    rewrite = "Sotorasib resistance pathway evidence in KRAS G12C non-small cell lung cancer"

    enhanced = service.enhance_query(
        raw,
        agent_rewrite=rewrite,
        explicit_filters=SearchFilters(
            year_min=2021,
            year_max=2025,
            study_type_filters=["Randomized Controlled Trial"],
        ),
    )

    assert enhanced.raw_query == raw
    assert enhanced.agent_rewrite == rewrite
    assert enhanced.canonical_query
    must_have = " ".join(enhanced.must_have_concepts).casefold()
    assert "sotorasib" in must_have
    assert "g12c" in must_have
    assert enhanced.filters.year_min == 2021
    assert enhanced.filters.year_max == 2025
    assert enhanced.filters.study_type_filters == ["Randomized Controlled Trial"]


def test_build_query_plan_uses_one_consistent_enhancement_snapshot():
    class StatefulPICOExtractor:
        def __init__(self):
            self.calls = 0

        def extract(self, *_args):
            self.calls += 1
            return PICOModel(
                population="adults",
                intervention="metformin",
                outcome=f"Outcome {self.calls}",
            )

    extractor = StatefulPICOExtractor()
    service = QueryAnalysisService(pico_extractor=extractor)

    plan, _ = service.build_query_plan("metformin outcomes in adults")

    assert extractor.calls == 1
    assert plan.pico.outcome == "Outcome 1"
    assert plan.concepts == plan.concept_weights.high_priority
    assert "Outcome 1" in plan.concepts
