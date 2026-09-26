"""
backend/app/services/mesh_service.py
In-memory service providing fast O(1) MeSH concept resolution, synonym expansion,
and controlled vocabulary mapping for query understanding and routing.
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional, Any

logger = logging.getLogger("mesh_service")


class MeshDictionaryService:
    """Provides high-performance in-memory lookups for MeSH concepts and synonyms."""

    def __init__(self, dict_path: str = "data/processed/mesh_dictionary.json"):
        self.dict_path = dict_path
        self.descriptors: Dict[str, Dict[str, Any]] = {}
        self.synonym_index: Dict[str, str] = {}
        self._loaded = False
        if os.path.exists(dict_path):
            self.load()
        else:
            logger.warning("MeSH dictionary file not found at %s. Service initialized empty.", dict_path)

    def load(self) -> None:
        """Loads MeSH dictionary and inverted index into memory."""
        logger.info("Loading MeSH dictionary from %s", self.dict_path)
        with open(self.dict_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.descriptors = data.get("descriptors", {})
        self.synonym_index = data.get("synonym_index", {})
        self._loaded = True
        logger.info("MeSH service loaded %d descriptors and %d synonyms.", len(self.descriptors), len(self.synonym_index))

    def resolve_concept(self, query_phrase: str) -> Optional[str]:
        """
        Maps a lay term, acronym, or natural-language phrase to its canonical MeSH descriptor.
        Example: 't2dm' -> 'Diabetes Mellitus, Type 2'
        """
        if not query_phrase:
            return None
        norm = query_phrase.strip().lower()
        return self.synonym_index.get(norm)

    def get_descriptor_info(self, descriptor_name: str) -> Optional[Dict[str, Any]]:
        """Returns metadata for a canonical descriptor."""
        return self.descriptors.get(descriptor_name)

    def get_synonyms(self, descriptor_name: str) -> List[str]:
        """Returns all known synonyms and acronyms for a descriptor."""
        info = self.descriptors.get(descriptor_name)
        if not info:
            return []
        return info.get("synonyms", [])

    def extract_mesh_concepts(self, text: str) -> List[str]:
        """
        Extracts matched MeSH concepts from an input query string.
        Uses exact substring matching across inverted index keys with word boundaries.
        """
        if not text:
            return []
        norm_text = f" {text.strip().lower()} "
        matched = set()

        sorted_keys = sorted(self.synonym_index.keys(), key=lambda k: len(k), reverse=True)
        for key in sorted_keys:
            if len(key) < 2:
                continue
            pattern = r"(?:\b|_)" + re.escape(key) + r"(?:\b|_)"
            if re.search(pattern, norm_text):
                canonical = self.synonym_index[key]
                matched.add(canonical)

        return sorted(list(matched))

    def search_prefix(self, prefix: str, limit: int = 10) -> List[str]:
        """Returns autocomplete suggestions for descriptors matching the prefix."""
        norm_prefix = prefix.strip().lower()
        if not norm_prefix:
            return []
        results = []
        for key, canonical in self.synonym_index.items():
            if key.startswith(norm_prefix):
                if canonical not in results:
                    results.append(canonical)
                if len(results) >= limit:
                    break
        return results
