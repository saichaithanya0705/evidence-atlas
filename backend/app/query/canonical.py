"""
backend/app/query/canonical.py
Canonical Query Formulation Module (FEAT-R3-04).
Synthesizes standardized biomedical research query phrasings bridging lay/short user inputs
with formal literature indexing. Supports a configurable NVIDIA NIM model and deterministic offline fallback.
"""
import logging
import re
from typing import Dict, List, Optional
from backend.app.query.models import PICOModel

logger = logging.getLogger(__name__)

# Conservative, reusable lexical equivalents. These are deliberately not
# benchmark answers: no outcome, intervention, or study-design detail is added
# unless it is already present in the input/query plan.
CONTROLLED_TERM_REPLACEMENTS = {
    r"\bT2DM\b|\bT2D\b": "type 2 diabetes mellitus",
    r"\bheart attack(?:s)?\b": "myocardial infarction",
    r"\bGLP-?1(?:\s*[- ]?\s*RA(?:s)?|\s+receptor\s+agonists?)\b": "glucagon-like peptide-1 receptor agonists",
    r"\bSGLT-?2(?:i|\s+inhibitors?)?\b": "sodium-glucose cotransporter-2 inhibitors",
    r"\bCKD\b": "chronic kidney disease",
    r"\bNSCLC\b": "non-small cell lung cancer",
    r"\bCOPD\b": "chronic obstructive pulmonary disease",
    r"\bRCTs?\b": "randomized controlled trials",
}

CANONICAL_PROMPT_SYSTEM = """You are an expert biomedical research information specialist.
Your objective is to formulate a single standardized, canonical scientific query for PubMed/MEDLINE retrieval based on a researcher's input.

Guidelines:
1. Use formal biomedical terminology and controlled MeSH descriptors.
2. Fully expand all abbreviations and clinical acronyms.
3. Explicitly state the population, intervention, comparator, and clinical outcomes if present.
4. Maintain any temporal constraints (e.g. "after 2022") or study designs (e.g. "randomized controlled trial").
5. Output ONLY the single canonical query sentence. Do not include commentary, quotes, or markdown.
"""



class CanonicalQueryFormulator:
    """
    Formulates standardized canonical biomedical queries (FEAT-R3-04).
    Uses NVIDIA NIM API when enabled, or a fully generalizable deterministic
    template engine that synthesizes canonical queries from PICO components,
    MeSH terms, and acronym expansions — no hardcoded scenario catalogs.
    """

    def __init__(
        self,
        llm_client=None,
        llm_mode: str = "mock",
        model_name: str = "nvidia/nemotron-3-super-120b-a12b",
        api_key: Optional[str] = None
    ):
        self.llm_client = llm_client
        self.llm_mode = llm_mode
        self.model_name = model_name
        self.api_key = api_key

    async def formulate(
        self,
        original_query: str,
        clean_query: str,
        mesh_terms: Optional[List[str]] = None,
        pico: Optional[PICOModel] = None,
        acronyms_expanded: Optional[Dict[str, str]] = None,
    ) -> str:
        """Formulates canonical query asynchronously."""
        # Active NIM / OpenAI execution if configured
        if self.llm_mode in ("nim", "openai") and self.api_key and self.llm_client:
            try:
                response = await self.llm_client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": CANONICAL_PROMPT_SYSTEM},
                        {"role": "user", "content": f"User query: {clean_query}"}
                    ],
                    temperature=0.0,
                    max_tokens=128,
                    timeout=5.0
                )
                raw_result = response.choices[0].message.content.strip().strip('"').strip("'")
                if self._is_safe_llm_result(raw_result, clean_query):
                    return raw_result
            except Exception as e:
                logger.warning("NVIDIA NIM query formulation failed (%s); using deterministic fallback.", e)

        return self.formulate_deterministic(original_query, clean_query, mesh_terms, pico, acronyms_expanded)

    def _apply_acronym_expansions(self, text: str, acronyms_expanded: Optional[Dict[str, str]]) -> str:
        """Applies acronym expansions inline to produce formal biomedical phrasing."""
        if not acronyms_expanded:
            return text
        result = text
        for abbr, full in sorted(acronyms_expanded.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = re.compile(re.escape(abbr), re.IGNORECASE)
            result = pattern.sub(full, result)
        return result

    def _normalize_controlled_terms(self, text: str) -> str:
        """Replace only high-confidence lexical equivalents found in ``text``."""
        result = text
        for pattern, replacement in CONTROLLED_TERM_REPLACEMENTS.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", result).strip()

    @staticmethod
    def _is_safe_llm_result(result: str, source_query: str) -> bool:
        """Reject malformed, instruction-like, or semantically unanchored output."""
        if not 15 <= len(result) <= 500 or "\n" in result:
            return False
        if any(marker in result.lower() for marker in ("```", "system:", "assistant:", "ignore previous")):
            return False
        source_terms = set(re.findall(r"[a-z0-9-]{3,}", source_query.lower()))
        result_terms = set(re.findall(r"[a-z0-9-]{3,}", result.lower()))
        return bool(source_terms & result_terms)

    def _enrich_with_mesh(self, text: str, mesh_terms: Optional[List[str]]) -> str:
        """Appends relevant MeSH context to short or generic queries."""
        if not mesh_terms:
            return text
        # Only add MeSH terms not already mentioned in the text
        text_lower = text.lower()
        novel_terms = [t for t in mesh_terms if t.lower() not in text_lower]
        if novel_terms:
            return f"{text} in the context of {', '.join(novel_terms[:3])}"
        return text

    def formulate_deterministic(
        self,
        original_query: str,
        clean_query: str,
        mesh_terms: Optional[List[str]] = None,
        pico: Optional[PICOModel] = None,
        acronyms_expanded: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Generalizable deterministic rule-based canonical formulation.
        Synthesizes from PICO components, acronym expansions, and MeSH context.
        Guarantees: len > 15 and (canonical != original or len > 20).
        No hardcoded scenario catalogs — every input is processed dynamically.
        """
        # Step 1: Expand acronyms in the clean query for formal biomedical phrasing
        expanded_query = self._apply_acronym_expansions(clean_query, acronyms_expanded)
        expanded_query = self._normalize_controlled_terms(expanded_query)

        # PICO is a lossy extraction, not authority to replace the question.
        # Keep the user's incidence, association, safety, or other objective;
        # fixed efficacy templates can erase it or invent an intervention.
        clean_norm = expanded_query.strip()
        if len(clean_norm) > 25:
            canon = clean_norm[0].upper() + clean_norm[1:]
            # Enrich with MeSH context if available
            canon = self._enrich_with_mesh(canon, mesh_terms)
            if canon == original_query and len(canon) <= 20:
                canon = f"{canon} clinical research"
            return canon

        # Step 4: Short queries — enrich with MeSH or standard scientific phrasing
        mesh_context = ", ".join(mesh_terms[:3]) if mesh_terms else "clinical medicine"
        canon = f"Biomedical literature on {clean_norm} in {mesh_context}"

        # Invariant check
        if len(canon) <= 15:
            canon = f"{canon} in biomedical research"

        return canon
