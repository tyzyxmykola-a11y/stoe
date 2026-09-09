from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .token_budget import TokenBudgetManager, TokenEstimator


ROLES = {"planner", "scout", "summarizer", "coder", "reviewer", "test_analyst", "comparison", "research_synthesis"}
MODES = {"interactive", "idle", "full_power"}
ACTIONS = {"RUN", "RUN_SMALLER_MODEL", "REUSE_LOADED_MODEL", "SERIALIZE", "THROTTLE", "DEFER_LOCAL_WORK", "USE_DETERMINISTIC_TOOL_INSTEAD"}
STATUSES = {"success", "failure", "deferred", "deterministic"}
FORBIDDEN_PARTS = {".git", ".env", "credentials", "secrets", "protected_evals", "research_checkpoints"}
SECRET_RE = re.compile(r"(?i)(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^,\s]{8,}|-----BEGIN .*PRIVATE KEY-----|\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{16,}")
ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9:._-]{5,127}$")
MAX_PACKET_BYTES = 100_000
MAX_RESULT_BYTES = 24_000
DEFAULT_RETURN_TOKENS = 400


class WorkerContractError(ValueError):
    pass


class WorkerUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ResourcePolicy:
    mode: str = "interactive"
    min_available_ram_bytes: int = 10 * 1024**3
    min_free_vram_bytes: int = 2 * 1024**3
    max_heavy_workers: int = 1
    max_small_workers: int = 1
    heavy_model_bytes: int = 10 * 1024**3
    explicit_full_power: bool = False

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise WorkerContractError("invalid resource mode")
        if self.mode == "full_power" and not self.explicit_full_power:
            raise WorkerContractError("full_power requires explicit human selection")
        if min(self.min_available_ram_bytes, self.min_free_vram_bytes, self.max_heavy_workers, self.max_small_workers) < 0:
            raise WorkerContractError("resource policy values must be non-negative")


@dataclass(frozen=True)
class MachineSnapshot:
    captured_at: float
    mode: str
    total_ram_bytes: int | None
    available_ram_bytes: int | None
    process_ram_bytes: int | None
    cpu_percent: float | None
    cpu_count: int | None
    gpu_name: str | None
    gpu_percent: float | None
    total_vram_bytes: int | None
    free_vram_bytes: int | None
    loaded_models: tuple[str, ...]
    active_workers: int
    active_heavy_workers: int
    unavailable_metrics: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskDescriptor:
    role: str
    difficulty: str = "medium"
    code_heavy: bool = False
    estimated_input_tokens: int = 0
    required_output_tokens: int = 400
    requires_json: bool = True
    security_sensitive: bool = False
    independent_review: bool = False
    latency_priority: float = 0.5
    quality_priority: float = 1.0
    deterministic_sufficient: bool = False

    def __post_init__(self) -> None:
        if self.role not in ROLES or self.difficulty not in {"low", "medium", "high"}:
            raise WorkerContractError("invalid task descriptor")
        if min(self.estimated_input_tokens, self.required_output_tokens) < 0:
            raise WorkerContractError("token budgets must be non-negative")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_ref(prefix: str, action_id: str, suffix: str) -> str:
    digest = sha256_bytes(f"{action_id}:{suffix}".encode())[:16]
    return f"{prefix}_{digest}"


def _bounded_strings(value: Any, name: str, *, count: int = 24, chars: int = 800) -> list[str]:
    if not isinstance(value, list) or len(value) > count or any(not isinstance(item, str) or len(item) > chars for item in value):
        raise WorkerContractError(f"{name} is not a bounded string array")
    return value


def _safe_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or any(part.lower() in FORBIDDEN_PARTS for part in path.parts):
        raise WorkerContractError("worker scope contains a forbidden path")
    return normalized


def validate_task_packet(packet: Any) -> dict[str, Any]:
    required = {
        "action_id", "role", "goal", "constraints", "relevant_context", "allowed_paths",
        "expected_output_schema", "resource_limits", "time_limit_seconds", "security_sensitivity", "provenance",
    }
    if not isinstance(packet, dict) or set(packet) != required:
        raise WorkerContractError("task packet fields are missing or unexpected")
    if not isinstance(packet["action_id"], str) or not ACTION_RE.fullmatch(packet["action_id"]):
        raise WorkerContractError("invalid stable action ID")
    if packet["role"] not in ROLES:
        raise WorkerContractError("invalid worker role")
    if not isinstance(packet["goal"], str) or not packet["goal"] or len(packet["goal"]) > 1_500:
        raise WorkerContractError("goal is empty or oversized")
    _bounded_strings(packet["constraints"], "constraints", count=24, chars=500)
    _bounded_strings(packet["relevant_context"], "relevant_context", count=24, chars=2_000)
    if not isinstance(packet["allowed_paths"], list) or not packet["allowed_paths"] or len(packet["allowed_paths"]) > 24:
        raise WorkerContractError("allowed_paths must be a non-empty bounded array")
    packet["allowed_paths"] = [_safe_path(item) for item in packet["allowed_paths"] if isinstance(item, str)]
    if not packet["allowed_paths"]:
        raise WorkerContractError("allowed_paths contains no valid path")
    if not isinstance(packet["expected_output_schema"], dict) or not isinstance(packet["resource_limits"], dict) or not isinstance(packet["provenance"], dict):
        raise WorkerContractError("schema, resource limits, and provenance must be objects")
    if not isinstance(packet["time_limit_seconds"], int) or not 1 <= packet["time_limit_seconds"] <= 900:
        raise WorkerContractError("invalid time limit")
    if packet["security_sensitivity"] not in {"low", "medium", "high"}:
        raise WorkerContractError("invalid security sensitivity")
    encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True).encode()
    if len(encoded) > MAX_PACKET_BYTES:
        raise WorkerContractError("task packet is oversized")
    if SECRET_RE.search(encoded.decode("utf-8")):
        raise WorkerContractError("task packet resembles secret material")
    return packet


RESULT_FIELDS = {
    "action_id", "status", "worker_role", "model", "files_examined", "decision", "evidence", "failures",
    "failure_condition", "files", "test_results", "artifact_paths", "hashes", "unresolved", "confidence", "recommended_next_action",
}


def result_schema(action_id: str, role: str, model: str) -> dict[str, Any]:
    string_array = {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 600}}
    props: dict[str, Any] = {
        "action_id": {"type": "string", "enum": [action_id]},
        "status": {"type": "string", "enum": sorted(STATUSES)},
        "worker_role": {"type": "string", "enum": [role]},
        "model": {"type": "string", "enum": [model]},
        "files_examined": {"type": "integer", "minimum": 0, "maximum": 1000},
        "decision": {"type": "string", "maxLength": 1200},
        "failure_condition": {"type": "string", "maxLength": 800},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "recommended_next_action": {"type": "string", "maxLength": 800},
    }
    for name in ("evidence", "failures", "files", "test_results", "artifact_paths", "hashes", "unresolved"):
        props[name] = string_array
    return {"type": "object", "properties": props, "required": sorted(RESULT_FIELDS), "additionalProperties": False}


def validate_worker_result(value: Any, *, action_id: str, role: str, model: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
        raise WorkerContractError("worker result fields are missing or unexpected")
    if value["action_id"] != action_id or value["worker_role"] != role or value["model"] != model or value["status"] not in STATUSES:
        raise WorkerContractError("worker result identity does not match dispatch")
    if not isinstance(value["files_examined"], int) or not 0 <= value["files_examined"] <= 1000:
        raise WorkerContractError("invalid files_examined")
    for name in ("evidence", "failures", "files", "test_results", "artifact_paths", "hashes", "unresolved"):
        _bounded_strings(value[name], name, count=20, chars=600)
    for name, limit in (("decision", 1200), ("failure_condition", 800), ("recommended_next_action", 800)):
        if not isinstance(value[name], str) or len(value[name]) > limit:
            raise WorkerContractError(f"invalid {name}")
    if not isinstance(value["confidence"], (int, float)) or not 0 <= float(value["confidence"]) <= 1:
        raise WorkerContractError("invalid confidence")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    if len(encoded) > MAX_RESULT_BYTES or SECRET_RE.search(encoded.decode("utf-8")):
        raise WorkerContractError("worker result is oversized or resembles secret material")
    return value


def parse_model_inventory(tags: dict[str, Any], loaded: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    loaded_names = {str(item.get("name")) for item in (loaded or {}).get("models", [])}
    result = []
    for item in tags.get("models", []):
        if not isinstance(item, dict) or not item.get("name") or not item.get("digest"):
            continue
        details = item.get("details") or {}
        result.append({
            "model": str(item["name"]), "digest": str(item["digest"]), "size_bytes": int(item.get("size") or 0),
            "parameter_size": details.get("parameter_size"), "quantization": details.get("quantization_level"),
            "context_capacity": None, "loaded": str(item["name"]) in loaded_names, "observations": [], "role_scores": {},
            "json_reliability": None, "latency_seconds": None, "tokens_per_second": None,
        })
    return sorted(result, key=lambda item: (item["size_bytes"], item["model"]))


def registry_fingerprint(models: list[dict[str, Any]], ollama_version: str, hardware_key: str) -> str:
    identities = [(item["model"], item["digest"]) for item in models]
    return sha256_bytes(json.dumps([ollama_version, hardware_key, identities], sort_keys=True).encode())


def load_registry(path: Path, *, expected_fingerprint: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("fingerprint") != expected_fingerprint:
        return None
    return value


def save_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


class OllamaAPI:
    def __init__(self, endpoint: str = "http://127.0.0.1:11434", timeout_seconds: int = 30) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(self, path: str, payload: dict[str, Any] | None = None, *, timeout: int | None = None) -> bytes:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.endpoint + path, data=data, headers={"Content-Type": "application/json"}, method="GET" if data is None else "POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_seconds) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WorkerUnavailable(f"Ollama unavailable for {path}: {exc}") from exc

    def json(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            value = json.loads(self.request(path, payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkerUnavailable(f"Ollama returned malformed JSON for {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise WorkerUnavailable("Ollama returned a non-object")
        return value

    def discover(self) -> dict[str, Any]:
        version = str(self.json("/api/version").get("version", "unknown"))
        tags = self.json("/api/tags")
        try:
            loaded = self.json("/api/ps")
        except WorkerUnavailable:
            loaded = {"models": []}
        models = parse_model_inventory(tags, loaded)
        for model in models:
            try:
                shown = self.json("/api/show", {"model": model["model"]})
                contexts = [int(value) for key, value in shown.get("model_info", {}).items() if key.endswith(".context_length")]
                model["context_capacity"] = max(contexts) if contexts else None
            except (WorkerUnavailable, TypeError, ValueError):
                model["context_capacity"] = None
        return {"ollama_version": version, "models": models, "loaded_models": sorted(item["model"] for item in models if item["loaded"])}


def _windows_memory() -> tuple[int | None, int | None]:
    if os.name != "nt":
        return None, None
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def _nvidia_snapshot() -> tuple[str | None, float | None, int | None, int | None]:
    try:
        run = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.total,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=False)
        if run.returncode or not run.stdout.strip():
            return None, None, None, None
        name, util, total, free = [part.strip() for part in run.stdout.splitlines()[0].split(",")]
        return name, float(util), int(total) * 1024**2, int(free) * 1024**2
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return None, None, None, None


def capture_machine_snapshot(*, mode: str = "interactive", loaded_models: list[str] | None = None, active_workers: int = 0, active_heavy_workers: int = 0) -> MachineSnapshot:
    if mode not in MODES:
        raise WorkerContractError("invalid resource mode")
    total, available = _windows_memory()
    gpu, gpu_util, total_vram, free_vram = _nvidia_snapshot()
    unavailable = []
    values = {"total_ram": total, "available_ram": available, "gpu": gpu, "gpu_utilization": gpu_util, "total_vram": total_vram, "free_vram": free_vram}
    unavailable.extend(name for name, value in values.items() if value is None)
    return MachineSnapshot(time.time(), mode, total, available, None, None, os.cpu_count(), gpu, gpu_util, total_vram, free_vram, tuple(sorted(loaded_models or [])), active_workers, active_heavy_workers, tuple(unavailable))


def route_model(task: TaskDescriptor, models: list[dict[str, Any]], snapshot: MachineSnapshot) -> dict[str, Any]:
    if task.deterministic_sufficient:
        return {"selected_model": None, "reason": "deterministic tool is sufficient", "fallback_models": [], "capability_evidence": [], "action": "USE_DETERMINISTIC_TOOL_INSTEAD"}
    viable = []
    for model in models:
        context = model.get("context_capacity")
        if context is not None and context < task.estimated_input_tokens + task.required_output_tokens + 512:
            continue
        score = float((model.get("role_scores") or {}).get(task.role, 0.0))
        evidence = list(model.get("observations") or [])
        if not evidence:
            score = max(score, 0.45)  # probationary, not a capability claim
        size = int(model.get("size_bytes") or 0)
        pressure_penalty = 0.25 if snapshot.available_ram_bytes is not None and size and snapshot.available_ram_bytes < size + 8 * 1024**3 else 0.0
        loaded_bonus = 0.12 if model.get("loaded") else 0.0
        quality = task.quality_priority * score
        latency = task.latency_priority * (1 / (1 + max(size, 1) / 1024**3))
        viable.append((quality + latency + loaded_bonus - pressure_penalty, size, model, evidence))
    if not viable:
        raise WorkerUnavailable("no installed model fits the bounded task")
    viable.sort(key=lambda row: (-row[0], row[1], row[2]["model"]))
    selected = viable[0][2]
    fallbacks = [row[2]["model"] for row in viable[1:4]]
    return {
        "selected_model": selected["model"], "selected_digest": selected["digest"],
        "reason": "highest deterministic utility from role evidence, context fit, load state, and resource cost",
        "fallback_models": fallbacks, "capability_evidence": viable[0][3],
        "expected_resource_use": {"model_size_bytes": selected.get("size_bytes"), "loaded": selected.get("loaded")},
        "action": "REUSE_LOADED_MODEL" if selected.get("loaded") else "RUN",
    }


def govern_dispatch(task: TaskDescriptor, selected: dict[str, Any], snapshot: MachineSnapshot, policy: ResourcePolicy) -> dict[str, Any]:
    if task.deterministic_sufficient:
        return {"action": "USE_DETERMINISTIC_TOOL_INSTEAD", "allowed": True, "reason": "deterministic authority is sufficient"}
    if policy.mode != snapshot.mode:
        raise WorkerContractError("resource policy and snapshot modes differ")
    size = int(selected.get("expected_resource_use", {}).get("model_size_bytes") or 0)
    heavy = size >= policy.heavy_model_bytes
    if snapshot.available_ram_bytes is not None and snapshot.available_ram_bytes < policy.min_available_ram_bytes + size:
        return {"action": "RUN_SMALLER_MODEL", "allowed": False, "reason": "operator RAM reserve would be breached"}
    if snapshot.free_vram_bytes is not None and heavy and snapshot.free_vram_bytes < policy.min_free_vram_bytes:
        return {"action": "THROTTLE", "allowed": False, "reason": "operator VRAM reserve would be breached"}
    if heavy and snapshot.active_heavy_workers >= policy.max_heavy_workers:
        return {"action": "SERIALIZE", "allowed": False, "reason": "one-heavy-worker rule"}
    if snapshot.active_workers >= policy.max_small_workers and not heavy:
        return {"action": "SERIALIZE", "allowed": False, "reason": "interactive worker concurrency limit"}
    return {"action": selected.get("action", "RUN"), "allowed": True, "reason": "measured headroom preserves configured operator reserve"}


def compact_result(result: dict[str, Any], *, estimator: TokenEstimator | None = None, max_tokens: int = DEFAULT_RETURN_TOKENS) -> dict[str, Any]:
    estimator = estimator or TokenEstimator()
    compact = {
        "action_id": result["action_id"], "status": result["status"], "role": result["worker_role"], "model": result["model"],
        "decision": result["decision"], "evidence": result["evidence"][:6], "failures": result["failures"][:3],
        "failure_condition": result["failure_condition"], "files": result["files"][:8], "test_results": result["test_results"][:6],
        "artifact_paths": result["artifact_paths"][:4], "hashes": result["hashes"][:6], "unresolved": result["unresolved"][:4],
        "confidence": result["confidence"], "next_action": result["recommended_next_action"],
    }
    while estimator.estimate(json.dumps(compact, ensure_ascii=False, sort_keys=True)) > max_tokens:
        trimmed = False
        for key in ("evidence", "files", "test_results", "hashes", "unresolved", "failures"):
            if compact[key]:
                compact[key].pop()
                trimmed = True
                break
        if not trimmed:
            compact["decision"] = compact["decision"][:300]
            compact["next_action"] = compact["next_action"][:200]
            break
    tokens = estimator.estimate(json.dumps(compact, ensure_ascii=False, sort_keys=True))
    if tokens > max_tokens:
        raise WorkerContractError("result cannot be compacted within return-packet cap")
    compact["return_packet_tokens_estimated"] = tokens
    return compact


class FieldWriter(Protocol):
    def add_ip(self, **kwargs: Any) -> dict[str, Any]: ...
    def add_relation(self, **kwargs: Any) -> dict[str, Any]: ...
    def record_evaluation(self, **kwargs: Any) -> dict[str, Any]: ...


def record_delegation(field: FieldWriter, *, task: dict[str, Any], result: dict[str, Any], artifact: dict[str, Any], session_id: str) -> dict[str, str]:
    action_id = task["action_id"]
    objective_ref = stable_ref("LW", action_id, "objective")
    action_ref = stable_ref("LW", action_id, "action")
    result_ref = stable_ref("LW", action_id, "result")
    artifact_ref = stable_ref("LW", action_id, "artifact")
    objective = field.add_ip(ref=objective_ref, content=task["goal"], kind="DevelopmentObjectiveIP", origin="runtime_reasoning", outcome="active", failure_condition="", session_id=session_id, metadata={"action_id": action_id}, visible=True)
    action = field.add_ip(ref=action_ref, content=f"Bounded local {task['role']} delegation", kind="WorkerActionIP", origin="runtime_reasoning", outcome=result["status"], failure_condition=result["failure_condition"], session_id=session_id, metadata={"model": result["model"]}, visible=True)
    origin = "failure_history" if result["status"] == "failure" else "runtime_reasoning"
    outcome = "failed" if result["status"] == "failure" else "supported"
    worker_result = field.add_ip(ref=result_ref, content=result["decision"], kind="WorkerResultIP", origin=origin, outcome=outcome, failure_condition=result["failure_condition"], session_id=session_id, metadata={"confidence": result["confidence"]}, visible=True)
    artifact_ip = field.add_ip(ref=artifact_ref, content=f"Artifact {artifact['path']} sha256={artifact['sha256']}", kind="ArtifactIP", origin="runtime_reasoning", outcome="supported", failure_condition="", session_id=session_id, metadata=artifact, visible=True)
    field.add_relation(source_ref=objective["ref"], target_ref=action["ref"], relation="depends_on", note="objective delegated to bounded worker action")
    field.add_relation(source_ref=worker_result["ref"], target_ref=action["ref"], relation="generated_by", note="validated worker result generated by action")
    field.add_relation(source_ref=worker_result["ref"], target_ref=artifact_ip["ref"], relation="depends_on", note="compact result refers to full canonical artifact")
    evaluation = field.record_evaluation(evaluates_ref=worker_result["ref"], content="Trusted worker-contract validation completed", outcome=outcome, session_id=session_id, metadata={"action_id": action_id})
    return {"objective": objective["ref"], "action": action["ref"], "result": worker_result["ref"], "artifact": artifact_ip["ref"], "evaluation": evaluation["ref"]}


class LocalWorkerOrchestrator:
    def __init__(self, *, api: OllamaAPI, artifact_root: Path, policy: ResourcePolicy | None = None, estimator: TokenEstimator | None = None) -> None:
        self.api = api
        self.artifact_root = artifact_root.resolve()
        self.policy = policy or ResourcePolicy()
        self.estimator = estimator or TokenEstimator()

    def run(self, packet: dict[str, Any], task: TaskDescriptor, registry: dict[str, Any], snapshot: MachineSnapshot) -> dict[str, Any]:
        packet = validate_task_packet(packet)
        route = route_model(task, registry["models"], snapshot)
        decision = govern_dispatch(task, route, snapshot, self.policy)
        if not decision["allowed"]:
            return {"route": route, "governor": decision, "compact_result": None, "artifact": None}
        if decision["action"] == "USE_DETERMINISTIC_TOOL_INSTEAD":
            return {"route": route, "governor": decision, "compact_result": None, "artifact": None}
        model = str(route["selected_model"])
        run_dir = self.artifact_root / re.sub(r"[^a-zA-Z0-9_.-]", "_", packet["action_id"])
        if run_dir.exists():
            raise WorkerContractError("stable action already has an artifact directory")
        run_dir.mkdir(parents=True)
        prompt = json.dumps({key: packet[key] for key in ("action_id", "role", "goal", "constraints", "relevant_context", "allowed_paths", "resource_limits", "time_limit_seconds", "security_sensitivity", "provenance")}, ensure_ascii=False, sort_keys=True)
        system = "Return exactly one JSON object matching the schema. You have no tools, filesystem, shell, network, memory-write, commit, patch-application, or activation authority. Analyze only supplied text."
        budget = TokenBudgetManager(context_limit_tokens=min(int(next((item.get("context_capacity") or 8192 for item in registry["models"] if item["model"] == model), 8192)), 16384), checkpoint_reserve_tokens=512, estimator=self.estimator).require_plan(system=system, prompt=prompt, reserved_generation_tokens=task.required_output_tokens)
        payload = {"model": model, "system": system, "prompt": prompt, "stream": False, "format": result_schema(packet["action_id"], packet["role"], model), "options": {"temperature": 0, "seed": 4401, "num_ctx": budget["context_limit_tokens"], "num_predict": task.required_output_tokens}}
        started = time.monotonic()
        raw = self.api.request("/api/generate", payload, timeout=packet["time_limit_seconds"])
        duration = time.monotonic() - started
        raw_path = run_dir / "raw_response.json"
        raw_path.write_bytes(raw)
        raw_sha = sha256_bytes(raw)
        try:
            envelope = json.loads(raw.decode("utf-8"))
            parsed = json.loads(str(envelope.get("response", "")))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise WorkerContractError(f"malformed Ollama response: {exc}") from exc
        result = validate_worker_result(parsed, action_id=packet["action_id"], role=packet["role"], model=model)
        result_path = run_dir / "validated_result.json"
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        result_sha = sha256_bytes(result_path.read_bytes())
        result["artifact_paths"].append(str(result_path))
        result["hashes"].extend([f"raw_response_sha256={raw_sha}", f"validated_result_sha256={result_sha}"])
        compact = compact_result(result, estimator=self.estimator)
        metrics = {
            "duration_seconds": round(duration, 3), "prompt_tokens": envelope.get("prompt_eval_count"), "output_tokens": envelope.get("eval_count"),
            "raw_bytes": len(raw), "validated_result_bytes": result_path.stat().st_size,
            "return_packet_tokens_estimated": compact["return_packet_tokens_estimated"], "raw_response_sha256": raw_sha,
            "provider_metrics_available": envelope.get("prompt_eval_count") is not None,
        }
        resume = {"action_id": packet["action_id"], "status": result["status"], "artifact_path": str(result_path), "artifact_sha256": result_sha, "next_action": result["recommended_next_action"], "model": model, "model_digest": route.get("selected_digest")}
        resume_path = run_dir / "resume.json"
        resume_path.write_text(json.dumps(resume, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        if self.estimator.estimate(resume_path.read_text(encoding="utf-8")) >= 1800:
            raise WorkerContractError("fresh-process resume exceeds 1800-token budget")
        return {"route": route, "governor": decision, "compact_result": compact, "artifact": {"path": str(result_path), "sha256": result_sha, "raw_path": str(raw_path), "raw_sha256": raw_sha}, "metrics": metrics, "resume_path": str(resume_path)}


def environment_summary(snapshot: MachineSnapshot) -> dict[str, Any]:
    disk = shutil.disk_usage(Path.cwd().anchor)
    return {"platform": platform.platform(), "python": platform.python_version(), "cpu": platform.processor() or None, "cpu_count": snapshot.cpu_count, "disk_free_bytes": disk.free, "machine_snapshot": asdict(snapshot)}
