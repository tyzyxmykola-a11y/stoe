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
from .function_candidate import (
    function_artifact_schema,
    reconstruct_module,
    sha256_text,
    target_function,
    validate_function_artifact,
)
from .self_code_cycle_v2 import validate_candidate_source
from .report_candidate_ir import render_report_function, report_ir_schema, validate_report_ir


ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "agent" / "runtime" / "local_development_v2"
SESSION = "development:local-development-v2"
TARGET = "agent/src/stoe_agent/development_report.py"
TARGET_FUNCTION = "render_retrieved_context"
DEFAULT_ACTION = "worker:local-development-v2:architecture-plan-v2"


def validate_required_reporting_obligations(parent: str, candidate: str) -> dict:
    if candidate == parent:
        raise RuntimeError("candidate equals parent")
    missing = [
        token
        for token in ("payload_sha256", "canonical_payload_count", "collapsed_duplicate_count", "path")
        if token not in candidate
    ]
    if missing:
        raise RuntimeError("candidate omits required reporting obligations: " + ", ".join(missing))
    return {"changed": True, "static_obligations": "passed"}


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


def run_coder(observer_state_ref: str, planner_result_ref: str, action_id: str, *, correction_ref: str | None = None, ir_mode: bool = False) -> dict:
    api = OllamaAPI(timeout_seconds=30)
    discovery = api.discover()
    _merge_measured_evidence(discovery)
    store = field_store()
    plan = store.get_ip(planner_result_ref)
    retrieval = store.navigate(observer_state_ref=observer_state_ref, include_seed=False, include_failures=True, limit=5, max_depth=4, per_item_chars=320, total_chars=1_400, run_label="local_development_v2_coder")
    parent_path = ROOT / TARGET
    parent = parent_path.read_text(encoding="utf-8")
    parent_sha = _sha256(parent.encode("utf-8"))
    _, parent_function = target_function(parent, TARGET_FUNCTION)
    parent_function_sha = sha256_text(parent_function)
    correction_ip = store.get_ip(correction_ref) if correction_ref else None
    correction = None if correction_ip is None else " | ".join(filter(None, (correction_ip["content"], correction_ip.get("failure_condition", ""))))
    context = [f"ACCEPTED_PLAN {plan['content']}", f"AUTHORIZED_SOURCE {TARGET}\n{parent}"]
    if correction:
        context.append(f"AUTHORITATIVE_CORRECTION {correction}")
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
    wrapper_schema = {
        "type": "object",
        "properties": {
            "control": control_schema(),
            "patch": (
                report_ir_schema(path=TARGET, function=TARGET_FUNCTION, parent_function_sha256=parent_function_sha)
                if ir_mode else
                function_artifact_schema(path=TARGET, function=TARGET_FUNCTION, parent_function_sha256=parent_function_sha)
            ),
        },
        "required": ["control", "patch"],
        "additionalProperties": False,
    }
    prompt_value = {"accepted_plan": plan["content"], "authoritative_correction": correction, "artifact_identity": {"format": "stoe.report_dedup_ir" if ir_mode else "stoe.function_replacement", "path": TARGET, "function": TARGET_FUNCTION, "parent_function_sha256": parent_function_sha}, "requirements": ["Use item payload_sha256 when non-empty; do not recompute identity from text", "Emit each canonical payload content once", "Emit every original ref/relation/direction/provenance connection including duplicates", "Emit exact canonical_payload_count=N and collapsed_duplicate_count=N fields", "Unhashed records remain distinct", "Preserve input order and max_chars bound"]}
    if ir_mode:
        prompt_value["emission_rule"] = "Select the exact bounded reporting IR values. No Python or prose belongs in the patch artifact."
    else:
        prompt_value.update({"replacement_source_rule": "Return the complete Python source of exactly the target function in replacement_source. It must start with def render_retrieved_context and contain no imports, decorators, nested functions, classes, or module code.", "source": parent})
    prompt = json.dumps(prompt_value, ensure_ascii=False, sort_keys=True)
    payload = {"model": route["selected_model"], "think": False, "system": system, "prompt": prompt, "stream": False, "format": wrapper_schema, "options": {"temperature": 0, "top_p": 0.9, "top_k": 40, "seed": 4403, "num_ctx": 8192, "num_predict": 1200}, "keep_alive": "10m"}
    manifest = {"action_id": action_id, "status": "started", "role": "coder", "model": route["selected_model"], "digest": route["selected_digest"], "parent_sha256": parent_sha, "parent_function_sha256": parent_function_sha, "planner_result_ref": planner_result_ref, "correction_ref": correction_ref, "ir_mode": ir_mode, "retrieval_run_id": retrieval["run_id"]}
    _atomic_json(run_dir / "manifest.json", manifest)
    started = time.monotonic()
    try:
        raw = api.request("/api/generate", payload, timeout=420)
    except Exception as exc:
        manifest.update({"status": "uncertain", "failure": type(exc).__name__})
        _atomic_json(run_dir / "manifest.json", manifest)
        raise RuntimeError("coder provider failure; stable action closed uncertain") from exc
    (run_dir / "raw_response.json").write_bytes(raw)
    outer: dict = {}
    try:
        outer = json.loads(raw.decode("utf-8"))
        if outer.get("done") is not True or outer.get("done_reason") in {"length", "error"}:
            raise RuntimeError("coder response incomplete")
        wrapper = json.loads(outer["response"])
        if not isinstance(wrapper, dict) or set(wrapper) != {"control", "patch"}:
            raise RuntimeError("coder wrapper fields invalid")
        control = validate_control(wrapper["control"], known_metadata=(action_id, route["selected_model"], route["selected_digest"], TARGET, parent_sha))
        if ir_mode:
            model_artifact = validate_report_ir(wrapper["patch"], path=TARGET, function=TARGET_FUNCTION, parent_function_sha256=parent_function_sha)
            patch = {"format": "stoe.function_replacement", "path": TARGET, "function": TARGET_FUNCTION, "parent_function_sha256": parent_function_sha, "replacement_source": render_report_function(model_artifact)}
        else:
            model_artifact = validate_function_artifact(wrapper["patch"], expected_path=TARGET, expected_function=TARGET_FUNCTION, parent_source=parent)
            patch = model_artifact
        candidate = reconstruct_module(
            parent,
            patch,
            expected_path=TARGET,
            expected_function=TARGET_FUNCTION,
        )
        validation = validate_candidate_source(parent, candidate)
        validation.update(validate_required_reporting_obligations(parent, candidate))
    except Exception as exc:
        exact_defect = f"{type(exc).__name__}: {exc}"[:160]
        failure_control = {
            "status": "failure",
            "decision": "Candidate artifact rejected by deterministic function-only grammar.",
            "evidence": [f"Preserved raw response sha256={_sha256(raw)}"],
            "risks": [exact_defect],
            "next_action": "Create a new linked corrective action using this exact deterministic defect.",
        }
        failure_envelope = trusted_envelope(failure_control, action_id=action_id, role="coder", model=route["selected_model"], digest=route["selected_digest"], instructions=instructions)
        field_refs = LocalDevelopmentRunner(api=api, artifact_root=RUNTIME / "artifacts", field=store)._record(failure_envelope, goal=plan["content"], session_id=SESSION)
        manifest.update({"status": "failed", "failure": exact_defect, "raw_sha256": _sha256(raw), "field_refs": field_refs, "duration_seconds": round(time.monotonic() - started, 3), "prompt_tokens": outer.get("prompt_eval_count") if isinstance(outer, dict) else None, "output_tokens": outer.get("eval_count") if isinstance(outer, dict) else None})
        _atomic_json(run_dir / "manifest.json", manifest)
        raise
    patch_path = run_dir / ("candidate_ir.json" if ir_mode else "candidate_patch.json")
    _atomic_json(patch_path, model_artifact)
    artifact = {"path": f"local_development_v2/artifacts/{run_dir.name}/candidate_patch.json", "sha256": _sha256(patch_path.read_bytes()), "size_bytes": patch_path.stat().st_size}
    envelope = trusted_envelope(control, action_id=action_id, role="coder", model=route["selected_model"], digest=route["selected_digest"], instructions=instructions, artifact=artifact)
    _atomic_json(run_dir / "validated_envelope.json", envelope)
    _atomic_json(run_dir / "candidate_validation.json", {**validation, "deterministic_renderer": ir_mode})
    (run_dir / "candidate_development_report.py").write_text(candidate, encoding="utf-8", newline="\n")
    manifest.update({"status": "completed", "duration_seconds": round(time.monotonic() - started, 3), "raw_sha256": _sha256(raw), "patch_sha256": artifact["sha256"], "candidate_sha256": validation["candidate_sha256"], "prompt_tokens": outer.get("prompt_eval_count"), "output_tokens": outer.get("eval_count")})
    _atomic_json(run_dir / "manifest.json", manifest)
    refs = LocalDevelopmentRunner(api=api, artifact_root=RUNTIME / "artifacts", field=store)._record(envelope, goal=plan["content"], session_id=SESSION)
    return {"status": "completed", "route": route, "governor": governor, "manifest": manifest, "control": control, "artifact": artifact, "validation": validation, "field_refs": refs, "candidate_path": str(run_dir / "candidate_development_report.py")}


def run_reviewer(observer_state_ref: str, planner_result_ref: str, coder_action_id: str, action_id: str, *, test_evidence: str | None = None) -> dict:
    api = OllamaAPI(timeout_seconds=30)
    discovery = api.discover()
    _merge_measured_evidence(discovery)
    store = field_store()
    plan = store.get_ip(planner_result_ref)
    coder_dir = RUNTIME / "artifacts" / coder_action_id.replace(":", "_")
    coder_manifest = json.loads((coder_dir / "manifest.json").read_text(encoding="utf-8"))
    if coder_manifest.get("status") != "completed":
        raise RuntimeError("review target is not a completed validated coder action")
    candidate_path = coder_dir / "candidate_development_report.py"
    candidate = candidate_path.read_text(encoding="utf-8")
    candidate_sha = _sha256(candidate.encode("utf-8"))
    if candidate_sha != coder_manifest.get("candidate_sha256"):
        raise RuntimeError("review target hash mismatch")
    role = "test_analyst" if test_evidence else "reviewer"
    retrieval = store.navigate(observer_state_ref=observer_state_ref, include_seed=False, include_failures=True, limit=4, max_depth=4, per_item_chars=260, total_chars=900, run_label=f"local_development_v2_{role}")
    context = [f"ACCEPTED_PLAN {plan['content']}", f"VALIDATED_CANDIDATE_SHA256 {candidate_sha}\n{candidate}"]
    context.extend(f"STOE_REF={item['ref']} OUTCOME={item['outcome']} CONTENT={item['content']}" for item in retrieval["selected_items"][:2])
    task = TaskDescriptor(role=role, difficulty="high", code_heavy=True, estimated_input_tokens=TokenEstimator().estimate("\n".join(context)), required_output_tokens=650, requires_json=True, quality_priority=1.0, latency_priority=0.2)
    snapshot = capture_machine_snapshot(mode="interactive", loaded_models=discovery["loaded_models"])
    route = route_model(task, discovery["models"], snapshot)
    if route["selected_model"] == coder_manifest["model"]:
        alternatives = [item for item in discovery["models"] if item.get("model") != coder_manifest["model"]]
        alternative = route_model(task, alternatives, snapshot)
        if alternative.get("action") == "RUN":
            route = alternative
    governor = govern_dispatch(task, route, snapshot, ResourcePolicy(mode="interactive"))
    if not governor["allowed"]:
        return {"status": "deferred", "route": route, "governor": governor}
    run_dir = RUNTIME / "artifacts" / action_id.replace(":", "_")
    if run_dir.exists():
        raise RuntimeError("reviewer stable action already exists and will not be retried")
    run_dir.mkdir(parents=True)
    instructions = load_instructions(role)
    system, _ = model_instructions(role)
    system += "\n\nReturn only Worker Contract v2. You have no tools, filesystem, shell, network, memory-write, Git, tests, patch application, or activation authority."
    if role == "reviewer":
        system += " Reject unless duplicate payload text is emitted once while every distinct connection remains visible and both required counts are accurate."
    prompt = json.dumps({"accepted_plan": plan["content"], "candidate_sha256": candidate_sha, "candidate_source": candidate, "deterministic_validation": "function-only grammar and capability validation passed", "deterministic_test_failure": test_evidence}, ensure_ascii=False, sort_keys=True)
    payload = {"model": route["selected_model"], "think": False, "system": system, "prompt": prompt, "stream": False, "format": control_schema(), "options": {"temperature": 0, "top_p": 0.9, "top_k": 40, "seed": 4404, "num_ctx": 8192, "num_predict": 650}, "keep_alive": "10m"}
    manifest = {"action_id": action_id, "status": "started", "role": role, "model": route["selected_model"], "digest": route["selected_digest"], "planner_result_ref": planner_result_ref, "coder_action_id": coder_action_id, "candidate_sha256": candidate_sha, "retrieval_run_id": retrieval["run_id"]}
    _atomic_json(run_dir / "manifest.json", manifest)
    started = time.monotonic()
    try:
        raw = api.request("/api/generate", payload, timeout=420)
    except Exception as exc:
        manifest.update({"status": "uncertain", "failure": type(exc).__name__})
        _atomic_json(run_dir / "manifest.json", manifest)
        raise RuntimeError("reviewer provider failure; stable action closed uncertain") from exc
    (run_dir / "raw_response.json").write_bytes(raw)
    try:
        outer = json.loads(raw.decode("utf-8"))
        if outer.get("done") is not True or outer.get("done_reason") in {"length", "error"}:
            raise RuntimeError("reviewer response incomplete")
        control = validate_control(json.loads(outer["response"]), known_metadata=(action_id, route["selected_model"], route["selected_digest"], TARGET, candidate_sha))
        envelope = trusted_envelope(control, action_id=action_id, role=role, model=route["selected_model"], digest=route["selected_digest"], instructions=instructions)
    except Exception as exc:
        manifest.update({"status": "failed", "failure": f"{type(exc).__name__}: {exc}", "raw_sha256": _sha256(raw)})
        _atomic_json(run_dir / "manifest.json", manifest)
        raise
    _atomic_json(run_dir / "validated_envelope.json", envelope)
    manifest.update({"status": "completed", "duration_seconds": round(time.monotonic() - started, 3), "raw_sha256": _sha256(raw), "prompt_tokens": outer.get("prompt_eval_count"), "output_tokens": outer.get("eval_count")})
    _atomic_json(run_dir / "manifest.json", manifest)
    refs = LocalDevelopmentRunner(api=api, artifact_root=RUNTIME / "artifacts", field=store)._record(envelope, goal=plan["content"], session_id=SESSION)
    return {"status": "completed", "route": route, "governor": governor, "manifest": manifest, "control": control, "field_refs": refs}


def conserve_failed_coder(action_id: str) -> dict:
    run_dir = RUNTIME / "artifacts" / action_id.replace(":", "_")
    manifest_path = run_dir / "manifest.json"
    raw_path = run_dir / "raw_response.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("action_id") != action_id or manifest.get("role") != "coder" or manifest.get("status") != "failed":
        raise RuntimeError("only an exact closed failed coder action can be conserved")
    raw_sha = _sha256(raw_path.read_bytes())
    if raw_sha != manifest.get("raw_sha256"):
        raise RuntimeError("failed coder raw response hash mismatch")
    exact_defect = str(manifest.get("failure") or "deterministic candidate validation failed")[:160]
    control = {"status": "failure", "decision": "Candidate artifact rejected by deterministic function-only grammar.", "evidence": [f"Preserved raw response sha256={raw_sha}"], "risks": [exact_defect], "next_action": "Create a new linked corrective action using this exact deterministic defect."}
    instructions = load_instructions("coder")
    envelope = trusted_envelope(control, action_id=action_id, role="coder", model=manifest["model"], digest=manifest["digest"], instructions=instructions)
    store = field_store()
    plan = store.get_ip(manifest["planner_result_ref"])
    refs = LocalDevelopmentRunner(api=OllamaAPI(timeout_seconds=30), artifact_root=RUNTIME / "artifacts", field=store)._record(envelope, goal=plan["content"], session_id=SESSION)
    manifest["field_refs"] = refs
    try:
        outer = json.loads(raw_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        outer = {}
    manifest.setdefault("prompt_tokens", outer.get("prompt_eval_count"))
    manifest.setdefault("output_tokens", outer.get("eval_count"))
    _atomic_json(manifest_path, manifest)
    return {"status": "conserved", "field_refs": refs, "raw_sha256": raw_sha, "exact_defect": exact_defect}
