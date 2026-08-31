"""
LLM interface
=============
Defines the abstract `LLMClient` protocol consumed by operators in slice 2,
plus two concrete implementations:

  • OllamaClient — calls a local Ollama instance (the v82 setup).
  • MockLLM      — deterministic, used by tests.

The protocol is deliberately tiny: operators only need to send a prompt
string and receive a response string. They do not need streaming, function
calling, or model selection inside the operator. Prompts are built by the
operator from the graph state; the LLM is dumb tail logic.
"""

from __future__ import annotations

import json
from typing import Callable, Protocol


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class LLMClient(Protocol):
    """Anything callable as `client.call(prompt) -> str`."""

    def call(self, prompt: str) -> str: ...


# ---------------------------------------------------------------------------
# Ollama (real)
# ---------------------------------------------------------------------------

class OllamaClient:
    """
    Thin client over Ollama's /api/chat endpoint. Used when v3 is run
    against a local model. Not used by tests.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
        timeout: int = 240,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def call(self, prompt: str) -> str:
        import requests
        try:
            r = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=self.timeout,
            )
        except Exception as e:
            raise OllamaError(f"transport error: {e}") from e
        if r.status_code != 200:
            raise OllamaError(f"http {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["message"]["content"]
        except (KeyError, json.JSONDecodeError) as e:
            raise OllamaError(f"unexpected response shape: {e}") from e


class OllamaError(RuntimeError):
    """Raised when the Ollama backend fails. Operators catch this and
    conserve the failure as a Ghost node via field.add_failed."""


# ---------------------------------------------------------------------------
# Mock (tests)
# ---------------------------------------------------------------------------

class MockLLM:
    """
    Deterministic LLM stub.

    Construct with either:
      • a list of canned responses (consumed left-to-right per call)
      • a callable `prompt -> response`

    Records every prompt sent in `self.calls` and every response in
    `self.responses_log` so tests can assert the operator built the
    expected prompt content.
    """

    def __init__(
        self,
        responses: list[str] | Callable[[str], str] | None = None,
    ):
        if responses is None:
            responses = []
        self.responses = responses
        self.calls: list[str] = []
        self.responses_log: list[str] = []

    def call(self, prompt: str) -> str:
        self.calls.append(prompt)
        if callable(self.responses):
            r = self.responses(prompt)
        elif self.responses:
            r = self.responses.pop(0) if isinstance(self.responses, list) else "default"
        else:
            r = "[mock] no canned response left"
        self.responses_log.append(r)
        return r

    def last_call(self) -> str | None:
        return self.calls[-1] if self.calls else None
