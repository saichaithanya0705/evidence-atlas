"""Construct NVIDIA NIM OpenAI clients with a single explicit TLS context."""

from __future__ import annotations

import ssl
from typing import Any

import certifi
import httpx2
from openai import OpenAI


def create_nim_client(settings: Any) -> OpenAI:
    """Build a bounded NIM client without nesting system truststore wrappers."""
    tls_context = ssl.create_default_context(cafile=certifi.where())
    http_client = httpx2.Client(
        verify=tls_context,
        timeout=float(settings.LLM_TIMEOUT_SECONDS),
    )
    return OpenAI(
        base_url=settings.NVIDIA_BASE_URL,
        api_key=settings.get_raw_nvidia_api_key(),
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=0,
        http_client=http_client,
    )
