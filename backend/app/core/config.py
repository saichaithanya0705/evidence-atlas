"""
Application Configuration Loader.
Satisfies: FEAT-R1-03 (Environment Configuration & Secret Hygiene).
Features:
- Typed settings using pydantic-settings.
- Secret hygiene via SecretStr (never prints API key in plaintext).
- Automatic device fallback (CUDA if healthy, else CPU).
- Centralized caching via @lru_cache.
"""

import os
from pathlib import Path
from functools import lru_cache
from typing import List, Optional
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM / NVIDIA NIM Configuration
    ADMIN_API_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Optional shared key required for administrator-only diagnostic endpoints",
    )
    NVIDIA_API_KEY: Optional[SecretStr] = Field(default=None, description="NVIDIA API Key")
    NVIDIA_BASE_URL: str = Field(default="https://integrate.api.nvidia.com/v1")
    NVIDIA_MODEL_NAME: str = Field(default="nvidia/nemotron-3-super-120b-a12b")
    LLM_MODE: str = Field(default="mock", description="'nim', 'mock', or 'openai'")
    LLM_TEMPERATURE: float = Field(default=0.1)
    LLM_MAX_TOKENS: int = Field(default=2048)
    LLM_SYNTHESIS_MAX_TOKENS: int = Field(default=300, ge=128, le=2048)
    LLM_TIMEOUT_SECONDS: float = Field(default=30.0)

    # Storage & Knowledge Base Paths
    QDRANT_STORAGE_PATH: str = Field(default="./data/qdrant_storage")
    QDRANT_COLLECTION_NAME: str = Field(default="medical_abstracts")
    RAW_DATA_PATH: str = Field(default="./data/raw/pubmed_sample.csv")
    CLEANED_DATA_PATH: str = Field(default="./data/processed/cleaned_pubmed.parquet")
    BM25_INDEX_PATH: str = Field(default="./data/processed/bm25_index.pkl")
    MESH_GRAPH_PATH: str = Field(default="./data/processed/mesh_graph.gpickle")
    MESH_DICT_PATH: str = Field(default="./data/processed/mesh_dictionary.json")
    INDEX_MANIFEST_PATH: str = Field(default="./data/manifests/index_manifest.json")

    # MedCPT Models & Inference
    MEDCPT_QUERY_ENCODER: str = Field(default="ncbi/MedCPT-Query-Encoder")
    MEDCPT_ARTICLE_ENCODER: str = Field(default="ncbi/MedCPT-Article-Encoder")
    MEDCPT_CROSS_ENCODER: str = Field(default="ncbi/MedCPT-Cross-Encoder")
    MODELS_CACHE_DIR: str = Field(default="./data/models_cache")
    MEDCPT_ALLOW_MOCK: bool = Field(
        default=False,
        description="Explicitly allow deterministic non-MedCPT embeddings for offline demos/tests",
    )
    MEDCPT_KEEP_MODELS_LOADED: bool = Field(
        default=False,
        description="Retain query and cross-encoder weights between requests when memory permits",
    )
    DEVICE: str = Field(default="auto")
    EMBEDDING_DIMENSION: int = Field(default=768)
    EMBEDDING_BATCH_SIZE: int = Field(default=32)

    # Retrieval & Reranker Hyperparameters
    RRF_K: int = Field(default=60)
    DENSE_TOP_K: int = Field(default=30)
    SPARSE_TOP_K: int = Field(default=30)
    RERANKER_TOP_N: int = Field(default=10)
    MAX_SUBQUERIES: int = Field(default=4)
    MAX_CORRECTIVE_LOOPS: int = Field(default=2)

    # Service & Telemetry
    APP_ENV: str = Field(default="development")
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    LOG_LEVEL: str = Field(default="INFO")
    TRACE_MAX_ENTRIES: int = Field(default=500, ge=10, le=10000)
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("DEVICE", mode="after")
    @classmethod
    def resolve_device(cls, v: str) -> str:
        """Resolve 'auto' to 'cuda' if torch reports CUDA is available, else 'cpu'."""
        if v.lower() == "auto":
            try:
                import torch
                return "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                return "cpu"
        return v.lower()

    def get_raw_nvidia_api_key(self) -> Optional[str]:
        """Safely extract plain text NVIDIA API key without logging it."""
        return self.NVIDIA_API_KEY.get_secret_value() if self.NVIDIA_API_KEY else None

    def get_raw_admin_api_key(self) -> Optional[str]:
        """Return the configured admin key, treating an empty value as disabled."""
        if self.ADMIN_API_KEY is None:
            return None
        value = self.ADMIN_API_KEY.get_secret_value()
        return value if value.strip() else None


@lru_cache()
def get_settings() -> Settings:
    """Singleton getter for application settings."""
    return Settings()
