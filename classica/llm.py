"""LLM access behind a small interface, so services never depend on a vendor.

`AnthropicClient` calls the Claude Messages API using only the standard library.
`build_llm_client()` returns None when no API key is set; services then fall
back to their offline strategies, which keeps the demo working without internet.
"""
from __future__ import annotations

import json
import os
import urllib.request
from abc import ABC, abstractmethod


class LLMClient(ABC):
    @abstractmethod
    def complete(self, system: str, prompt: str, max_tokens: int = 1500) -> str: ...


class AnthropicClient(LLMClient):
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str = "claude-sonnet-5-5", timeout: float = 90):
        self._key = api_key
        self.model = model
        self._timeout = timeout

    def complete(self, system: str, prompt: str, max_tokens: int = 1500) -> str:
        body = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(self.URL, data=body, method="POST", headers={
            "x-api-key": self._key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.load(resp)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


class FakeLLMClient(LLMClient):
    """Test double: records prompts and returns a canned answer."""

    def __init__(self, answer: str = "LLM answer"):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str, max_tokens: int = 1500) -> str:
        self.calls.append((system, prompt))
        return self.answer


def build_llm_client() -> LLMClient | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    return AnthropicClient(key, os.environ.get("CLASSICA_MODEL", "claude-sonnet-5-5"))
