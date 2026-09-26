"""
backend/app/retrieval/bm25.py
Biomedical BM25 Sparse Index Creation and Query Engine.
Tokenizes Title, Abstract, MeSH terms, and Keywords while preserving hyphenated
biomedical entities (e.g. GLP-1, SGLT-2, COVID-19).
Serializes index to data/processed/bm25_index.pkl.
Implements FEAT-R2-06.
"""

from typing import List, Dict, Any, Tuple, Union, Optional, Set
import re
import pickle
import logging
import hashlib
from pathlib import Path
import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# Standard English stop words safe for biomedical text search
STOP_WORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves"
}

# Regex preserving alphanumeric words and hyphenated biomedical entities
TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*")


def tokenize_biomedical_text(text: str) -> List[str]:
    """Tokenizes biomedical text, preserving hyphenated terms and filtering stopwords."""
    if not text:
        return []
    raw_tokens = TOKEN_PATTERN.findall(text.lower())
    return [t for t in raw_tokens if len(t) > 1 and t not in STOP_WORDS]


def token_to_sparse_index(token: str) -> int:
    """Map a lexical token to a stable positive Qdrant sparse-vector index."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFF


def build_qdrant_sparse_vector(text: str) -> Tuple[List[int], List[float]]:
    """Create deterministic term-frequency weights for Qdrant's IDF modifier.

    The collection applies inverse-document-frequency at query time.  Values
    here are normalized term frequencies, keeping the stored representation
    bounded while preserving repeated title/term emphasis.
    """
    tokens = tokenize_biomedical_text(text)
    if not tokens:
        return [], []
    counts: Dict[int, float] = {}
    for token in tokens:
        idx = token_to_sparse_index(token)
        counts[idx] = counts.get(idx, 0.0) + 1.0
    maximum = max(counts.values())
    ordered = sorted(counts.items())
    return [idx for idx, _ in ordered], [count / maximum for _, count in ordered]


class BM25Index:
    """
    Self-contained BM25 Index wrapper mapping document rank positions to PMIDs.
    Provides fast search and full serialization to/from pickle.
    """

    def __init__(
        self,
        bm25: BM25Okapi,
        pmids: List[int],
        avgdl: float,
        vocab_size: int,
    ):
        self.bm25 = bm25
        self.pmids = pmids
        self.pmid_to_idx = {pmid: i for i, pmid in enumerate(pmids)}
        self.avgdl = avgdl
        self.vocab_size = vocab_size

    @classmethod
    def build_from_records(cls, records: List[Dict[str, Any]]) -> "BM25Index":
        """
        Builds BM25 index over title, abstract, MeSH terms, and keywords.
        Title is doubled for increased term frequency weighting.
        """
        tokenized_corpus = []
        pmids = []
        vocab: Set[str] = set()

        for rec in records:
            pmid = int(rec["pmid"])
            pmids.append(pmid)

            title = str(rec.get("title", ""))
            abstract = str(rec.get("abstract", ""))
            mesh_val = rec.get("mesh_terms")
            if mesh_val is None:
                mesh_str = ""
            elif isinstance(mesh_val, (list, np.ndarray)):
                mesh_str = " ".join(str(m) for m in mesh_val if m)
            else:
                mesh_str = str(mesh_val)

            kw_val = rec.get("keywords")
            if kw_val is None:
                kw_str = ""
            elif isinstance(kw_val, (list, np.ndarray)):
                kw_str = " ".join(str(k) for k in kw_val if k)
            else:
                kw_str = str(kw_val)

            # Combine fields with 2x title weighting
            combined_text = f"{title} {title} {abstract} {mesh_str} {kw_str}"
            tokens = tokenize_biomedical_text(combined_text)
            tokenized_corpus.append(tokens)
            vocab.update(tokens)

        logger.info("Initializing BM25Okapi over %d documents (vocab size: %d)", len(tokenized_corpus), len(vocab))
        bm25 = BM25Okapi(tokenized_corpus, k1=1.5, b=0.75)
        avgdl = float(bm25.avgdl)

        return cls(
            bm25=bm25,
            pmids=pmids,
            avgdl=avgdl,
            vocab_size=len(vocab),
        )

    def search(self, query: str, top_k: int = 50) -> List[Tuple[int, float]]:
        """
        Computes BM25 scores for query and returns top_k (pmid, score) pairs sorted descending.
        """
        query_tokens = tokenize_biomedical_text(query)
        if not query_tokens:
            return []

        doc_scores = self.bm25.get_scores(query_tokens)

        n_docs = len(doc_scores)
        k = min(top_k, n_docs)
        if k == 0:
            return []

        top_indices = np.argpartition(doc_scores, -k)[-k:]
        top_indices = top_indices[np.argsort(-doc_scores[top_indices])]

        results = []
        for idx in top_indices:
            score = float(doc_scores[idx])
            if score > 0.0:
                results.append((self.pmids[idx], score))
        return results

    def save(self, filepath: Union[str, Path]) -> None:
        """Serializes BM25 index and PMID mapping to disk."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "bm25": self.bm25,
            "pmids": self.pmids,
            "avgdl": self.avgdl,
            "vocab_size": self.vocab_size,
        }
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(path)
        logger.info("Saved BM25Index to %s", path)

    @classmethod
    def load(cls, filepath: Union[str, Path]) -> "BM25Index":
        """Loads BM25 index from pickle."""
        path = Path(filepath)
        with open(path, "rb") as f:
            data = pickle.load(f)
        return cls(
            bm25=data["bm25"],
            pmids=data["pmids"],
            avgdl=data["avgdl"],
            vocab_size=data["vocab_size"],
        )
