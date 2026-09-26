"""
backend/app/retrieval/medcpt.py
MedCPT Article and Query dense embedding generation module.
Implements 768-dim embedding computation using ncbi/MedCPT models with [CLS] pooling,
L2 normalization, and CPU/GPU device safety.
Supports offline deterministic fallback for unit tests and air-gapped environments.
"""

from typing import List, Tuple, Union, Optional
import os
import hashlib
import logging
import numpy as np

logger = logging.getLogger(__name__)

ARTICLE_ENCODER_MODEL = "ncbi/MedCPT-Article-Encoder"
QUERY_ENCODER_MODEL = "ncbi/MedCPT-Query-Encoder"
EMBEDDING_DIM = 768
MAX_LENGTH = 512


def get_optimal_device():
    """Detects available hardware accelerator with safe fallback to CPU."""
    try:
        import torch
        if torch.cuda.is_available():
            return torch.device("cuda")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    except ImportError:
        return "cpu"


def _generate_deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> np.ndarray:
    """Generates a deterministic L2-normalized pseudo-embedding from text hash for offline/mock fallback."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.RandomState(seed)
    vec = rng.randn(dim).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


class MedCPTArticleEncoder:
    """
    Computes 768-dim dense representations for biomedical articles (Title + Abstract).
    Uses [CLS] token pooling and L2 normalization per NCBI MedCPT specification.
    """

    def __init__(
        self,
        model_name_or_path: str = ARTICLE_ENCODER_MODEL,
        device=None,
        batch_size: int = 32,
        cache_dir: Optional[str] = "data/models_cache",
        allow_mock: Optional[bool] = None,
    ):
        self.device = device or get_optimal_device()
        self.batch_size = batch_size
        self.model_name = model_name_or_path
        self.cache_dir = cache_dir
        self.allow_mock = (
            allow_mock
            if allow_mock is not None
            else os.getenv("MEDCPT_ALLOW_MOCK", "false").strip().lower() in {"1", "true", "yes", "on"}
        )
        self.is_mock = False

        try:
            import torch
            from transformers import AutoTokenizer, AutoModel
            logger.info("Loading MedCPT Article Encoder from %s onto %s", self.model_name, self.device)
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, cache_dir=self.cache_dir)
            self.model = AutoModel.from_pretrained(self.model_name, cache_dir=self.cache_dir)
            self.model.to(self.device)
            self.model.eval()
        except Exception as e:
            if not self.allow_mock:
                raise RuntimeError(
                    f"MedCPT Article Encoder could not be loaded from {self.model_name}. "
                    "Run scripts/setup_assets.py or explicitly set MEDCPT_ALLOW_MOCK=true for an offline demo."
                ) from e
            logger.warning("MedCPT Article Encoder unavailable (%s); explicit mock mode is enabled.", e)
            self.is_mock = True

    def encode_articles(
        self,
        titles: List[str],
        abstracts: List[str],
        show_progress: bool = False,
    ) -> np.ndarray:
        """
        Encodes article title and abstract pairs into an (N, 768) float32 L2-normalized numpy array.
        """
        assert len(titles) == len(abstracts), "titles and abstracts must have identical lengths"
        total = len(titles)
        if total == 0:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        if self.is_mock:
            embeddings_list = []
            for t, a in zip(titles, abstracts):
                combined = f"{str(t or '').strip()} {str(a or '').strip()}"
                embeddings_list.append(_generate_deterministic_embedding(combined))
            return np.vstack(embeddings_list)

        import torch
        pairs = [[str(t or "").strip(), str(a or "").strip()] for t, a in zip(titles, abstracts)]
        embeddings_list = []

        iterator = range(0, total, self.batch_size)
        if show_progress:
            from tqdm import tqdm
            iterator = tqdm(iterator, desc="Encoding MedCPT Articles", total=(total + self.batch_size - 1) // self.batch_size)

        with torch.no_grad():
            for i in iterator:
                batch_pairs = pairs[i : i + self.batch_size]
                encoded = self.tokenizer(
                    batch_pairs,
                    padding=True,
                    truncation=True,
                    max_length=MAX_LENGTH,
                    return_tensors="pt",
                ).to(self.device)

                outputs = self.model(**encoded)
                # MedCPT pooling: [CLS] token at index 0
                cls_repr = outputs.last_hidden_state[:, 0, :]
                norm_repr = torch.nn.functional.normalize(cls_repr, p=2, dim=1)
                embeddings_list.append(norm_repr.cpu().numpy().astype(np.float32))

        return np.vstack(embeddings_list)


class MedCPTQueryEncoder:
    """
    Computes 768-dim dense representations for search queries using ncbi/MedCPT-Query-Encoder.
    Uses [CLS] token pooling and L2 normalization.
    """

    def __init__(
        self,
        model_name_or_path: str = QUERY_ENCODER_MODEL,
        device=None,
        cache_dir: Optional[str] = "data/models_cache",
        allow_mock: Optional[bool] = None,
    ):
        self.device = device or get_optimal_device()
        self.model_name = model_name_or_path
        self.cache_dir = cache_dir
        self.allow_mock = (
            allow_mock
            if allow_mock is not None
            else os.getenv("MEDCPT_ALLOW_MOCK", "false").strip().lower() in {"1", "true", "yes", "on"}
        )
        self.is_mock = False

        try:
            import torch
            from transformers import AutoTokenizer, AutoModel
            logger.info("Loading MedCPT Query Encoder from %s onto %s", self.model_name, self.device)
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, cache_dir=self.cache_dir)
            self.model = AutoModel.from_pretrained(self.model_name, cache_dir=self.cache_dir)
            self.model.to(self.device)
            self.model.eval()
        except Exception as e:
            if not self.allow_mock:
                raise RuntimeError(
                    f"MedCPT Query Encoder could not be loaded from {self.model_name}. "
                    "Run scripts/setup_assets.py or explicitly set MEDCPT_ALLOW_MOCK=true for an offline demo."
                ) from e
            logger.warning("MedCPT Query Encoder unavailable (%s); explicit mock mode is enabled.", e)
            self.is_mock = True

    def encode_queries(self, queries: List[str]) -> np.ndarray:
        """Encodes queries into an (N, 768) float32 normalized array."""
        if not queries:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        if self.is_mock:
            embeddings_list = [_generate_deterministic_embedding(q) for q in queries]
            return np.vstack(embeddings_list)

        import torch
        with torch.no_grad():
            encoded = self.tokenizer(
                queries,
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            ).to(self.device)
            outputs = self.model(**encoded)
            cls_repr = outputs.last_hidden_state[:, 0, :]
            norm_repr = torch.nn.functional.normalize(cls_repr, p=2, dim=1)
            return norm_repr.cpu().numpy().astype(np.float32)

    def encode_query(self, query: str) -> np.ndarray:
        """Encodes a single query string into a 1D 768-dim float32 array."""
        return self.encode_queries([query])[0]
