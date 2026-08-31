from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from .retrieval import EmbeddingBackend


@dataclass(slots=True)
class GenerationParams:
    model: str
    temperature: float = 0.0
    top_p: float = 0.9
    top_k: int = 40
    seed: int = 9417
    num_ctx: int = 8192
    max_output_tokens: int = 192


@dataclass(slots=True)
class GenerationResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    metadata: dict[str, Any]


class OllamaClient:
    name = "ollama_local"

    def __init__(self, base_url: str, expected_model_digest: str | None = None, max_retries: int = 1):
        self.base_url = base_url.rstrip("/")
        self.expected_model_digest = expected_model_digest
        self.max_retries = max_retries

    def tags(self) -> dict:
        with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=20) as response:
            return json.loads(response.read().decode())

    def model_digest(self, model: str) -> str:
        for item in self.tags().get("models", []):
            if item.get("name") == model or item.get("model") == model:
                return str(item.get("digest", ""))
        raise RuntimeError(f"Ollama model not installed: {model}")

    def generate(self, prompt: str, context: str, params: GenerationParams) -> GenerationResult:
        digest = self.model_digest(params.model)
        if self.expected_model_digest and digest != self.expected_model_digest:
            raise RuntimeError(f"model digest mismatch: expected {self.expected_model_digest}, got {digest}")
        body = {
            "model": params.model,
            "stream": False,
            "think": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": compose_user_content(prompt, context)},
            ],
            "options": {
                "temperature": params.temperature,
                "top_p": params.top_p,
                "top_k": params.top_k,
                "seed": params.seed,
                "num_ctx": params.num_ctx,
                "num_predict": params.max_output_tokens,
            },
        }
        raw = json.dumps(body).encode()
        error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                request = urllib.request.Request(
                    f"{self.base_url}/api/chat", data=raw,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(request, timeout=180) as response:
                    payload = json.loads(response.read().decode())
                text = str(payload.get("message", {}).get("content", ""))
                return GenerationResult(
                    text=text,
                    input_tokens=int(payload.get("prompt_eval_count", 0)),
                    output_tokens=int(payload.get("eval_count", 0)),
                    latency_seconds=time.perf_counter() - started,
                    metadata={
                        "model": params.model, "model_digest": digest, "attempt": attempt + 1,
                        "prompt_eval_count": payload.get("prompt_eval_count", 0),
                        "eval_count": payload.get("eval_count", 0),
                        "total_duration_ns": payload.get("total_duration", 0),
                        "eval_duration_ns": payload.get("eval_duration", 0),
                    },
                )
            except Exception as exc:  # transport retry only
                error = exc
        raise RuntimeError(f"Ollama generation failed: {error}")


class OllamaEmbedder(EmbeddingBackend):
    def __init__(self, base_url: str, model: str, expected_digest: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.expected_digest = expected_digest
        self.name = f"ollama:{model}"
        self.calls = 0
        self.texts = 0
        self.latency_seconds = 0.0

    def _digest(self) -> str:
        client = OllamaClient(self.base_url)
        digest = client.model_digest(self.model)
        if self.expected_digest and digest != self.expected_digest:
            raise RuntimeError(f"embedding digest mismatch: expected {self.expected_digest}, got {digest}")
        return digest

    def encode(self, texts: list[str]) -> list[list[float]]:
        self._digest()
        started = time.perf_counter()
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=json.dumps({"model": self.model, "input": texts}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode())
        self.calls += 1
        self.texts += len(texts)
        self.latency_seconds += time.perf_counter() - started
        return [[float(value) for value in vector] for vector in payload["embeddings"]]


class DeterministicMockProvider:
    name = "deterministic_mock"

    def __init__(self, answers: dict[str, str]):
        self.answers = answers

    def generate(self, prompt: str, context: str, params: GenerationParams) -> GenerationResult:
        task_id = next(
            line.split(":", 1)[1].strip() for line in prompt.splitlines() if line.startswith("TASK_ID:")
        )
        answer = self.answers.get(task_id, "UNKNOWN")
        refs = [part.split("]", 1)[0] for part in context.split("[MEMORY_REF ")[1:]][:2]
        text = json.dumps({"answer": answer, "used_memory_refs": refs, "confidence": 0.9})
        return GenerationResult(text, len(prompt) // 4, len(text) // 4, 0.0, {"mock": True})


def compose_user_content(prompt: str, context: str) -> str:
    """Return the exact user message supplied to Ollama."""
    return prompt + "\n\nMEMORY_CONTEXT:\n" + (context or "(none)")


SYSTEM_PROMPT = """You are solving a controlled reasoning task.
Return one JSON object with exactly these fields:
{"answer":"TASK_DOMAIN_ANSWER", "used_memory_refs":["IP_00002"], "confidence":0.0}
The answer must be the task-domain answer token requested by the question. Never put a MEMORY_REF, IP_ reference, SEED_ reference, UUID, or storage identifier in answer. Internal references belong only in used_memory_refs. Use only memory references actually shown. Do not add prose outside JSON."""
