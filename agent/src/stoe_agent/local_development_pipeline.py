from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from .local_development_runner import LocalDevelopmentRunner
from .local_development import control_schema, load_instructions, model_instructions, trusted_envelope, validate_control
from .local_workers import (
    OllamaAPI,
    ResourcePolicy,
    TaskDescriptor,
    capture_machine_snapshot,
    chunk_context_text,
    govern_dispatch,
    route_model,
)
from .token_budget import TokenEstimator
from .self_code_cycle_v2 import patch_schema, reconstruct_candidate, validate_candidate_source, validate_patch_envelope


ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "agent" / "runtime" / "local_development_v2"
SESSION = "development:local-development-v2"
TARGET = "agent/src/stoe_agent/development_report.py"
DEFAULT_ACTION = "worker:local-development-v2:architecture-plan-v2"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def field_store():
    core = ROOT / "plugins" / "stoe-memory" / "core.py"
    spec = importlib.util.spec_from_file_location("stoe_local_development_v2_memory", core)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the repository SToE Memory implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    store = module.FieldStore()
    store.initialize()
    return store


def _merge_measured_evidence(discovery: dict) -> None:
    path = ROOT / "agent" / "runtime" / "local_workers_v1" / "capability_registry.json"
    if not path.is_file():
        return
    prior = json.loads(path.read_text(encoding="utf-8"))
    evidence = {(item.get("model"), item.get("digest")): item for item in prior.get("models", [])}
    for model in discovery["models"]:
        matched = evidence.get((model["model"], model["digest"]))
        if matched:
            model["role_scores"] = dict(matched.get("role_scores") or {})
            model["observations"] = list(matched.get("observations") or [])
            model["json_reliability"] = matched.get("json_reliability")


def record_routing_evidence(*, model: str, digest: str, role: str, score: float, observation: str) -> None:
    path = ROOT / "agent" / "runtime" / "local_workers_v1" / "capability_registry.json"
    if not path.is_file() or not 0.0 <= score <= 1.0:
        raise RuntimeError("measured routing registry is unavailable or score is invalid")
    value = json.loads(path.read_text(encoding="utf-8"))
    matched = next((item for item in value.get("models", []) if item.get("model") == model and item.get("digest") == digest), None)
    if matched is None:
        raise RuntimeError("exact model identity is absent from measured routing registry")
    observations = list(matched.get("observations") or [])
    if observation not in observations:
        observations.append(observation)
    matched["observations"] = observations
    matched.setdefault("role_scores", {})[role] = score
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def run_planner(observer_state_ref: str, action_id: str = DEFAULT_ACTION, *, difficulty: str = "medium") -> dict:
    api = OllamaAPI(timeout_seconds=30)
    discovery = api.discover()
    _merge_measured_evidence(discovery)
    store = field_store()
    retrieval = store.navigate(observer_state_ref=observer_state_ref, include_seed=False, include_failures=True, limit=6, max_depth=4, per_item_chars=360, total_chars=1_800, run_label="local_development_v2_planner")
    source = (ROOT / TARGET).read_text(encoding="utf-8")
    context = [
        f"STOE_REF={item['ref']} ORIGIN={item['origin']} OUTCOME={item['outcome']} CONTENT={item['content']}"
        for item in retrieval["selected_items"]
    ]
    context.extend(chunk_context_text(f"AUTHORIZED_SOURCE {TARGET}", source, max_chars=950))
    task = TaskDescriptor(role="planner", difficulty=difficulty, estimated_input_tokens=TokenEstimator().estimate("\n".join(context)), required_output_tokens=1_200, requires_json=True, quality_priority=1.0, latency_priority=0.35)
    snapshot = capture_machine_snapshot(mode="interactive", loaded_models=discovery["loaded_models"])
    route = route_model(task, discovery["models"], snapshot)
    governor = govern_dispatch(task, route, snapshot, ResourcePolicy(mode="interactive"))
    if not governor["allowed"]:
        return {"status": "deferred", "route": route, "governor": governor, "retrieval_run_id": retrieval["run_id"]}
    result = LocalDevelopmentRunner(api=api, artifact_root=RUNTIME / "artifacts", field=store).run_planner(
        action_id=action_id,
        model=route["selected_model"],
        expected_digest=route["selected_digest"],
        goal="Plan the smallest change to development_report.py so identical retrieved artifact content is emitted once by canonical SHA-256 while every distinct SToE connection remains visible and canonical payload count plus collapsed duplicate count are reported.",
        constraints=[f"Only {TARGET} is editable", "Plan only; do not emit code or a patch", "Explicitly address canonical SHA-256 deduplication, preservation of every distinct connection, canonical payload count, and collapsed duplicate count", "Records without a non-empty SHA-256 remain distinct", "Preserve input order and do not mutate inputs", "No authority, dependency, security, evaluator, Git, or activation changes"],
        context_items=context,
        session_id=SESSION,
    )
    result.update({"route": route, "governor": governor, "retrieval_run_id": retrieval["run_id"]})
    if result.get("field_refs"):
        result["next_observer"] = store.set_observer_state(
            goal="Continue Local Development v2 through bounded coder and independent reviewer stages.",
            question="Can the accepted planner result produce a valid inert candidate for development_report.py?",
            active_constraints=["Local Ollama only", "One bounded coder call", "Separate inert candidate artifact", "Deterministic tests are authoritative"],
            evidence=[result["envelope"]["control"]["decision"]],
            open_questions=["Will the candidate pass focused and complete deterministic tests?"],
            recent_refs=[result["field_refs"]["result"], result["field_refs"]["evaluation"]],
            current_reasoning_ref=result["field_refs"]["result"],
            session_id=SESSION,
        )
    return result


def run_coder(observer_state_ref: str, planner_result_ref: str, action_id: str) -> dict:
    api = OllamaAPI(timeout_seconds=30)
    discovery = api.discover()
    _merge_measured_evidence(discovery)
    store = field_store()
    plan = store.get_ip(planner_result_ref)
    retrieval = store.navigate(observer_state_ref=observer_state_ref, include_seed=False, include_failures=True, limit=5, max_depth=4, per_item_chars=320, total_chars=1_400, run_label="local_development_v2_coder")
    parent_path = ROOT / TARGET
    parent = parent_path.read_text(encoding="utf-8")
    parent_sha = _sha256(parent.encode("utf-8"))
    context = [f"ACCEPTED_PLAN {plan['content']}", f"AUTHORIZED_SOURCE {TARGET}\n{parent}"]
    context.extend(f"STOE_REF={item['ref']} OUTCOME={item['outcome']} CONTENT={item['content']}" for item in retrieval["selected_items"][:3])
    task = TaskDescriptor(role="coder", difficulty="high", code_heavy=True, estimated_input_tokens=TokenEstimator().estimate("\n".join(context)), required_output_tokens=1_200, requires_json=True, quality_priority=1.0, latency_priority=0.2)
    snapshot = capture_machine_snapshot(mode="interactive", loaded_models=discovery["loaded_models"])
    route = route_model(task, discovery["models"], snapshot)
    governor = govern_dispatch(task, route, snapshot, ResourcePolicy(mode="interactive"))
    if not governor["allowed"]:
        return {"status": "deferred", "route": route, "governor": governor}
    run_dir = RUNTIME / "artifacts" / action_id.replace(":", "_")
    if run_dir.exists():
        raise RuntimeError("coder stable action already exists and will not be retried")
    run_dir.mkdir(parents=True)
    instructions = load_instructions("coder")
    system, _ = model_instructions("coder")
    system += "\n\nReturn one wrapper object with control and patch. You have no tools, filesystem, shell, network, memory-write, Git, tests, patch application, or activation authority."
    wrapper_schema = {"type": "object", "properties": {"control": control_schema(), "patch": patch_schema(parent_sha)}, "required": ["control", "patch"], "additionalProperties": False}
    prompt = json.dumps({"accepted_plan": plan["content"], "requirements": ["Use item payload_sha256 when non-empty; do not recompute identity from text", "Emit each canonical payload content once", "Emit every original ref/relation/direction/provenance connection", "Report canonical_payload_count and collapsed_duplicate_count", "Unhashed records remain distinct", "Preserve input order and max_chars bound"], "source": parent}, ensure_ascii=False, sort_keys=True)
    payload = {"model": route["selected_model"], "think": False, "system": system, "prompt": prompt, "stream": False, "format": wrapper_schema, "options": {"temperature": 0, "top_p": 0.9, "top_k": 40, "seed": 4403, "num_ctx": 8192, "num_predict": 1200}, "keep_alive": "10m"}
    manifest = {"action_id": action_id, "status": "started", "role": "coder", "model": route["selected_model"], "digest": route["selected_digest"], "parent_sha256": parent_sha, "planner_result_ref": planner_result_ref, "retrieval_run_id": retrieval["run_id"]}
    _atomic_json(run_dir / "manifest.json", manifest)
    started = time.monotonic()
    try:
        raw = api.request("/api/generate", payload, timeout=420)
    except Exception as exc:
        manifest.update({"status": "uncertain", "failure": type(exc).__name__})
        _atomic_json(run_dir / "manifest.json", manifest)
        raise RuntimeError("coder provider failure; stable action closed uncertain") from exc
    (run_dir / "raw_response.json").write_bytes(raw)
    try:
        outer = json.loads(raw.decode("utf-8"))
        if outer.get("done") is not True or outer.get("done_reason") in {"length", "error"}:
            raise RuntimeError("coder response incomplete")
        wrapper = json.loads(outer["response"])
        if not isinstance(wrapper, dict) or set(wrapper) != {"control", "patch"}:
            raise RuntimeError("coder wrapper fields invalid")
        control = validate_control(wrapper["control"], known_metadata=(action_id, route["selected_model"], route["selected_digest"], TARGET, parent_sha))
        patch = validate_patch_envelope(wrapper["patch"], expected_parent=parent_sha)
        candidate = reconstruct_candidate(parent, patch)
        validation = validate_candidate_source(parent, candidate)
    except Exception as exc:
        manifest.update({"status": "failed", "failure": f"{type(exc).__name__}: {exc}", "raw_sha256": _sha256(raw)})
        _atomic_json(run_dir / "manifest.json", manifest)
        raise
    patch_path = run_dir / "candidate_patch.json"
    _atomic_json(patch_path, patch)
    artifact = {"path": f"local_development_v2/artifacts/{run_dir.name}/candidate_patch.json", "sha256": _sha256(patch_path.read_bytes()), "size_bytes": patch_path.stat().st_size}
    envelope = trusted_envelope(control, action_id=action_id, role="coder", model=route["selected_model"], digest=route["selected_digest"], instructions=instructions, artifact=artifact)
    _atomic_json(run_dir / "validated_envelope.json", envelope)
    _atomic_json(run_dir / "candidate_validation.json", validation)
    (run_dir / "candidate_development_report.py").write_text(candidate, encoding="utf-8", newline="\n")
    manifest.update({"status": "completed", "duration_seconds": round(time.monotonic() - started, 3), "raw_sha256": _sha256(raw), "patch_sha256": artifact["sha256"], "candidate_sha256": validation["candidate_sha256"], "prompt_tokens": outer.get("prompt_eval_count"), "output_tokens": outer.get("eval_count")})
    _atomic_json(run_dir / "manifest.json", manifest)
    refs = LocalDevelopmentRunner(api=api, artifact_root=RUNTIME / "artifacts", field=store)._record(envelope, goal=plan["content"], session_id=SESSION)
    return {"status": "completed", "route": route, "governor": governor, "manifest": manifest, "control": control, "artifact": artifact, "validation": validation, "field_refs": refs, "candidate_path": str(run_dir / "candidate_development_report.py")}
