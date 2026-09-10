from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .local_development import (
    LocalDevelopmentError,
    control_schema,
    load_instructions,
    model_instructions,
    parse_preserved_control,
    record_envelope,
    trusted_envelope,
)
from .token_budget import TokenBudgetManager, TokenEstimator


ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9:._-]{5,127}$")
TERMINAL = {"completed", "failed", "uncertain"}
MAX_CONTEXT_ITEMS = 12
MAX_CONTEXT_CHARS = 8_000
MAX_ITEM_CHARS = 1_000


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LocalDevelopmentError(f"expected JSON object at {path}")
    return value


def _bounded_context(items: list[str]) -> list[str]:
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_CONTEXT_ITEMS:
        raise LocalDevelopmentError("planner context must contain 1..12 items")
    if any(not isinstance(item, str) or not item or len(item) > MAX_ITEM_CHARS for item in items):
        raise LocalDevelopmentError("planner context item is empty or oversized")
    if sum(len(item) for item in items) > MAX_CONTEXT_CHARS:
        raise LocalDevelopmentError("planner context exceeds its aggregate cap")
    return list(items)


class LocalDevelopmentRunner:
    """Trusted, single-call local worker boundary with stable-action recovery."""

    def __init__(
        self,
        *,
        api: Any,
        artifact_root: Path,
        field: Any | None = None,
        context_limit_tokens: int = 8192,
        output_tokens: int = 1200,
        timeout_seconds: int = 420,
        seed: int = 4402,
    ) -> None:
        if not 1024 <= context_limit_tokens <= 16_384:
            raise LocalDevelopmentError("invalid fixed context limit")
        if not 128 <= output_tokens <= 1_200:
            raise LocalDevelopmentError("invalid output reserve")
        if not 1 <= timeout_seconds <= 900:
            raise LocalDevelopmentError("invalid timeout")
        self.api = api
        self.artifact_root = artifact_root.resolve()
        self.field = field
        self.context_limit_tokens = context_limit_tokens
        self.output_tokens = output_tokens
        self.timeout_seconds = timeout_seconds
        self.seed = seed
        self.estimator = TokenEstimator()

    def _identity(self, model: str, expected_digest: str) -> dict[str, str]:
        version = str(self.api.json("/api/version").get("version", "unknown"))
        models = self.api.json("/api/tags").get("models", [])
        match = next((item for item in models if item.get("name") == model), None)
        if match is None:
            raise LocalDevelopmentError(f"required local model is not installed: {model}")
        digest = str(match.get("digest", ""))
        if digest != expected_digest:
            raise LocalDevelopmentError("local model digest mismatch")
        return {"model": model, "digest": digest, "ollama_version": version}

    @staticmethod
    def _run_name(action_id: str) -> str:
        if not isinstance(action_id, str) or not ACTION_RE.fullmatch(action_id):
            raise LocalDevelopmentError("invalid stable action ID")
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", action_id)

    def _record(self, envelope: dict[str, Any], *, goal: str, session_id: str) -> dict[str, Any] | None:
        if self.field is None:
            return None
        return record_envelope(self.field, envelope, goal=goal, session_id=session_id)

    def _recover(
        self,
        *,
        manifest_path: Path,
        raw_path: Path,
        envelope_path: Path,
        expected_identity: dict[str, Any],
        goal: str,
        session_id: str,
        instructions: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        manifest = _read_json(manifest_path)
        for key, expected in expected_identity.items():
            if manifest.get(key) != expected:
                raise LocalDevelopmentError(f"stable action identity mismatch: {key}")
        status = manifest.get("status")
        if status == "completed":
            envelope = _read_json(envelope_path)
            refs = self._record(envelope, goal=goal, session_id=session_id)
            return {"status": "completed", "recovered": True, "called_model": False, "manifest": manifest, "envelope": envelope, "field_refs": refs}
        if status in {"failed", "uncertain"}:
            raise LocalDevelopmentError(f"stable action is closed with status {status}")
        if status != "started":
            raise LocalDevelopmentError("invalid stable action state")
        if not raw_path.is_file():
            manifest.update({"status": "uncertain", "failure": "interrupted before raw response preservation"})
            _atomic_json(manifest_path, manifest)
            raise LocalDevelopmentError("interrupted stable action closed as uncertain")
        try:
            control = parse_preserved_control(raw_path.read_bytes(), raw_path, known_metadata=tuple(str(value) for value in expected_identity.values()))
            envelope = trusted_envelope(control, action_id=manifest["action_id"], role="planner", model=manifest["model"], digest=manifest["digest"], instructions=instructions)
        except LocalDevelopmentError as exc:
            manifest.update({"status": "failed", "failure": str(exc)})
            _atomic_json(manifest_path, manifest)
            raise
        _atomic_json(envelope_path, envelope)
        manifest.update({"status": "completed", "recovered_from_raw": True, "envelope_sha256": _sha256(envelope_path.read_bytes())})
        _atomic_json(manifest_path, manifest)
        refs = self._record(envelope, goal=goal, session_id=session_id)
        return {"status": "completed", "recovered": True, "called_model": False, "manifest": manifest, "envelope": envelope, "field_refs": refs}

    def run_planner(
        self,
        *,
        action_id: str,
        model: str,
        expected_digest: str,
        goal: str,
        constraints: list[str],
        context_items: list[str],
        session_id: str = "development:local-development-v2",
    ) -> dict[str, Any]:
        run_dir = self.artifact_root / self._run_name(action_id)
        manifest_path = run_dir / "manifest.json"
        raw_path = run_dir / "raw_response.json"
        envelope_path = run_dir / "validated_envelope.json"
        instructions = load_instructions("planner")
        identity = self._identity(model, expected_digest)
        if not isinstance(goal, str) or not goal or len(goal) > 1_500:
            raise LocalDevelopmentError("planner goal is empty or oversized")
        if not isinstance(constraints, list) or len(constraints) > 16 or any(not isinstance(item, str) or not item or len(item) > 320 for item in constraints):
            raise LocalDevelopmentError("planner constraints are invalid")
        context_items = _bounded_context(context_items)
        prompt_value = {"goal": goal, "constraints": constraints, "bounded_stoe_context": context_items}
        prompt = json.dumps(prompt_value, ensure_ascii=False, sort_keys=True)
        system, _ = model_instructions("planner")
        system += "\n\nYou have no tools, filesystem, shell, network, memory-write, Git, test, patch, or activation authority."
        budget = TokenBudgetManager(context_limit_tokens=self.context_limit_tokens, checkpoint_reserve_tokens=512, estimator=self.estimator).require_plan(
            system=system,
            prompt=prompt,
            reserved_generation_tokens=self.output_tokens,
            categories={"task_context": json.dumps({"goal": goal, "constraints": constraints}, ensure_ascii=False), "retrieved_material": json.dumps(context_items, ensure_ascii=False), "tool_results": ""},
        )
        instruction_ids = {key: {name: item[name] for name in ("version", "path", "sha256")} for key, item in instructions.items()}
        expected_identity = {
            "action_id": action_id,
            "role": "planner",
            "model": identity["model"],
            "digest": identity["digest"],
            "prompt_sha256": _sha256(prompt.encode("utf-8")),
            "instructions": instruction_ids,
        }
        if manifest_path.is_file():
            return self._recover(manifest_path=manifest_path, raw_path=raw_path, envelope_path=envelope_path, expected_identity=expected_identity, goal=goal, session_id=session_id, instructions=instructions)
        run_dir.mkdir(parents=True, exist_ok=False)
        manifest = {**expected_identity, "status": "started", "ollama_version": identity["ollama_version"], "token_budget": budget}
        _atomic_json(manifest_path, manifest)
        payload = {
            "model": model,
            "think": False,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": control_schema(),
            "options": {"temperature": 0, "top_p": 0.9, "top_k": 40, "seed": self.seed, "num_ctx": self.context_limit_tokens, "num_predict": self.output_tokens},
            "keep_alive": "10m",
        }
        started = time.monotonic()
        try:
            raw = self.api.request("/api/generate", payload, timeout=self.timeout_seconds)
        except Exception as exc:
            manifest.update({"status": "uncertain", "failure": f"provider call did not return: {type(exc).__name__}"})
            _atomic_json(manifest_path, manifest)
            raise LocalDevelopmentError("provider call failed; stable action closed as uncertain") from exc
        duration = time.monotonic() - started
        try:
            control = parse_preserved_control(raw, raw_path, known_metadata=tuple(str(value) for value in expected_identity.values() if not isinstance(value, dict)))
            envelope = trusted_envelope(control, action_id=action_id, role="planner", model=model, digest=expected_digest, instructions=instructions)
        except LocalDevelopmentError as exc:
            manifest.update({"status": "failed", "failure": str(exc), "raw_sha256": _sha256(raw)})
            _atomic_json(manifest_path, manifest)
            raise
        _atomic_json(envelope_path, envelope)
        provider = json.loads(raw.decode("utf-8"))
        manifest.update({
            "status": "completed",
            "duration_seconds": round(duration, 3),
            "raw_sha256": _sha256(raw),
            "envelope_sha256": _sha256(envelope_path.read_bytes()),
            "prompt_tokens": provider.get("prompt_eval_count"),
            "output_tokens": provider.get("eval_count"),
            "done_reason": provider.get("done_reason"),
        })
        _atomic_json(manifest_path, manifest)
        refs = self._record(envelope, goal=goal, session_id=session_id)
        return {"status": "completed", "recovered": False, "called_model": True, "manifest": manifest, "envelope": envelope, "field_refs": refs}
