"""Construct NVIDIA NIM OpenAI clients with a single explicit TLS context."""

from __future__ import annotations

import ssl
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from typing import Any

import certifi
import httpx2
from openai import OpenAI

_request_deadline: ContextVar[dict | None] = ContextVar("nim_request_deadline", default=None)


@contextmanager
def llm_request_scope(seconds: float):
    """Bound cumulative provider waiting without sharing state across requests."""
    existing = _request_deadline.get()
    token = _request_deadline.set(existing if existing is not None else {"deadline": None, "seconds": seconds})
    try:
        yield
    finally:
        _request_deadline.reset(token)


def llm_time_remaining() -> float | None:
    deadline = _request_deadline.get()
    return None if deadline is None or deadline["deadline"] is None else max(0.0, deadline["deadline"] - monotonic())


def structured_completion_options(settings: Any, *, timeout_seconds: float | None = None) -> dict:
    call_timeout = float(getattr(settings, "LLM_STRUCTURED_TIMEOUT_SECONDS", 10)) if timeout_seconds is None else float(timeout_seconds)
    timeout = min(float(getattr(settings, "LLM_TIMEOUT_SECONDS", 30)), call_timeout)
    scope = _request_deadline.get()
    if scope is not None and scope["deadline"] is None:
        # Cold model/index loading precedes provider waiting; do not consume
        # the LLM budget before the first live call has even been attempted.
        scope["deadline"] = monotonic() + scope["seconds"]
    remaining = llm_time_remaining()
    if remaining is not None:
        if remaining <= 0:
            raise TimeoutError("Research provider time budget exhausted")
        timeout = min(timeout, remaining)
    return {
        "timeout": timeout,
        "response_format": {"type": "json_object"},
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }


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
