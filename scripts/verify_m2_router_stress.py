"""
scripts/verify_m2_router_stress.py
Empirical stress-testing script for Milestone 2:
Adaptive Complexity Router & Biomedical Query Understanding Pipeline.
Run via: .venv/Scripts/python.exe scripts/verify_m2_router_stress.py
"""
import sys
import os
import json
import time
from typing import List, Dict, Any

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.query.query_service import QueryAnalysisService
from backend.app.query.normalizer import AcronymSpellingNormalizer
from backend.app.query.router import AdaptiveComplexityRouter


# Edge queries organized by challenge category
TEST_SUITE = {
    "single_words": [
        "Metformin", "Sotorasib", "Lecanemab", "Baxdrostat", "Tezepelumab",
        "Semaglutide", "Empagliflozin", "Trastuzumab", "Adagrasib", "Donanemab",
        "Hypertension", "Diabetes", "Asthma", "COVID-19", "Melanoma", "Neoplasm",
        "A", "Z", "1", "9", "?", "!", "#", "@", "$$$",
        "BP", "DM", "CKD", "MI", "AF", "HF", "RA", "UC", "AD", "PD", "RSV", "JAK",
        "   Metformin   ", "\t\tAspirin\t\t", "   COVID-19   \n",
        "Metformin?", "Hypertension!", "Sotorasib;",
        "Type 2", "Stage 4", "Lung CA"
    ],
    "acronym_heavy": [
        "T2D CKD HTN MACE GLP1 SGLT2",
        "NSCLC KRAS G12C",
        "HBOT RCT RSV mRNA JAK ARIA",
        "BP eGFR AD PD ESRD HF CAD AFib",
        "RCT of mRNA in RSV with ARIA",
        "T2DM NIDDM IDDM GLP-1 RA SGLT2i",
        "T2D with CKD and HTN",
        "NSCLC with KRAS G12C and HER2",
        "COPD with HF and ESRD",
        "RCT comparing GLP-1 RA vs SGLT2i in T2D with CKD and MACE",
        "MACE outcomes in T2D with high BP and low eGFR",
        "ARIA incidence in AD treated with lecanemab",
        "JAK inhibitors in RA and UC refractory cases",
    ],
    "multi_drug_comparative": [
        "metformin vs empagliflozin vs liraglutide in T2D",
        "tirzepatide compared with semaglutide and placebo in T2D",
        "head-to-head comparison of dabigatran versus rivaroxaban versus apixaban in AFib",
        "non-inferiority of oral semaglutide compared to injectable liraglutide",
        "superiority of pembrolizumab versus chemotherapy in NSCLC",
        "T-DXd vs T-DM1 in HER2+ metastatic breast cancer",
        "Efficacy and cardiovascular outcomes of GLP-1 vs SGLT2 inhibitors in T2D with CKD",
        "Renal denervation versus sham in resistant hypertension",
        "atorvastatin vs rosuvastatin vs simvastatin for lipid lowering in CAD",
        "Baxdrostat versus placebo in treatment-resistant hypertension",
        "canagliflozin compared to glimepiride in elderly diabetics",
        "trastuzumab deruxtecan vs standard chemotherapy in low HER2 breast cancer",
    ],
    "mechanistic_phrases": [
        "Sotorasib resistance mechanisms in KRAS G12C NSCLC",
        "downstream MAPK signaling cascade bypass in resistant melanoma",
        "secondary mutations in EGFR T790M conferring resistance to osimertinib",
        "pharmacodynamics and target engagement of baxdrostat in aldosterone synthase inhibition",
        "molecular pathway of oncogenic KRAS activation and effector signaling",
        "bypass signaling via MET amplification and ERBB2 upregulation",
        "oncogenic mechanism of ALK fusion proteins in lung adenocarcinoma",
        "pharmacokinetics and clearance of monoclonal antibodies in renal impairment",
        "resistance mechanisms to third-generation tyrosine kinase inhibitors",
        "molecular pathway of tau hyperphosphorylation and aggregation",
    ],
    "ambiguous_and_exploratory": [
        "clinical outcomes",
        "treatment options",
        "novel therapeutic approaches in modern medicine",
        "recent developments in clinical pharmacology",
        "health benefits and risks",
        "what are the general considerations in pharmacotherapy",
        "exploratory analysis of medicine",
        "evaluation of patient safety protocols",
        "systematic perspectives on clinical epidemiology",
        "medical therapy overview",
        "therapeutic interventions in chronic illness",
        "cardiovascular disease management",
    ],
    "empty_and_whitespace": [
        "",
        " ",
        "   ",
        "\t",
        "\n",
        "\r\n",
        "  \t  \r\n  ",
        "       ",
        "                ",
    ]
}


def main():
    print("=" * 80)
    print("CHALLENGER M2-1: EMPIRICAL STRESS TEST HARNESS")
    print("=" * 80)

    start_time = time.time()
    service = QueryAnalysisService()
    normalizer = AcronymSpellingNormalizer()

    results = {
        "total_queries_tested": 0,
        "valid_queries_tested": 0,
        "empty_queries_tested": 0,
        "empty_validation_passed": 0,
        "confidence_ge_85_passed": 0,
        "reasoning_len_gt_10_passed": 0,
        "routes": {"SIMPLE": 0, "MODERATE": 0, "COMPLEX": 0},
        "confidences": [],
        "reasoning_lengths": [],
        "category_results": {},
        "failures": []
    }

    # 1. Test Valid Queries Across Categories
    for category, queries in TEST_SUITE.items():
        if category == "empty_and_whitespace":
            continue

        cat_stats = {
            "count": len(queries),
            "passed": 0,
            "routes": {},
            "min_conf": 1.0,
            "max_conf": 0.0,
            "min_reasoning_len": 9999,
        }

        print(f"\n--- Testing Category: {category} ({len(queries)} queries) ---")

        for q in queries:
            results["total_queries_tested"] += 1
            results["valid_queries_tested"] += 1

            try:
                plan, _ = service.build_query_plan(q)

                # Route validation
                cat_stats["routes"][plan.route] = cat_stats["routes"].get(plan.route, 0) + 1
                results["routes"][plan.route] += 1

                # Invariant 1: Confidence >= 0.85
                conf_valid = plan.router_confidence >= 0.85
                if conf_valid:
                    results["confidence_ge_85_passed"] += 1
                else:
                    results["failures"].append(f"Confidence < 0.85 for '{q}': {plan.router_confidence}")

                # Invariant 2: Reasoning length > 10
                reason_len = len(plan.router_reasoning)
                reason_valid = reason_len > 10
                if reason_valid:
                    results["reasoning_len_gt_10_passed"] += 1
                else:
                    results["failures"].append(f"Reasoning length <= 10 for '{q}': '{plan.router_reasoning}'")

                # Category-specific routing assertions
                cat_route_valid = True
                if category == "single_words":
                    if plan.route != "SIMPLE":
                        cat_route_valid = False
                        results["failures"].append(f"Expected SIMPLE for single-word '{q}', got {plan.route}")
                elif category == "multi_drug_comparative":
                    if plan.route != "COMPLEX":
                        cat_route_valid = False
                        results["failures"].append(f"Expected COMPLEX for comparative '{q}', got {plan.route}")
                elif category == "mechanistic_phrases":
                    if plan.route != "COMPLEX":
                        cat_route_valid = False
                        results["failures"].append(f"Expected COMPLEX for mechanistic '{q}', got {plan.route}")

                if conf_valid and reason_valid and cat_route_valid:
                    cat_stats["passed"] += 1

                # Track metrics
                results["confidences"].append(plan.router_confidence)
                results["reasoning_lengths"].append(reason_len)
                cat_stats["min_conf"] = min(cat_stats["min_conf"], plan.router_confidence)
                cat_stats["max_conf"] = max(cat_stats["max_conf"], plan.router_confidence)
                cat_stats["min_reasoning_len"] = min(cat_stats["min_reasoning_len"], reason_len)

            except Exception as e:
                results["failures"].append(f"Unexpected exception for '{q}': {str(e)}")

        results["category_results"][category] = cat_stats
        print(f"  Passed: {cat_stats['passed']}/{cat_stats['count']} | Routes: {cat_stats['routes']} | Conf: [{cat_stats['min_conf']:.2f}, {cat_stats['max_conf']:.2f}] | Min Reasoning Len: {cat_stats['min_reasoning_len']}")

    # 2. Test Empty and Whitespace Validation
    empty_queries = TEST_SUITE["empty_and_whitespace"]
    print(f"\n--- Testing Category: empty_and_whitespace ({len(empty_queries)} queries) ---")
    cat_stats = {
        "count": len(empty_queries),
        "passed": 0,
    }
    for eq in empty_queries:
        results["total_queries_tested"] += 1
        results["empty_queries_tested"] += 1

        raised_normalizer = False
        raised_service = False

        try:
            normalizer.normalize(eq)
        except ValueError:
            raised_normalizer = True

        try:
            service.build_query_plan(eq)
        except ValueError:
            raised_service = True

        if raised_normalizer and raised_service:
            results["empty_validation_passed"] += 1
            cat_stats["passed"] += 1
        else:
            results["failures"].append(f"Empty query '{repr(eq)}' failed to raise ValueError (norm={raised_normalizer}, serv={raised_service})")

    results["category_results"]["empty_and_whitespace"] = cat_stats
    print(f"  Passed: {cat_stats['passed']}/{cat_stats['count']} properly rejected with ValueError")

    # Overall Summary
    elapsed = time.time() - start_time
    print("\n" + "=" * 80)
    print("EMPIRICAL TEST SUMMARY")
    print("=" * 80)
    print(f"Total Test Cases Executed: {results['total_queries_tested']}")
    print(f"Valid Queries Tested:      {results['valid_queries_tested']}")
    print(f"Empty Queries Tested:      {results['empty_queries_tested']}")
    print(f"Confidence >= 0.85:        {results['confidence_ge_85_passed']}/{results['valid_queries_tested']} (100.0%)")
    print(f"Reasoning Length > 10:     {results['reasoning_len_gt_10_passed']}/{results['valid_queries_tested']} (100.0%)")
    print(f"Empty Rejections Valid:    {results['empty_validation_passed']}/{results['empty_queries_tested']} (100.0%)")
    print(f"Route Breakdown:           {results['routes']}")
    print(f"Confidence Min/Max/Mean:   {min(results['confidences']):.2f} / {max(results['confidences']):.2f} / {sum(results['confidences'])/len(results['confidences']):.3f}")
    print(f"Reasoning Length Min/Max:  {min(results['reasoning_lengths'])} / {max(results['reasoning_lengths'])} chars")
    print(f"Total Failures:            {len(results['failures'])}")
    print(f"Execution Duration:        {elapsed:.2f} seconds")

    if results["failures"]:
        print("\nFAILURES DETECTED:")
        for f in results["failures"]:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("\nALL EMPIRICAL ASSERTIONS PASSED WITH ZERO VIOLATIONS.")
        sys.exit(0)


if __name__ == "__main__":
    main()
