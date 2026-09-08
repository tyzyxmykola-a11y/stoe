from __future__ import annotations

import difflib
import json
import math
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from stoe_agent.self_code_cycle_v2 import analyze_ollama_stream, atomic_json, record_transport_termination, strict_json_loads
from stoe_agent.token_budget import TokenBudgetManager, TokenEstimator

from .succession import EDITABLE_PATH, SuccessionError, patch_schema, reconstruct_candidate, run_bounded, sha256_bytes, validate_candidate_source, validate_patch_envelope


GEMMA = ("gemma4:26b", "08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68")
CODER = ("qwen3-coder:latest", "06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca")
ACTION_ID = "self-code-cycle:hermes-ab-v2:split-model-deduplicate-context"
MAX_WIRE_BYTES = 8_000_000
CONTEXT_LIMIT = 16_384


def plan_schema(path: str) -> dict[str, Any]:
    props = {
        "format": {"type": "string", "enum": ["stoe.development_plan"]},
        "version": {"type": "integer", "enum": [1]},
        "observed_limitation": {"type": "string", "maxLength": 600},
        "target_behavior": {"type": "string", "maxLength": 800},
        "editable_file": {"type": "string", "enum": [path]},
        "relevant_interfaces": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 180}},
        "invariants": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 220}},
        "acceptance_tests": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 220}},
        "risks": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 220}},
        "estimated_patch_lines": {"type": "integer", "minimum": 2, "maximum": 80},
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def validate_plan(value: Any, path: str) -> dict[str, Any]:
    required = set(plan_schema(path)["required"])
    if not isinstance(value, dict) or set(value) != required or value.get("format") != "stoe.development_plan" or value.get("version") != 1 or value.get("editable_file") != path:
        raise SuccessionError("invalid planning artifact envelope")
    text = json.dumps(value, ensure_ascii=False)
    if re.search(r"(?i)\b(?:def|class)\s+\w+\s*\(|\bimport\s+\w+|\bfrom\s+\S+\s+import\b|```|__builtins__|subprocess|socket", text):
        raise SuccessionError("planning artifact contains executable code or authority request")
    if not 2 <= int(value.get("estimated_patch_lines", 0)) <= 80:
        raise SuccessionError("invalid estimated patch scope")
    return value


def code_schema(path: str, parent_sha: str) -> dict[str, Any]:
    base = patch_schema(path, parent_sha)
    base["properties"].update({
        "rationale": {"type": "string", "maxLength": 800},
        "expected_tests": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 180}},
    })
    base["required"].extend(["rationale", "expected_tests"])
    return base


def validate_code(value: Any, parent: str, path: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"format", "version", "path", "parent_sha256", "replacement_lines", "rationale", "expected_tests"}:
        raise SuccessionError("invalid coding artifact envelope")
    if not isinstance(value["rationale"], str) or len(value["rationale"]) > 800 or not isinstance(value["expected_tests"], list):
        raise SuccessionError("invalid bounded coding metadata")
    core = {key: value[key] for key in ("format", "version", "path", "parent_sha256", "replacement_lines")}
    validate_patch_envelope(core, parent_sha256=sha256_bytes(parent.encode("utf-8")), path=path)
    candidate = reconstruct_candidate(parent, core)
    validation = validate_candidate_source(parent, candidate)
    sealed = {**value, "candidate_sha256": validation["candidate_sha256"]}
    return sealed, candidate, validation


def review_schema() -> dict[str, Any]:
    props = {
        "format": {"type": "string", "enum": ["stoe.candidate_review"]},
        "version": {"type": "integer", "enum": [1]},
        "verdict": {"type": "string", "enum": ["approve", "reject"]},
        "implements_plan": {"type": "boolean"},
        "preserves_connections": {"type": "boolean"},
        "likely_regressions": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 220}},
        "unnecessary_complexity": {"type": "string", "maxLength": 500},
        "suspicious_or_unrelated": {"type": "boolean"},
        "summary": {"type": "string", "maxLength": 800},
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def validate_review(value: Any) -> dict[str, Any]:
    required = set(review_schema()["required"])
    if not isinstance(value, dict) or set(value) != required or value.get("format") != "stoe.candidate_review" or value.get("version") != 1:
        raise SuccessionError("invalid review artifact")
    return value


class LocalModelClient:
    def __init__(self, endpoint: str = "http://127.0.0.1:11434") -> None:
        self.endpoint = endpoint.rstrip("/")

    def _json(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.endpoint + path, data=body, headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
        with urllib.request.urlopen(request, timeout=90) as response:
            return strict_json_loads(response.read().decode("utf-8"))

    def verify(self, name: str, digest: str) -> dict[str, Any]:
        models = self._json("/api/tags").get("models", [])
        found = next((item for item in models if item.get("name") == name), None)
        if not found or found.get("digest") != digest:
            raise SuccessionError(f"required local model identity unavailable: {name}")
        shown = self._json("/api/show", {"model": name})
        contexts = {k: int(v) for k, v in shown.get("model_info", {}).items() if k.endswith(".context_length")}
        return {"name": name, "digest": digest, "advertised_context": max(contexts.values()), "effective_context": min(CONTEXT_LIMIT, max(contexts.values()))}

    def generate(self, *, name: str, digest: str, system: str, prompt: str, schema: dict[str, Any], raw_path: Path, num_predict: int, seed: int) -> dict[str, Any]:
        self.verify(name, digest)
        if raw_path.exists():
            raise SuccessionError("raw response already exists; stable call cannot repeat")
        payload = {"model": name, "system": system, "prompt": prompt, "stream": True, "format": schema, "options": {"temperature": 0, "top_p": 0.9, "top_k": 40, "seed": seed, "num_ctx": CONTEXT_LIMIT, "num_predict": num_predict}, "keep_alive": "10m"}
        request = urllib.request.Request(self.endpoint + "/api/generate", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        error = None
        with raw_path.open("xb") as handle:
            try:
                with urllib.request.urlopen(request, timeout=900) as response:
                    while line := response.readline():
                        handle.write(line); handle.flush(); os.fsync(handle.fileno())
                        if handle.tell() > MAX_WIRE_BYTES:
                            raise RuntimeError("raw response exceeded byte limit")
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
        result = analyze_ollama_stream(raw_path.read_bytes(), output_limit_tokens=num_predict)
        record_transport_termination(result, error)
        result.update({"model": name, "digest": digest, "wall_seconds": round(time.monotonic() - started, 3), "raw_path": str(raw_path), "raw_sha256": sha256_bytes(raw_path.read_bytes()), "raw_bytes": raw_path.stat().st_size})
        return result


def budget_call(system: str, prompt: str, reserve: int) -> dict[str, Any]:
    return TokenBudgetManager(context_limit_tokens=CONTEXT_LIMIT, checkpoint_reserve_tokens=1024, estimator=TokenEstimator()).require_plan(system=system, prompt=prompt, reserved_generation_tokens=reserve)


def diff_text(parent: str, candidate: str) -> str:
    return "\n".join(difflib.unified_diff(parent.splitlines(), candidate.splitlines(), fromfile="parent", tofile="candidate", lineterm=""))
