from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .token_budget import TokenBudgetManager, TokenEstimator


@dataclass(frozen=True)
class ModelIdentity:
    name: str
    digest: str
    ollama_version: str


class OllamaClient:
    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:11434",
        model: str = "qwen3-coder:latest",
        timeout_seconds: int = 240,
        context_limit_tokens: int = 8192,
        checkpoint_reserve_tokens: int = 512,
        tokenizer=None,
        tokenizer_name: str = "conservative_utf8_bytes_div_3",
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.context_limit_tokens = context_limit_tokens
        self.budget_manager = TokenBudgetManager(
            context_limit_tokens=context_limit_tokens,
            checkpoint_reserve_tokens=checkpoint_reserve_tokens,
            estimator=TokenEstimator(tokenizer=tokenizer, tokenizer_name=tokenizer_name),
        )

    def _json_request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if data is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed for {path}: {exc}") from exc

    def identity(self) -> ModelIdentity:
        version = str(self._json_request("/api/version").get("version", "unknown"))
        tags = self._json_request("/api/tags").get("models", [])
        match = next((item for item in tags if item.get("name") == self.model), None)
        if match is None:
            raise RuntimeError(f"Ollama model is not installed: {self.model}")
        return ModelIdentity(self.model, str(match.get("digest", "")), version)

    def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        max_output_tokens: int,
        seed: int,
        context_sections: dict[str, str] | None = None,
        truncation_events: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        budget = self.budget_manager.require_plan(
            system=system,
            prompt=prompt,
            reserved_generation_tokens=max_output_tokens,
            categories=context_sections,
            truncation_events=truncation_events,
        )
        payload = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "options": {
                "temperature": 0,
                "top_p": 0.9,
                "top_k": 40,
                "seed": seed,
                "num_ctx": self.context_limit_tokens,
                "num_predict": max_output_tokens,
            },
            "keep_alive": "10m",
        }
        raw = self._json_request("/api/generate", payload)
        response_text = str(raw.get("response", "")).strip()
        response_channel = "response"
        if not response_text and str(raw.get("thinking", "")).strip():
            response_text = str(raw["thinking"]).strip()
            response_channel = "thinking"
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned malformed JSON: {exc}") from exc
        response_trace = {key: value for key, value in raw.items() if key != "context"}
        provider_usage = {
            "prompt_tokens": raw.get("prompt_eval_count"),
            "output_tokens": raw.get("eval_count"),
            "total_tokens": (
                int(raw.get("prompt_eval_count", 0)) + int(raw.get("eval_count", 0))
                if raw.get("prompt_eval_count") is not None and raw.get("eval_count") is not None
                else None
            ),
            "source": "ollama_provider_counts" if raw.get("prompt_eval_count") is not None else "unavailable",
        }
        budget["actual_provider_usage"] = provider_usage
        trace = {
            "request": payload,
            "response": response_trace,
            "parsed_response_channel": response_channel,
            "omitted_response_fields": ["context"] if "context" in raw else [],
            "token_budget": budget,
            "provider_token_usage": provider_usage,
        }
        return parsed, trace
