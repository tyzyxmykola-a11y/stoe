from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_agent.local_development import LocalDevelopmentError, control_schema, load_instructions, model_instructions, record_envelope, trusted_envelope, validate_control  # noqa: E402
from stoe_agent.local_development_pipeline import _merge_measured_evidence, field_store  # noqa: E402
from stoe_agent.local_workers import OllamaAPI, ResourcePolicy, TaskDescriptor, capture_machine_snapshot, govern_dispatch, route_model  # noqa: E402
from stoe_agent.self_code_cycle_v2 import strict_json_loads  # noqa: E402
from stoe_agent.token_budget import TokenEstimator  # noqa: E402
from stoe_hermes.development_governor import (  # noqa: E402
    ALLOWED_CAPABILITIES, ESCALATION_REASONS, REQUIRED_FORBIDDEN,
    TASK_SCOPE_FORMAT, task_scope_schema, validate_task_scope,
)


RUNTIME = ROOT / "agent" / "runtime" / "hermes_governor_v1"
SESSION = "development:hermes-governor-v1"
TARGET = "stoe-hermes/README.md"
OBJECTIVE = "Add a concise operational section documenting SToE Hermes Development Governor v1, TaskScope enforcement, model limits, trusted verification, and SToE Memory continuity without overstating autonomy."
TASK_ID = "hermes:governor-v1:readme:0001"
PARENT_REFS = ["IP_hermesgovernornext01", "IP_ldv2qualified02"]
HEADING = "SToE Hermes Development Governor v1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def action_dir(action_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9:._-]{8,128}", action_id):
        raise RuntimeError("invalid stable action ID")
    return RUNTIME / "actions" / action_id.replace(":", "_")


def model_call(*, action_id: str, role: str, prompt_value: dict, schema: dict, difficulty: str = "medium", output_tokens: int = 900) -> tuple[dict, dict, dict]:
    run_dir = action_dir(action_id)
    manifest_path = run_dir / "manifest.json"
    raw_path = run_dir / "raw_response.json"
    parsed_path = run_dir / "parsed.json"
    prompt = json.dumps(prompt_value, ensure_ascii=False, sort_keys=True)
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("action_id") != action_id or manifest.get("role") != role:
            raise RuntimeError("stable action identity mismatch")
        if manifest.get("status") == "completed":
            return json.loads(parsed_path.read_text(encoding="utf-8")), manifest, {"recovered": True}
        if manifest.get("status") in {"failed", "uncertain", "deferred"}:
            raise RuntimeError("closed stable action cannot be retried")
        if manifest.get("status") != "started" or not raw_path.is_file():
            manifest.update({"status": "uncertain", "failure": "interrupted before raw preservation"})
            atomic_json(manifest_path, manifest)
            raise RuntimeError("interrupted action closed uncertain")
        raw = raw_path.read_bytes()
        route = {"selected_model": manifest["model"], "selected_digest": manifest["digest"]}
        governor = {"allowed": True, "action": "RECOVER_RAW", "reason": "preserved raw response"}
    else:
        api = OllamaAPI(timeout_seconds=30)
        discovery = api.discover()
        _merge_measured_evidence(discovery)
        routing_role = "planner" if role == "governor" else role
        task = TaskDescriptor(role=routing_role, difficulty=difficulty, code_heavy=role == "coder", estimated_input_tokens=TokenEstimator().estimate(prompt), required_output_tokens=output_tokens, requires_json=True, quality_priority=1.0, latency_priority=0.25)
        snapshot = capture_machine_snapshot(mode="interactive", loaded_models=discovery["loaded_models"])
        route = route_model(task, discovery["models"], snapshot)
        governor = govern_dispatch(task, route, snapshot, ResourcePolicy(mode="interactive"))
        if not governor["allowed"]:
            ranked_names = list(route.get("fallback_models", []))
            ranked_names.extend(model["model"] for model in discovery["models"] if model["model"] != route["selected_model"] and model["model"] not in ranked_names)
            inventory = {model["model"]: model for model in discovery["models"]}
            for name in ranked_names:
                model = inventory[name]
                alternate = {
                    "selected_model": name,
                    "selected_digest": model["digest"],
                    "reason": "ranked fallback selected because the preferred model breached the interactive resource reserve",
                    "fallback_models": [],
                    "capability_evidence": list(model.get("observations") or []),
                    "expected_resource_use": {"model_size_bytes": model.get("size_bytes"), "loaded": model.get("loaded")},
                    "action": "REUSE_LOADED_MODEL" if model.get("loaded") else "RUN_SMALLER_MODEL",
                }
                alternate_governor = govern_dispatch(task, alternate, snapshot, ResourcePolicy(mode="interactive"))
                if alternate_governor["allowed"]:
                    route, governor = alternate, alternate_governor
                    break
        if not governor["allowed"]:
            run_dir.mkdir(parents=True, exist_ok=False)
            deferred = {"status": "deferred", "action_id": action_id, "role": role, "route": route, "governor": governor}
            atomic_json(manifest_path, deferred)
            return {"status": "deferred"}, deferred, {"route": route, "governor": governor}
        run_dir.mkdir(parents=True, exist_ok=False)
        system, _ = model_instructions(role)
        system += "\n\nReturn only the schema-conforming inert object. You have no tools, filesystem, network, process, Git, SToE-write, apply, or activation authority."
        payload = {"model": route["selected_model"], "think": False, "system": system, "prompt": prompt, "stream": False, "format": schema, "options": {"temperature": 0, "top_p": 0.9, "top_k": 40, "seed": 7301, "num_ctx": 8192, "num_predict": output_tokens}, "keep_alive": "5m"}
        manifest = {"action_id": action_id, "role": role, "status": "started", "model": route["selected_model"], "digest": route["selected_digest"], "prompt_sha256": sha256(prompt.encode()), "prompt_tokens_estimated": task.estimated_input_tokens}
        atomic_json(manifest_path, manifest)
        started = time.monotonic()
        try:
            raw = api.request("/api/generate", payload, timeout=420)
        except Exception as exc:
            manifest.update({"status": "uncertain", "failure": type(exc).__name__})
            atomic_json(manifest_path, manifest)
            raise
        raw_path.write_bytes(raw)
        manifest["duration_seconds"] = round(time.monotonic() - started, 3)
    try:
        outer = strict_json_loads(raw.decode("utf-8"))
        if outer.get("done") is not True or outer.get("done_reason") in {"length", "error"}:
            raise RuntimeError("incomplete local model response")
        parsed = strict_json_loads(outer["response"])
    except Exception as exc:
        manifest.update({"status": "failed", "failure": f"{type(exc).__name__}: {exc}", "raw_sha256": sha256(raw)})
        atomic_json(manifest_path, manifest)
        raise
    atomic_json(parsed_path, parsed)
    manifest.update({"status": "completed", "raw_sha256": sha256(raw), "prompt_tokens": outer.get("prompt_eval_count"), "output_tokens": outer.get("eval_count")})
    atomic_json(manifest_path, manifest)
    return parsed, manifest, {"route": route, "governor": governor}


def record_control(*, action_id: str, role: str, manifest: dict, control: dict, goal: str, artifact: dict | None = None) -> dict:
    instructions = load_instructions(role)
    envelope = trusted_envelope(control, action_id=action_id, role=role, model=manifest["model"], digest=manifest["digest"], instructions=instructions, artifact=artifact)
    return record_envelope(field_store(), envelope, goal=goal, session_id=SESSION)


def exact_scope() -> dict:
    return {"format": TASK_SCOPE_FORMAT, "task_id": TASK_ID, "parent_refs": PARENT_REFS, "role": "coder", "objective": OBJECTIVE, "read_scope": [TARGET], "write_scope": [TARGET], "allowed_capabilities": sorted(ALLOWED_CAPABILITIES), "forbidden_capabilities": sorted(REQUIRED_FORBIDDEN), "invariants": ["Models cannot apply or use Git", "Existing evidence and trust boundaries remain unchanged", "Documentation must not claim unrestricted autonomy"], "success_criteria": ["One Governor v1 section is appended", "TaskScope and deterministic authority are explained", "SToE Memory continuity and model limits are explicit"], "resource_budget": {"input_tokens": 3000, "output_tokens": 900, "timeout_seconds": 300}, "recovery_budget": {"planner": 1, "coder": 2, "reviewer": 1}, "escalation_boundary": sorted(ESCALATION_REASONS)}


def validate_doc_patch(value: dict, *, parent_sha: str) -> dict:
    fields = {"format", "path", "parent_sha256", "heading", "body"}
    if not isinstance(value, dict) or set(value) != fields or value["format"] != "stoe.documentation_append.v1" or value["path"] != TARGET or value["parent_sha256"] != parent_sha or value["heading"] != HEADING:
        raise RuntimeError("documentation artifact identity mismatch")
    body = value["body"]
    has_heading = any(line.lstrip().startswith("#") for line in body.splitlines())
    if not isinstance(body, str) or not 200 <= len(body.encode("utf-8")) <= 1800 or "\x00" in body or has_heading:
        raise RuntimeError("documentation body is invalid or unbounded")
    folded = body.casefold()
    required = ("taskscope", "deterministic", "model", "stoe memory", "trusted")
    if any(term not in folded for term in required):
        raise RuntimeError("documentation omits required bounded-governance concepts")
    if any(term in folded for term in ("unrestricted self-improvement", "agi achieved", "bypass", "force-push")):
        raise RuntimeError("documentation contains unsafe or overstated claim")
    return value


def main() -> int:
    store = field_store()
    scope_expected = exact_scope()
    scope_wrapper = {"type": "object", "properties": {"control": control_schema(), "task_scope": task_scope_schema(task_id=TASK_ID, objective=OBJECTIVE, read_scope=[TARGET], write_scope=[TARGET], parent_refs=PARENT_REFS, role="coder")}, "required": ["control", "task_scope"], "additionalProperties": False}
    governed, governed_manifest, governed_meta = model_call(action_id="worker:hermes-governor-v1:scope-1", role="governor", prompt_value={"unresolved_objectives": [OBJECTIVE], "required_scope": scope_expected}, schema=scope_wrapper, difficulty="high", output_tokens=1000)
    if governed.get("status") == "deferred":
        print(json.dumps({"status": "deferred", "stage": "governor", **governed_meta}, indent=2)); return 2
    control = validate_control(governed["control"])
    scope = validate_task_scope(governed["task_scope"], exact=scope_expected)
    scope_path = action_dir(governed_manifest["action_id"]) / "task_scope.json"
    atomic_json(scope_path, scope)
    try:
        governor_refs = record_control(action_id=governed_manifest["action_id"], role="governor", manifest=governed_manifest, control=control, goal=OBJECTIVE)
    except LocalDevelopmentError as exc:
        failure_ref = "IP_hermes_governor_control_failure01"
        try:
            store.get_ip(failure_ref)
        except KeyError:
            store.add_ip(ref=failure_ref, content=f"Closed governor control failed deterministic validation: {exc}", kind="FailureIP", origin="failure_history", outcome="failed", session_id=SESSION, metadata={"action_id": governed_manifest["action_id"], "raw_sha256": governed_manifest["raw_sha256"]})
        governed, governed_manifest, _ = model_call(action_id="worker:hermes-governor-v1:scope-2", role="governor", prompt_value={"parent_action": "worker:hermes-governor-v1:scope-1", "exact_defect": str(exc), "required_scope": scope_expected, "correction": "Return the exact required TaskScope. In control fields do not repeat task ID, role, model, hashes, paths, budgets, or supervisor metadata."}, schema=scope_wrapper, difficulty="high", output_tokens=1000)
        control = validate_control(governed["control"])
        scope = validate_task_scope(governed["task_scope"], exact=scope_expected)
        try:
            governor_refs = record_control(action_id=governed_manifest["action_id"], role="governor", manifest=governed_manifest, control=control, goal=OBJECTIVE)
            store.add_relation(source_ref=governor_refs["result"], target_ref=failure_ref, relation="corrects", note="New linked governor action corrects the exact control-contract defect")
        except LocalDevelopmentError as repair_exc:
            repair_failure_ref = "IP_hermes_governor_control_failure02"
            try:
                store.get_ip(repair_failure_ref)
            except KeyError:
                store.add_ip(ref=repair_failure_ref, content=f"Corrective governor control remained invalid: {repair_exc}; exact TaskScope artifact validated independently.", kind="FailureIP", origin="failure_history", outcome="failed", session_id=SESSION, metadata={"action_id": governed_manifest["action_id"], "raw_sha256": governed_manifest["raw_sha256"]})
                store.add_relation(source_ref=repair_failure_ref, target_ref=failure_ref, relation="follows", note="Bounded corrective control attempt also repeated supervisor metadata")
            governor_refs = {"result": repair_failure_ref}
    scope_ref = "IP_hermes_taskscope_" + sha256(json.dumps(scope, sort_keys=True).encode())[:12]
    try:
        store.get_ip(scope_ref)
    except KeyError:
        store.add_ip(ref=scope_ref, content=f"TaskScope {TASK_ID} sha256={sha256(scope_path.read_bytes())}", kind="TaskScopeIP", origin="runtime_reasoning", outcome="active", session_id=SESSION, metadata={"path": str(scope_path.relative_to(ROOT)).replace('\\', '/'), "sha256": sha256(scope_path.read_bytes()), "task_id": TASK_ID})
        store.add_relation(source_ref=scope_ref, target_ref=governor_refs["result"], relation="generated_by", note="Hermes governor produced this validated TaskScope")
        for ref in PARENT_REFS:
            store.add_relation(source_ref=scope_ref, target_ref=ref, relation="depends_on", note="TaskScope descends from conserved objective/qualification")
    planner_schema = control_schema()
    planned, planner_manifest, planner_meta = model_call(action_id="worker:hermes-governor-v1:planner-1", role="planner", prompt_value={"task_scope": scope, "source_excerpt": (ROOT / TARGET).read_text(encoding="utf-8")[-2200:], "instruction": "Plan only the smallest appended section; no implementation."}, schema=planner_schema, difficulty="medium", output_tokens=600)
    if planned.get("status") == "deferred": print(json.dumps({"status": "deferred", "stage": "planner", **planner_meta}, indent=2)); return 2
    planned = validate_control(planned)
    planner_refs = record_control(action_id=planner_manifest["action_id"], role="planner", manifest=planner_manifest, control=planned, goal=OBJECTIVE)
    parent = (ROOT / TARGET).read_text(encoding="utf-8")
    parent_sha = sha256(parent.encode())
    patch_schema = {"type": "object", "properties": {"control": control_schema(), "patch": {"type": "object", "properties": {"format": {"type": "string", "enum": ["stoe.documentation_append.v1"]}, "path": {"type": "string", "enum": [TARGET]}, "parent_sha256": {"type": "string", "enum": [parent_sha]}, "heading": {"type": "string", "enum": [HEADING]}, "body": {"type": "string", "minLength": 200, "maxLength": 1800}}, "required": ["format", "path", "parent_sha256", "heading", "body"], "additionalProperties": False}}, "required": ["control", "patch"], "additionalProperties": False}
    coded, coder_manifest, coder_meta = model_call(action_id="worker:hermes-governor-v1:coder-1", role="coder", prompt_value={"task_scope": scope, "accepted_plan": planned, "existing_readme_tail": parent[-2400:], "artifact_rule": "Return one inert append section; do not repeat the heading inside body."}, schema=patch_schema, difficulty="high", output_tokens=1100)
    if coded.get("status") == "deferred": print(json.dumps({"status": "deferred", "stage": "coder", **coder_meta}, indent=2)); return 2
    coded_control = validate_control(coded["control"])
    try:
        patch = validate_doc_patch(coded["patch"], parent_sha=parent_sha)
    except RuntimeError as exc:
        coder_failure_ref = "IP_hermes_governor_coder_failure01"
        try:
            store.get_ip(coder_failure_ref)
        except KeyError:
            store.add_ip(ref=coder_failure_ref, content=f"Closed coder artifact failed deterministic validation: {exc}; body also ended with an incomplete claim.", kind="FailureIP", origin="failure_history", outcome="failed", session_id=SESSION, metadata={"action_id": coder_manifest["action_id"], "raw_sha256": coder_manifest["raw_sha256"]})
            store.add_relation(source_ref=coder_failure_ref, target_ref=planner_refs["result"], relation="follows", note="First coder attempt followed the accepted local plan")
        coded, coder_manifest, _ = model_call(action_id="worker:hermes-governor-v1:coder-2", role="coder", prompt_value={"parent_action": "worker:hermes-governor-v1:coder-1", "exact_defects": [str(exc), "Body ended with an incomplete numerical claim"], "task_scope": scope, "accepted_plan": planned, "artifact_requirements": {"format": "stoe.documentation_append.v1", "path": TARGET, "parent_sha256": parent_sha, "heading": HEADING, "body_chars": "350..900", "required_literal_terms": ["TaskScope", "deterministic", "model", "SToE Memory", "trusted"], "forbidden": ["artifact paths in control", "numeric test claims", "unrestricted autonomy", "incomplete sentence"]}}, schema=patch_schema, difficulty="high", output_tokens=850)
        coded_control = validate_control(coded["control"])
        try:
            patch = validate_doc_patch(coded["patch"], parent_sha=parent_sha)
        except RuntimeError as repair_exc:
            second_failure_ref = "IP_hermes_governor_coder_failure02"
            try:
                store.get_ip(second_failure_ref)
            except KeyError:
                store.add_ip(ref=second_failure_ref, content=f"First coder correction failed deterministic validation: {repair_exc}; body repeated the heading and used a forbidden overclaim phrase.", kind="FailureIP", origin="failure_history", outcome="failed", session_id=SESSION, metadata={"action_id": coder_manifest["action_id"], "raw_sha256": coder_manifest["raw_sha256"]})
                store.add_relation(source_ref=second_failure_ref, target_ref=coder_failure_ref, relation="follows", note="First coder correction remained outside inert artifact grammar")
            coded, coder_manifest, _ = model_call(action_id="worker:hermes-governor-v1:coder-3", role="coder", prompt_value={"parent_action": "worker:hermes-governor-v1:coder-2", "exact_defects": [str(repair_exc), "Body must not contain any Markdown heading", "Never use the exact phrase unrestricted self-improvement, even in a negation"], "task_scope": scope, "accepted_plan": planned, "exact_body_contract": "Write 350-800 characters of plain paragraphs only. Include literal terms TaskScope, deterministic, model, SToE Memory, trusted. No headings, lists, paths, hashes, test counts, or autonomy claims."}, schema=patch_schema, difficulty="high", output_tokens=750)
            coded_control = validate_control(coded["control"])
            patch = validate_doc_patch(coded["patch"], parent_sha=parent_sha)
    candidate = parent.rstrip() + "\n\n## " + HEADING + "\n\n" + patch["body"].strip() + "\n"
    if candidate == parent or candidate.count("## " + HEADING) != 1 or not candidate.startswith(parent.rstrip()):
        raise RuntimeError("candidate is not one exact append")
    candidate_path = action_dir(coder_manifest["action_id"]) / "candidate_README.md"
    candidate_path.write_text(candidate, encoding="utf-8", newline="\n")
    patch_path = action_dir(coder_manifest["action_id"]) / "candidate_patch.json"
    atomic_json(patch_path, patch)
    artifact = {"path": str(patch_path.relative_to(ROOT / "agent" / "runtime")).replace('\\', '/'), "sha256": sha256(patch_path.read_bytes()), "size_bytes": patch_path.stat().st_size}
    coder_refs = record_control(action_id=coder_manifest["action_id"], role="coder", manifest=coder_manifest, control=coded_control, goal=OBJECTIVE, artifact=artifact)
    if coder_manifest["action_id"].endswith("coder-2"):
        store.add_relation(source_ref=coder_refs["result"], target_ref="IP_hermes_governor_coder_failure01", relation="corrects", note="Linked coder successor corrects deterministic content defects")
    elif coder_manifest["action_id"].endswith("coder-3"):
        store.add_relation(source_ref=coder_refs["result"], target_ref="IP_hermes_governor_coder_failure02", relation="corrects", note="Final bounded coder successor corrects exact artifact-grammar defects")
    reviewed, reviewer_manifest, reviewer_meta = model_call(action_id="worker:hermes-governor-v1:reviewer-1", role="reviewer", prompt_value={"task_scope": scope, "accepted_plan": planned, "candidate_append": patch["body"], "deterministic": {"identity": "passed", "bounded_append": "passed", "required_concepts": "passed"}}, schema=control_schema(), difficulty="high", output_tokens=650)
    if reviewed.get("status") == "deferred": print(json.dumps({"status": "deferred", "stage": "reviewer", **reviewer_meta}, indent=2)); return 2
    reviewed = validate_control(reviewed)
    reviewer_refs = record_control(action_id=reviewer_manifest["action_id"], role="reviewer", manifest=reviewer_manifest, control=reviewed, goal=OBJECTIVE)
    if reviewed["status"] != "success":
        raise RuntimeError("independent reviewer rejected candidate")
    result = {"status": "awaiting_trusted_apply", "task_scope_ref": scope_ref, "candidate_path": str(candidate_path), "candidate_sha256": sha256(candidate_path.read_bytes()), "patch_artifact_sha256": artifact["sha256"], "parent_sha256": parent_sha, "models": {"governor": governed_manifest["model"], "planner": planner_manifest["model"], "coder": coder_manifest["model"], "reviewer": reviewer_manifest["model"]}, "refs": {"governor": governor_refs, "planner": planner_refs, "coder": coder_refs, "reviewer": reviewer_refs}, "actions": [governed_manifest["action_id"], planner_manifest["action_id"], coder_manifest["action_id"], reviewer_manifest["action_id"]]}
    atomic_json(RUNTIME / "result.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
