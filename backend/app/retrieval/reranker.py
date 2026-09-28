"""MedCPT cross-encoder reranking with an explicit, deterministic fallback."""

from __future__ import annotations

import logging
import math
import re
import gc
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

from backend.app.models.request_response import RetrievalCandidate

logger = logging.getLogger(__name__)


class MedCPTReranker:
    """Lazily load the MedCPT Cross-Encoder and rerank candidate abstracts.

    If loading or inference fails, candidates are ordered by a transparent
    lexical coverage score and marked ``lexical_fallback`` in the typed result.
    """

    def __init__(
        self,
        model_name_or_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
        device: Optional[str] = None,
        allow_mock: bool = False,
        model: Any = None,
        tokenizer: Any = None,
    ) -> None:
        self.model_name_or_path = model_name_or_path
        self.cache_dir = cache_dir
        self.device = device
        # ``allow_mock`` permits explicit offline behavior elsewhere in the
        # MedCPT stack. This reranker never fabricates model scores: if the
        # checkpoint is absent it reports and uses the lexical fallback.
        self.allow_mock = bool(allow_mock)
        self._model = model
        self._tokenizer = tokenizer
        self._load_error: Optional[str] = None
        self._load_attempted = model is not None and tokenizer is not None

    def _load(self) -> bool:
        if self._load_attempted:
            return self._model is not None and self._tokenizer is not None
        self._load_attempted = True
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            from backend.app.core.config import get_settings

            settings = get_settings()
            model_name = self.model_name_or_path or settings.MEDCPT_CROSS_ENCODER
            cache_dir = self.cache_dir or settings.MODELS_CACHE_DIR
            device = self.device or settings.DEVICE
            self._tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
            self._model = AutoModelForSequenceClassification.from_pretrained(model_name, cache_dir=cache_dir)
            self._model.to(device)
            self._model.eval()
            self.device = device
            return True
        except Exception as exc:
            self._load_error = f"MedCPT Cross-Encoder unavailable: {exc}"
            logger.warning("%s", self._load_error)
            self._model = None
            self._tokenizer = None
            return False

    @staticmethod
    def _score_to_probability(logits: Any) -> np.ndarray:
        values = np.asarray(logits, dtype=np.float64)
        if values.ndim == 2 and values.shape[1] > 1:
            values = values[:, -1] - values[:, 0]
        else:
            values = values.reshape(-1)
        values = np.clip(values, -40.0, 40.0)
        scores = 1.0 / (1.0 + np.exp(-values))
        return scores.astype(np.float64)

    def _cross_encoder_scores(self, query: str, candidates: Sequence[RetrievalCandidate]) -> List[float]:
        import torch

        pairs = [
            (query, f"{candidate.title}\n{candidate.abstract}".strip())
            for candidate in candidates
        ]
        encoded = self._tokenizer(
            [pair[0] for pair in pairs],
            [pair[1] for pair in pairs],
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        target_device = self.device or "cpu"
        encoded = {key: value.to(target_device) for key, value in encoded.items()}
        with torch.no_grad():
            output = self._model(**encoded)
        logits = getattr(output, "logits", output[0] if isinstance(output, tuple) else output)
        scores = self._score_to_probability(logits.detach().cpu().numpy())
        if len(scores) != len(candidates) or not np.all(np.isfinite(scores)):
            raise ValueError("Cross-Encoder returned malformed or non-finite scores")
        return [float(value) for value in scores]

    @staticmethod
    def _lexical_score(query: str, candidate: RetrievalCandidate) -> float:
        from backend.app.retrieval.bm25 import tokenize_biomedical_text

        query_tokens = set(tokenize_biomedical_text(query))
        if not query_tokens:
            return 0.0
        text = " ".join(
            [candidate.title, candidate.abstract, *candidate.mesh_terms]
        )
        document_tokens = set(tokenize_biomedical_text(text))
        overlap = len(query_tokens & document_tokens) / len(query_tokens)
        normalized_query = re.sub(r"\s+", " ", query).strip().casefold()
        normalized_title = re.sub(r"\s+", " ", candidate.title).strip().casefold()
        phrase_bonus = 0.25 if normalized_query and normalized_query in normalized_title else 0.0
        return min(1.0, overlap * 0.75 + phrase_bonus)

    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievalCandidate],
        top_n: Optional[int] = None,
    ) -> Tuple[List[RetrievalCandidate], dict]:
        """Return sorted candidates and a trace describing the scoring mode."""
        if not candidates:
            return [], {"mode": "not_run", "reason": "no candidates", "reranked_count": 0}
        selected = list(candidates[:top_n] if top_n else candidates)
        remaining = list(candidates[len(selected):])
        if self._load():
            try:
                scores = self._cross_encoder_scores(query, selected)
                for candidate, score in zip(selected, scores):
                    candidate.reranker_score = score
                    candidate.reranker_mode = "medcpt"
                    candidate.fallback_reason = None
                mode = "medcpt"
                reason = None
            except Exception as exc:
                self._load_error = f"MedCPT Cross-Encoder inference failed: {exc}"
                logger.warning("%s; using lexical reranking", self._load_error)
                scores = [self._lexical_score(query, candidate) for candidate in selected]
                for candidate, score in zip(selected, scores):
                    candidate.reranker_score = score
                    candidate.reranker_mode = "lexical_fallback"
                    candidate.fallback_reason = self._load_error
                mode = "lexical_fallback"
                reason = self._load_error
        else:
            reason = self._load_error or "MedCPT Cross-Encoder was not available"
            scores = [self._lexical_score(query, candidate) for candidate in selected]
            for candidate, score in zip(selected, scores):
                candidate.reranker_score = score
                candidate.reranker_mode = "lexical_fallback"
                candidate.fallback_reason = reason
            mode = "lexical_fallback"

        selected.sort(key=lambda candidate: (-(candidate.reranker_score or 0.0), -candidate.rrf_score, candidate.pmid))
        for candidate in remaining:
            candidate.reranker_mode = "not_run"
            candidate.fallback_reason = None
        return selected + remaining, {
            "mode": mode,
            "reason": reason,
            "reranked_count": len(selected),
            "candidate_count": len(candidates),
        }

    def release(self) -> None:
        """Release lazily loaded model weights before another dense pass."""
        if self._model is None and self._tokenizer is None and not self._load_attempted:
            return
        model, tokenizer = self._model, self._tokenizer
        self._model = None
        self._tokenizer = None
        self._load_attempted = False
        del model, tokenizer
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
