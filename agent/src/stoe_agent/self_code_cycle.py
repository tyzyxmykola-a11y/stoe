from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .development_report import render_retrieved_context
from .ollama import OllamaClient
from .token_budget import TokenBudgetManager, TokenEstimator


ACTION_ID = "self-code-cycle:v1:deduplicate-development-context"
MODEL_NAME = "gemma4:26b"
PATCH_FORMAT = "stoe.source_patch"
PATCH_VERSION = 1
EDITABLE_PATH = "agent/src/stoe_agent/development_report.py"
MAX_OBJECTIVE_CHARS = 1200
MAX_SOURCE_CHARS = 20_000
MAX_RATIONALE_CHARS = 3000
MAX_RISK_ITEMS = 8
MAX_RISK_CHARS = 500
MAX_PATCH_BYTES = 32_000
MAX_RETRIEVED_ITEMS = 6
MAX_RETRIEVED_CHARS = 7000
OUTPUT_RESERVE_TOKENS = 4096
CHECKPOINT_RESERVE_TOKENS = 1024
MAX_EFFECTIVE_CONTEXT = 16_384

PROTECTED_PREFIXES = (
    ".git/",
    "agent/protected_evals/",
    "agent/research_checkpoints/",
    "agent/research_state/",
    "agent/rebuild_reports/",
    "agent/src/stoe_agent/supervisor.py",
    "agent/src/stoe_agent/self_code_cycle.py",
    "agent/src/stoe_agent/selection_policy.py",
    "agent/src/stoe_agent/selector_loader.py",
    "agent/owned_components/",
)
DEPENDENCY_NAMES = {
    "pyproject.toml",
    "requirements.txt",
    "poetry.lock",
    "pdm.lock",
    "uv.lock",
    "package.json",
    "package-lock.json",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_\-]{20,}\b"),
)

PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "format": {"type": "string", "enum": [PATCH_FORMAT]},
        "version": {"type": "integer", "enum": [PATCH_VERSION]},
        "objective": {"type": "string", "maxLength": MAX_OBJECTIVE_CHARS},
        "rationale": {"type": "string", "maxLength": MAX_RATIONALE_CHARS},
        "file": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "enum": [EDITABLE_PATH]},
                "base_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "content": {"type": "string", "maxLength": MAX_SOURCE_CHARS},
            },
            "required": ["path", "base_sha256", "content"],
            "additionalProperties": False,
        },
        "expected_effect": {"type": "string", "maxLength": 1200},
        "risks": {
            "type": "array",
            "maxItems": MAX_RISK_ITEMS,
            "items": {"type": "string", "maxLength": MAX_RISK_CHARS},
        },
        "suggested_test_ids": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "string",
                "enum": [
                    "report_contract",
                    "duplicate_hash_fixture",
                    "character_budget_fixture",
                    "input_immutability_fixture",
                ],
            },
        },
    },
    "required": [
        "format",
        "version",
        "objective",
        "rationale",
        "file",
        "expected_effect",
        "risks",
        "suggested_test_ids",
    ],
    "additionalProperties": False,
}


class PatchBoundaryError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _validate_keys(value: dict[str, Any], required: set[str], *, label: str) -> None:
    if set(value) != required:
        raise PatchBoundaryError(f"{label} fields must be exactly {sorted(required)}")


def validate_patch_artifact(
    artifact: dict[str, Any], *, repo_root: Path
) -> dict[str, Any]:
    """Validate an inert complete-file patch without importing or executing it."""

    if not isinstance(artifact, dict):
        raise PatchBoundaryError("patch artifact must be an object")
    encoded = json.dumps(artifact, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_PATCH_BYTES:
        raise PatchBoundaryError("patch artifact exceeds byte limit")
    _validate_keys(
        artifact,
        {"format", "version", "objective", "rationale", "file", "expected_effect", "risks", "suggested_test_ids"},
        label="patch",
    )
    if artifact["format"] != PATCH_FORMAT or artifact["version"] != PATCH_VERSION:
        raise PatchBoundaryError("unsupported patch format or version")
    for field, limit in (("objective", MAX_OBJECTIVE_CHARS), ("rationale", MAX_RATIONALE_CHARS), ("expected_effect", 1200)):
        if not isinstance(artifact[field], str) or not artifact[field].strip() or len(artifact[field]) > limit:
            raise PatchBoundaryError(f"invalid {field}")
    risks = artifact["risks"]
    if not isinstance(risks, list) or len(risks) > MAX_RISK_ITEMS or any(
        not isinstance(item, str) or len(item) > MAX_RISK_CHARS for item in risks
    ):
        raise PatchBoundaryError("invalid risks")
    test_ids = artifact["suggested_test_ids"]
    permitted_tests = {
        "report_contract",
        "duplicate_hash_fixture",
        "character_budget_fixture",
        "input_immutability_fixture",
    }
    if not isinstance(test_ids, list) or len(test_ids) > 4 or not set(test_ids) <= permitted_tests:
        raise PatchBoundaryError("invalid suggested tests")
    file_value = artifact["file"]
    if not isinstance(file_value, dict):
        raise PatchBoundaryError("file must be an object")
    _validate_keys(file_value, {"path", "base_sha256", "content"}, label="file")
    raw_path = file_value["path"]
    if not isinstance(raw_path, str) or "\\" in raw_path or "\x00" in raw_path:
        raise PatchBoundaryError("path must be normalized UTF-8 POSIX text")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise PatchBoundaryError("absolute or traversing paths are forbidden")
    normalized = relative.as_posix()
    if normalized != EDITABLE_PATH:
        raise PatchBoundaryError("path is outside the exact editable allowlist")
    if normalized.lower().endswith(tuple(DEPENDENCY_NAMES)) or PurePosixPath(normalized).name.lower() in DEPENDENCY_NAMES:
        raise PatchBoundaryError("dependency files are forbidden")
    if any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        raise PatchBoundaryError("protected path is forbidden")
    target = (repo_root / Path(*relative.parts)).resolve()
    try:
        target.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise PatchBoundaryError("resolved path escaped repository") from exc
    if not target.is_file():
        raise PatchBoundaryError("allowlisted parent source is missing")
    base_sha = file_value["base_sha256"]
    if not isinstance(base_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", base_sha):
        raise PatchBoundaryError("invalid base hash")
    if sha256_file(target) != base_sha:
        raise PatchBoundaryError("parent source hash mismatch")
    content = file_value["content"]
    if not isinstance(content, str) or not content or len(content) > MAX_SOURCE_CHARS:
        raise PatchBoundaryError("candidate source is empty or oversized")
    if "\x00" in content:
        raise PatchBoundaryError("binary/NUL source is forbidden")
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        raise PatchBoundaryError("candidate resembles generated secret material")
    try:
        tree = ast.parse(content, filename=normalized)
        compile(tree, normalized, "exec", dont_inherit=True)
    except (SyntaxError, ValueError, TypeError) as exc:
        raise PatchBoundaryError(f"candidate is not valid Python: {exc}") from exc
    if any(isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)) for node in ast.walk(tree)):
        raise PatchBoundaryError("candidate may not add import or scope-authority statements")
    if any(isinstance(node, ast.Name) and node.id.startswith("__") for node in ast.walk(tree)):
        raise PatchBoundaryError("dunder names are forbidden")
    if any(isinstance(node, ast.Attribute) and node.attr.startswith("__") for node in ast.walk(tree)):
        raise PatchBoundaryError("dunder traversal is forbidden")
    function_names = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if function_names != ["render_retrieved_context"]:
        raise PatchBoundaryError("candidate must define exactly render_retrieved_context")
    if any(not isinstance(node, (ast.FunctionDef, ast.Expr)) for node in tree.body):
        raise PatchBoundaryError("candidate may contain only its function and optional module docstring")
    if any(
        isinstance(node, ast.Expr)
        and not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))
        for node in tree.body
    ):
        raise PatchBoundaryError("top-level side effects are forbidden")
    if any(isinstance(node, (ast.While, ast.AsyncFor, ast.Await, ast.Yield, ast.YieldFrom)) for node in ast.walk(tree)):
        raise PatchBoundaryError("unbounded or asynchronous execution constructs are forbidden")
    safe_named_calls = {"str", "len", "set", "ValueError", "min", "max", "sorted"}
    safe_method_calls = {"get", "replace", "append", "add", "join"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in safe_named_calls:
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr in safe_method_calls:
            continue
        raise PatchBoundaryError("candidate call is outside the pure reporting capability allowlist")
    return {
        "passed": True,
        "path": normalized,
        "base_sha256": base_sha,
        "candidate_sha256": sha256_bytes(content.encode("utf-8")),
        "bytes": len(content.encode("utf-8")),
        "defense_in_depth_note": "AST checks narrow syntax but are not a security sandbox; candidate code remains unexecuted.",
    }


def apply_in_isolated_directory(
    artifact: dict[str, Any], *, repo_root: Path, candidate_root: Path
) -> dict[str, Any]:
    validation = validate_patch_artifact(artifact, repo_root=repo_root)
    if candidate_root.exists():
        raise FileExistsError(candidate_root)
    relative = Path(*PurePosixPath(validation["path"]).parts)
    target = candidate_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    source = repo_root / relative
    shutil.copy2(source, target)
    target.write_text(artifact["file"]["content"], encoding="utf-8", newline="\n")
    if sha256_file(target) != validation["candidate_sha256"]:
        raise RuntimeError("isolated candidate hash mismatch after write")
    diff = "".join(
        difflib.unified_diff(
            source.read_text(encoding="utf-8").splitlines(keepends=True),
            target.read_text(encoding="utf-8").splitlines(keepends=True),
            fromfile=f"a/{validation['path']}",
            tofile=f"b/{validation['path']}",
        )
    )
    if not diff:
        raise PatchBoundaryError("candidate makes no source change")
    return {**validation, "candidate_path": str(target), "diff": diff}


def restore_isolated_parent(*, repo_root: Path, candidate_root: Path) -> dict[str, Any]:
    target = candidate_root / Path(*PurePosixPath(EDITABLE_PATH).parts)
    parent = repo_root / Path(*PurePosixPath(EDITABLE_PATH).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(parent, target)
    return {"restored_sha256": sha256_file(target), "expected_sha256": sha256_file(parent)}


@dataclass(frozen=True)
class CommandLimits:
    timeout_seconds: float = 120.0
    max_output_bytes: int = 1_000_000
    max_ram_bytes: int = 2_000_000_000
    max_disk_bytes: int = 200_000_000
    max_processes: int = 8


def run_trusted_command(command: list[str], *, cwd: Path, limits: CommandLimits) -> dict[str, Any]:
    """Run trusted tooling with measured soft resource bounds.

    This is operational containment, not a security sandbox. It is never used
    to execute generated candidate Python.
    """

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=False,
            capture_output=True,
            timeout=limits.timeout_seconds,
            check=False,
        )
        stdout = completed.stdout[: limits.max_output_bytes]
        stderr = completed.stderr[: limits.max_output_bytes]
        output_exceeded = len(completed.stdout) > limits.max_output_bytes or len(completed.stderr) > limits.max_output_bytes
        return {
            "command": command,
            "exit_code": completed.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "output_exceeded": output_exceeded,
            "limits": limits.__dict__,
            "limit_enforcement": {
                "time": "hard subprocess timeout",
                "output": "captured then bounded for trusted tools only",
                "ram": "declared/observed only; no Windows Job Object",
                "disk": "declared/observed only",
                "processes": "declared only; child process count is not isolated",
            },
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": None,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout": (exc.stdout or b"")[: limits.max_output_bytes].decode("utf-8", errors="replace"),
            "stderr": (exc.stderr or b"")[: limits.max_output_bytes].decode("utf-8", errors="replace"),
            "timed_out": True,
            "limits": limits.__dict__,
        }


class SelfCodeModificationCycle:
    def __init__(self, supervisor: Any, *, model_client: Any | None = None) -> None:
        self.supervisor = supervisor
        self.repo_root = supervisor.config.repo_root.resolve()
        self.runtime_root = supervisor.config.runtime_dir / "self_code_cycle_v1"
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.runtime_root / "cycle_state.json"
        self.model_client = model_client or OllamaClient(
            endpoint=supervisor.config.ollama_endpoint,
            model=MODEL_NAME,
            context_limit_tokens=MAX_EFFECTIVE_CONTEXT,
            checkpoint_reserve_tokens=CHECKPOINT_RESERVE_TOKENS,
            timeout_seconds=900,
        )

    def _state(self) -> dict[str, Any] | None:
        return json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else None

    def _save_state(self, value: dict[str, Any]) -> None:
        _atomic_json(self.state_path, value)

    def prepare(self, objective: str) -> dict[str, Any]:
        if not objective.strip() or len(objective) > MAX_OBJECTIVE_CHARS:
            raise ValueError("objective is empty or exceeds bounded objective length")
        previous = self._state()
        if previous and previous.get("action_id") == ACTION_ID:
            if previous.get("status") in {"generation_started", "generation_uncertain"} and not previous.get("proposal"):
                previous["status"] = "generation_uncertain"
                self._save_state(previous)
                return {"ready": False, "requires_reconciliation": True, "state": previous}
            if previous.get("status") in {"proposal_received", "validated", "preserved", "failed_preserved"}:
                return {"ready": False, "duplicate_suppressed": True, "state": previous}
        parent = self.repo_root / Path(*PurePosixPath(EDITABLE_PATH).parts)
        fixture = [
            {"ref": "A", "origin": "evaluation", "kind": "report", "outcome": "supported", "content": "same evidence", "sha256": "1" * 64},
            {"ref": "B", "origin": "runtime_reasoning", "kind": "report", "outcome": "supported", "content": "same evidence", "sha256": "1" * 64},
        ]
        observed = render_retrieved_context(fixture, 2000)
        state = {
            "action_id": ACTION_ID,
            "status": "prepared",
            "objective": objective,
            "parent_path": EDITABLE_PATH,
            "parent_sha256": sha256_file(parent),
            "observed_limitation": {
                "fixture": fixture,
                "rendered": observed,
                "duplicate_hash_occurrences": sum(observed.count(ref) for ref in ("A", "B")),
                "finding": "Both references sharing one content hash are rendered, consuming duplicate context budget.",
            },
            "proposal": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state(state)
        return {"ready": True, "state": state}

    def _model_capability(self) -> dict[str, Any]:
        identity = self.model_client.identity()
        if identity.name != MODEL_NAME or not re.fullmatch(r"[a-f0-9]{64}", identity.digest):
            raise RuntimeError("required gemma4:26b model/digest is unavailable or malformed")
        if hasattr(self.model_client, "context_capabilities"):
            capability = self.model_client.context_capabilities()
        elif isinstance(self.model_client, OllamaClient):
            shown = self.model_client._json_request("/api/show", {"model": MODEL_NAME})
            model_info = shown.get("model_info", {})
            candidates = [
                (str(key), int(value))
                for key, value in model_info.items()
                if str(key).endswith(".context_length") and isinstance(value, (int, float))
            ] if isinstance(model_info, dict) else []
            if not candidates:
                raise RuntimeError("Ollama /api/show did not expose a model context_length")
            key, advertised_value = max(candidates, key=lambda item: item[1])
            capability = {
                "advertised_context_tokens": advertised_value,
                "source": f"ollama_api_show:model_info.{key}",
                "all_context_fields": dict(candidates),
                "parameters": shown.get("parameters", ""),
                "template_sha256": sha256_bytes(str(shown.get("template", "")).encode("utf-8")),
            }
        else:
            capability = {"advertised_context_tokens": MAX_EFFECTIVE_CONTEXT, "source": "test_double"}
        advertised = int(capability.get("advertised_context_tokens") or 0)
        if advertised <= 0:
            raise RuntimeError("Ollama did not expose a positive model context length")
        effective = min(advertised, MAX_EFFECTIVE_CONTEXT)
        if effective <= OUTPUT_RESERVE_TOKENS + CHECKPOINT_RESERVE_TOKENS:
            raise RuntimeError("detected model context cannot preserve required output/checkpoint reserves")
        if isinstance(self.model_client, OllamaClient):
            self.model_client.context_limit_tokens = effective
            self.model_client.budget_manager = TokenBudgetManager(
                context_limit_tokens=effective,
                checkpoint_reserve_tokens=CHECKPOINT_RESERVE_TOKENS,
                estimator=self.model_client.budget_manager.estimator,
            )
        return {
            "name": identity.name,
            "digest": identity.digest,
            "ollama_version": identity.ollama_version,
            "advertised_context_tokens": advertised,
            "effective_context_tokens": effective,
            "context_source": capability.get("source", "ollama_api_show"),
        }

    def _retrieve_context(self, state: dict[str, Any]) -> dict[str, Any]:
        cycle = "SELF_CODE_V1"
        journal = self.supervisor.journal
        objective_ip = journal.add_ip(cycle_id=cycle, label="objective", content=state["objective"], kind="development_objective", metadata={"action_id": ACTION_ID})
        limitation_ip = journal.add_ip(
            cycle_id=cycle,
            label="observed_limitation",
            content=state["observed_limitation"]["finding"],
            kind="observed_failure",
            origin="failure_history",
            outcome="failed",
            failure_condition="retrieved artifacts share a content hash",
            metadata={"fixture": "disclosed_duplicate_hash"},
        )
        boundary_ip = journal.add_ip(
            cycle_id=cycle,
            label="boundary",
            content=(
                "Only development_report.py is editable. Candidate is inert data; no activation, dependency, network, "
                "supervisor, evaluation, history, security-boundary, or Git changes. Generated Python is not executed."
            ),
            kind="constraint",
            outcome="active",
        )
        code_ip = journal.add_ip(
            cycle_id=cycle,
            label="parent_source",
            content=(self.repo_root / Path(*PurePosixPath(EDITABLE_PATH).parts)).read_text(encoding="utf-8"),
            kind="source_snapshot",
            metadata={"path": EDITABLE_PATH, "sha256": state["parent_sha256"]},
        )
        journal.relate(objective_ip["ref"], limitation_ip["ref"], "motivated_by", "Observed duplicate context expenditure motivates the bounded objective")
        journal.relate(objective_ip["ref"], boundary_ip["ref"], "constrained_by", "Development objective is bounded by the trusted editable surface")
        journal.relate(limitation_ip["ref"], code_ip["ref"], "diagnoses", "Observed behavior is produced by this parent source")
        observer = journal.store.set_observer_state(
            goal=state["objective"],
            question="What bounded source change should become a supervised successor candidate?",
            active_constraints=[
                "edit only development_report.py",
                "preserve character budget and deterministic ordering",
                "deduplicate only when a non-empty SHA-256 is actually present",
                "do not execute candidate code",
            ],
            evidence=[state["observed_limitation"]["finding"]],
            open_questions=["Can hash deduplication conserve context without erasing distinct un-hashed records?"],
            recent_refs=[objective_ip["ref"], limitation_ip["ref"], boundary_ip["ref"]],
            current_reasoning_ref=code_ip["ref"],
            session_id="stoe-self-rebuild-v1",
        )
        retrieval = journal.store.navigate(
            observer_state_ref=observer["observer_state_ref"],
            limit=MAX_RETRIEVED_ITEMS,
            max_depth=4,
            include_failures=True,
            include_seed=True,
            per_item_chars=2500,
            total_chars=MAX_RETRIEVED_CHARS,
            run_label="self_code_modification_v1",
        )
        retrieval["trace"] = journal.store.get_retrieval_trace(run_id=retrieval["run_id"], limit=100)
        return {"field_refs": {"objective": objective_ip["ref"], "limitation": limitation_ip["ref"], "boundary": boundary_ip["ref"], "parent_source": code_ip["ref"], "observer": observer["observer_state_ref"]}, "retrieval": retrieval}

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are proposing one bounded source successor for SToE Agent. Return only the JSON object required by the schema. "
            "The artifact is inert data. Modify exactly the allowlisted reporting file. Preserve its public function signature and "
            "deterministic character budget. Deduplicate records only when they carry the same non-empty sha256; records without a "
            "hash remain distinct. Do not add filesystem/environment/network/process access, dependencies, secrets, dunder "
            "access, while loops, async code, or side effects. Candidate content must contain zero import statements: remove the "
            "parent file's imports and use built-in types or omit annotations. Do not claim the candidate was executed or improved."
        )

    @staticmethod
    def _prompt_payload(state: dict[str, Any]) -> dict[str, Any]:
        retrieved = state["field_context"]["retrieval"]
        return {
            "objective": state["objective"],
            "editable_path": EDITABLE_PATH,
            "parent_sha256": state["parent_sha256"],
            "observed_behavior": state["observed_limitation"],
            "retrieved_information_points": retrieved["selected_items"],
            "retrieval_trace": retrieved["trace"],
            "required_contract": {
                "function": "render_retrieved_context(items, max_chars) -> str",
                "deduplication": "first record for each non-empty sha256 wins; missing/empty sha256 never causes deduplication",
                "budget": "returned string length must never exceed max_chars",
                "input": "must not mutate items",
            },
        }

    def _write_attempt_manifest(self, state: dict[str, Any], preserved_root: Path) -> Path:
        payload = self._prompt_payload(state)
        manifest = {
            "action_id": ACTION_ID,
            "model": state.get("model"),
            "system": self._system_prompt(),
            "prompt": json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            "schema": PATCH_SCHEMA,
            "generation_options": {
                "temperature": 0,
                "top_p": 0.9,
                "top_k": 40,
                "seed": 910_241,
                "num_ctx": state.get("model", {}).get("effective_context_tokens"),
                "num_predict": OUTPUT_RESERVE_TOKENS,
                "retry_count": 0,
            },
            "budget": state.get("budget"),
            "field_context": state.get("field_context"),
            "response": None,
            "response_preservation_limitation": (
                "OllamaClient raised while parsing the malformed provider response, before returning its trace."
            ),
        }
        path = preserved_root / "attempt_manifest.json"
        _atomic_json(path, manifest)
        return path

    def run(self, objective: str, *, allow_generation: bool) -> dict[str, Any]:
        prepared = self.prepare(objective)
        if not prepared["ready"]:
            return {"decision": "RECONCILIATION_REQUIRED" if prepared.get("requires_reconciliation") else "SKIP_EXISTING_CYCLE", **prepared}
        state = prepared["state"]
        context = self._retrieve_context(state)
        model = self._model_capability()
        retrieved = context["retrieval"]
        state["field_context"] = context
        prompt_payload = self._prompt_payload(state)
        prompt = json.dumps(prompt_payload, indent=2, ensure_ascii=False, sort_keys=True)
        system = self._system_prompt()
        estimator = TokenEstimator()
        manager = TokenBudgetManager(
            context_limit_tokens=model["effective_context_tokens"],
            checkpoint_reserve_tokens=CHECKPOINT_RESERVE_TOKENS,
            estimator=estimator,
        )
        budget = manager.require_plan(
            system=system,
            prompt=prompt,
            reserved_generation_tokens=OUTPUT_RESERVE_TOKENS,
            categories={
                "task_context": json.dumps({"objective": objective, "contract": prompt_payload["required_contract"]}),
                "retrieved_material": json.dumps(retrieved["selected_items"]),
                "tool_results": json.dumps({"observed": state["observed_limitation"], "trace": retrieved["trace"]}),
            },
        )
        if not allow_generation:
            return {"decision": "READY_NO_GENERATION", "action_id": ACTION_ID, "model": model, "budget": budget, "context": context}
        state.update({"status": "generation_started", "model": model, "budget": budget, "field_context": context})
        self._save_state(state)
        try:
            proposal, trace = self.model_client.generate_json(
                system=system,
                prompt=prompt,
                schema=PATCH_SCHEMA,
                max_output_tokens=OUTPUT_RESERVE_TOKENS,
                seed=910_241,
                context_sections={
                    "task_context": json.dumps({"objective": objective, "contract": prompt_payload["required_contract"]}),
                    "retrieved_material": json.dumps(retrieved["selected_items"]),
                    "tool_results": json.dumps(state["observed_limitation"]),
                },
            )
        except Exception:
            state["status"] = "generation_uncertain"
            self._save_state(state)
            raise
        state.update({"status": "proposal_received", "proposal": proposal, "model_trace": trace})
        self._save_state(state)
        validation = validate_patch_artifact(proposal, repo_root=self.repo_root)
        candidate_workspace = self.runtime_root / "candidate_workspace"
        isolated = apply_in_isolated_directory(proposal, repo_root=self.repo_root, candidate_root=candidate_workspace)
        state.update({"status": "validated", "validation": validation, "isolated": {key: value for key, value in isolated.items() if key != "diff"}})
        self._save_state(state)
        preserved_root = self.repo_root / "agent" / "self_code_candidates" / "self_code_cycle_v1_deduplicate_context"
        preserved_root.mkdir(parents=True, exist_ok=True)
        _atomic_json(preserved_root / "proposal.json", proposal)
        (preserved_root / "candidate_development_report.py").write_text(proposal["file"]["content"], encoding="utf-8", newline="\n")
        (preserved_root / "candidate.patch").write_text(isolated["diff"], encoding="utf-8", newline="\n")
        rollback = {
            "active_source_changed": False,
            "parent_path": EDITABLE_PATH,
            "parent_sha256": state["parent_sha256"],
            "candidate_sha256": validation["candidate_sha256"],
            "rollback": "Discard candidate directory; active release and parent source were never modified.",
            "activation_requires_author_approval": True,
        }
        _atomic_json(preserved_root / "rollback.json", rollback)
        state.update({"status": "preserved", "preserved_root": str(preserved_root), "rollback": rollback})
        self._save_state(state)
        return {
            "decision": "PRESERVED_UNEXECUTED_AWAITING_SAFE_EVALUATION_AND_AUTHOR_APPROVAL",
            "action_id": ACTION_ID,
            "model": model,
            "budget": budget,
            "field_context": context,
            "validation": validation,
            "candidate": {"directory": str(preserved_root), "diff": isolated["diff"]},
            "rollback": rollback,
            "isolation": {
                "achieved": "candidate written only to a separate directory; generated source parsed and compiled but never imported or executed",
                "not_achieved": "filesystem worktree/subprocess isolation is not a security sandbox and this Windows host has no configured low-authority executor",
            },
        }

    def conserve_generation_failure(self, error: str) -> dict[str, Any]:
        """Close an uncertain generation as a failed, non-repeatable attempt."""

        state = self._state()
        if not state or state.get("action_id") != ACTION_ID:
            raise RuntimeError("no matching cycle state to reconcile")
        if state.get("status") == "failed_preserved":
            preserved_root = Path(state["preserved_root"])
            self._write_attempt_manifest(state, preserved_root)
            return {"decision": "SKIP_ALREADY_PRESERVED_FAILURE", "state": state}
        if state.get("status") not in {"generation_started", "generation_uncertain"}:
            raise RuntimeError(f"cycle is not an uncertain generation: {state.get('status')}")
        preserved_root = self.repo_root / "agent" / "self_code_candidates" / "self_code_cycle_v1_deduplicate_context"
        preserved_root.mkdir(parents=True, exist_ok=True)
        attempt_manifest = self._write_attempt_manifest(state, preserved_root)
        failure = {
            "action_id": ACTION_ID,
            "decision": "FAILED_GENERATION_NO_VALID_PATCH",
            "objective": state["objective"],
            "model": state.get("model"),
            "budget": state.get("budget"),
            "error": error,
            "proposal_received": False,
            "candidate_source_created": False,
            "active_source_changed": False,
            "model_calls": 1,
            "retry_permitted_for_action_id": False,
            "raw_response_preserved": False,
            "attempt_manifest": str(attempt_manifest),
            "raw_response_limitation": (
                "The frozen OllamaClient parsed before returning its trace and raised on malformed JSON; "
                "the provider body was therefore not returned to this cycle."
            ),
            "rollback": "No rollback action is necessary because no candidate was applied or activated.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_json(preserved_root / "failed_attempt.json", failure)
        journal = self.supervisor.journal
        cycle_id = "SELF_CODE_V1_FAILED"
        attempt_ip = journal.add_ip(
            cycle_id=cycle_id,
            label="generation_attempt",
            content=(
                "One gemma4:26b generation was attempted under the frozen digest and bounded prompt. "
                "It returned malformed JSON, so no inert patch artifact or candidate source was accepted."
            ),
            kind="candidate_generation",
            origin="failure_history",
            outcome="failed",
            failure_condition="Ollama response was an unterminated JSON string",
            metadata={"action_id": ACTION_ID, "model_calls": 1},
        )
        evaluation_ip = journal.add_ip(
            cycle_id=cycle_id,
            label="failure_evaluation",
            content=error,
            kind="evaluation",
            origin="evaluation",
            outcome="failed",
            metadata={"candidate_source_created": False, "raw_response_preserved": False},
        )
        decision_ip = journal.add_ip(
            cycle_id=cycle_id,
            label="decision",
            content="Preserve the failed attempt; do not retry, activate, merge, or change the parent source.",
            kind="decision",
            outcome="rejected",
            metadata={"activation": False, "retry": False},
        )
        objective_ref = state.get("field_context", {}).get("field_refs", {}).get("objective")
        limitation_ref = state.get("field_context", {}).get("field_refs", {}).get("limitation")
        if objective_ref:
            journal.relate(objective_ref, attempt_ip["ref"], "motivates", "Bounded objective led to the one generation attempt")
        if limitation_ref:
            journal.relate(limitation_ref, attempt_ip["ref"], "motivates", "Observed reporting waste shaped the requested candidate")
        journal.relate(evaluation_ip["ref"], attempt_ip["ref"], "evaluates", "Schema parse failure invalidated the candidate artifact")
        journal.relate(evaluation_ip["ref"], decision_ip["ref"], "supports", "No valid artifact means fail closed without retry")
        field_refs = {
            "attempt": attempt_ip["ref"],
            "evaluation": evaluation_ip["ref"],
            "decision": decision_ip["ref"],
        }
        failure["field_refs"] = field_refs
        _atomic_json(preserved_root / "failed_attempt.json", failure)
        state.update(
            {
                "status": "failed_preserved",
                "failure": failure,
                "preserved_root": str(preserved_root),
                "field_result_refs": field_refs,
            }
        )
        self._save_state(state)
        return {**failure, "artifact_path": str(preserved_root / "failed_attempt.json")}


def record_cycle_in_field(supervisor: Any, result: dict[str, Any], report_path: Path) -> dict[str, Any]:
    cycle_id = "SELF_CODE_V1_RESULT"
    journal = supervisor.journal
    proposal = journal.add_ip(cycle_id=cycle_id, label="proposal", content=f"Model-proposed inert patch {result['validation']['candidate_sha256']}", kind="candidate_patch", outcome="untested", metadata={"artifact_path": str(result["candidate"]["directory"])})
    evaluation = journal.add_ip(cycle_id=cycle_id, label="evaluation", content="Boundary validation passed; candidate execution withheld because no hardened low-authority executor is configured.", kind="evaluation", origin="evaluation", outcome="blocked", metadata={"validation": result["validation"]})
    decision = journal.add_ip(cycle_id=cycle_id, label="decision", content=result["decision"], kind="decision", outcome="pending_approval", metadata={"activation": False})
    report = journal.add_ip(cycle_id=cycle_id, label="report", content=f"Full report: {report_path.as_posix()}", kind="report", outcome="preserved")
    journal.relate(result["field_context"]["field_refs"]["objective"], proposal["ref"], "motivates", "Bounded objective led to this proposal")
    journal.relate(result["field_context"]["field_refs"]["limitation"], proposal["ref"], "motivates", "Observed duplicate-hash behavior shaped the proposal")
    journal.relate(evaluation["ref"], proposal["ref"], "evaluates", "Trusted boundary validation and static checks")
    journal.relate(evaluation["ref"], decision["ref"], "supports", "Execution blocker requires preservation without activation")
    journal.relate(decision["ref"], report["ref"], "conserved_by", "Report conserves succession and rollback evidence")
    return {"proposal": proposal["ref"], "evaluation": evaluation["ref"], "decision": decision["ref"], "report": report["ref"]}
