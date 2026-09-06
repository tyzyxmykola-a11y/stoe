from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


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
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

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
    ) -> tuple[dict[str, Any], dict[str, Any]]:
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
                "num_ctx": 8192,
                "num_predict": max_output_tokens,
            },
            "keep_alive": "10m",
        }
        raw = self._json_request("/api/generate", payload)
        response_text = str(raw.get("response", ""))
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned malformed JSON: {exc}") from exc
        response_trace = {key: value for key, value in raw.items() if key != "context"}
        trace = {
            "request": payload,
            "response": response_trace,
            "omitted_response_fields": ["context"] if "context" in raw else [],
        }
        return parsed, trace
