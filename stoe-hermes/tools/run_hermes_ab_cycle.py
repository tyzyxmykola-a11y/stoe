from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.self_code_cycle_v2 import RawOllamaClient, atomic_json, sha256_file
from stoe_agent.token_budget import TokenBudgetManager, TokenEstimator
from stoe_hermes.succession import (
    EDITABLE_PATH,
    ReleaseRecord,
    SuccessionError,
    create_isolated_profile,
    create_isolated_venv,
    expose_integration_plugin,
    materialize_commit,
    patch_schema,
    reconstruct_candidate,
    run_bounded,
    sanitized_candidate_environment,
    sha256_bytes,
    validate_candidate_source,
    validate_patch_envelope,
)


ACTION_ID = "self-code-cycle:hermes-ab-v1:deduplicate-context"
CALL_ID = ACTION_ID + ":candidate-generation"
HERMES_SHA = "bb924730743cc05934bf0dfd188abdfdb46c03c2"
HERMES_VERSION = "0.20.3 (2026.8.16.2)"
MODEL = "gemma4:26b"
MODEL_DIGEST = "08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"action_id": ACTION_ID, "status": "new", "calls": {}, "created_at": utc_now()}


def build_prompt(parent: str, parent_sha: str) -> tuple[str, str]:
    system = (
        "You propose inert source patches for a protected self-development supervisor. "
        "Return only the JSON object required by the supplied schema. You have no authority "
        "to activate, execute commands, read files, add dependencies, or alter any other path."
    )
    prompt = f"""Objective: improve the SToE-Hermes context renderer in {EDITABLE_PATH}.

The renderer must emit identical content bytes once per canonical SHA-256 while emitting every distinct connection, provenance path, relation, direction, origin, kind, outcome, and ref. It must report how many duplicate payload appearances were collapsed. It must obey max_chars using complete lines and remain deterministic. Preserve the public function signature and imports. Do not access files, environment, processes, network, globals, dynamic attributes, or external state.

Return a stoe.line_patch v3 replacing only the function. Use the exact path and parent hash below. Keep the implementation compact and inside the pure reporting call/attribute allowlist.

Parent SHA-256: {parent_sha}
Trusted parent source (included exactly once):
---
{parent}
---
"""
    return system, prompt


def qualification_summary() -> dict:
    """Machine-readable gate; the complete deterministic suite is run externally."""
    parent = (ROOT / EDITABLE_PATH).read_text(encoding="utf-8")
    parent_sha = sha256_bytes(parent.encode("utf-8"))
    safe = {
        "format": "stoe.line_patch", "version": 3, "path": EDITABLE_PATH,
        "parent_sha256": parent_sha,
        "replacement_lines": ["def render_retrieved_context(items, max_chars):", "    return str(len(items))[:max_chars]"],
    }
    validate_patch_envelope(safe, parent_sha256=parent_sha)
    validate_candidate_source(parent, reconstruct_candidate(parent, safe))
    for forbidden in ("../escape.py", "stoe-hermes/src/stoe_hermes/succession.py"):
        try:
            validate_patch_envelope(dict(safe, path=forbidden), parent_sha256=parent_sha)
        except SuccessionError:
            continue
        raise RuntimeError("forbidden deterministic patch passed")
    return {"passed": True, "parent_sha256": parent_sha, "checks": ["safe_patch", "source_capability", "forbidden_paths"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-repo", type=Path, required=True)
    parser.add_argument("--skill-dir", type=Path, required=True)
    parser.add_argument("--qualify-only", action="store_true")
    args = parser.parse_args()
    runtime = ROOT / "agent" / "runtime" / "hermes_ab_v1"
    runtime.mkdir(parents=True, exist_ok=True)
    qualification = qualification_summary()
    atomic_json(runtime / "deterministic_gate.json", qualification)
    if args.qualify_only:
        print(json.dumps(qualification, indent=2))
        return 0

    state_path = runtime / "state.json"
    state = load_state(state_path)
    if state["status"] != "new" or state["calls"]:
        raise RuntimeError("stable Hermes A/B action already started; it cannot be repeated")

    client = RawOllamaClient(timeout_seconds=900)
    capability = client.capability()
    if capability["model"] != MODEL or capability["digest"] != MODEL_DIGEST:
        raise RuntimeError("exact frozen model identity mismatch")
    parent_path = ROOT / EDITABLE_PATH
    parent = parent_path.read_text(encoding="utf-8")
    parent_sha = sha256_bytes(parent.encode("utf-8"))
    system, prompt = build_prompt(parent, parent_sha)
    output_reserve = max(1800, math.ceil(len(parent.encode("utf-8")) / 2))
    budget = TokenBudgetManager(
        context_limit_tokens=capability["effective_context_tokens"],
        checkpoint_reserve_tokens=1024,
        estimator=TokenEstimator(),
    ).require_plan(
        system=system,
        prompt=prompt,
        reserved_generation_tokens=output_reserve,
        categories={"task_context": prompt, "retrieved_material": parent, "tool_results": ""},
    )
    state.update({"status": "running", "capability": capability, "budget": budget, "calls": {CALL_ID: {"status": "started", "started_at": utc_now()}}})
    atomic_json(state_path, state)

    raw_path = runtime / "raw" / "candidate_generation.ndjson"
    result = client.generate(
        system=system,
        prompt=prompt,
        schema=patch_schema(EDITABLE_PATH, parent_sha),
        raw_path=raw_path,
        num_ctx=capability["effective_context_tokens"],
        num_predict=output_reserve,
        seed=918273,
    )
    state = load_state(state_path)
    state["calls"][CALL_ID] = {"status": "completed" if result["diagnosis"] == "COMPLETE_STRUCTURED_OUTPUT" else "failed", "result": result, "completed_at": utc_now()}
    state["raw_response_sha256"] = result["raw_response_sha256"]
    if result["diagnosis"] != "COMPLETE_STRUCTURED_OUTPUT":
        state.update({"status": "failed", "failure": result["diagnosis"]})
        atomic_json(state_path, state)
        print(json.dumps({"status": state["status"], "diagnosis": result["diagnosis"], "raw_response_sha256": result["raw_response_sha256"]}, indent=2))
        return 2

    try:
        patch = validate_patch_envelope(result["parsed"], parent_sha256=parent_sha)
        candidate = reconstruct_candidate(parent, patch)
        validation = validate_candidate_source(parent, candidate)
    except Exception as exc:
        state.update({"status": "failed", "failure": f"{type(exc).__name__}: {exc}"})
        atomic_json(state_path, state)
        print(json.dumps({"status": "failed", "failure": state["failure"], "raw_response_sha256": result["raw_response_sha256"]}, indent=2))
        return 2

    b_root = runtime / "candidate_B"
    if b_root.exists():
        raise RuntimeError("candidate B directory already exists; refusing ambiguous recovery")
    b_root.mkdir(parents=True)
    assembly = materialize_commit(args.hermes_repo.resolve(), HERMES_SHA, b_root / "hermes-agent")
    integration = b_root / "stoe-integration"
    shutil.copytree(ROOT / "stoe-hermes", integration, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    candidate_path = integration / "src" / "stoe_hermes" / "context_renderer.py"
    candidate_path.write_text(candidate, encoding="utf-8", newline="\n")
    environment = create_isolated_venv(b_root / "venv")
    profile = create_isolated_profile(
        b_root / "profile", candidate_cwd=b_root / "hermes-agent",
        python_command=environment["python"], mcp_server=ROOT / "plugins" / "stoe-memory" / "server.py",
        skill_dir=args.skill_dir.resolve(),
    )
    plugin_loader = expose_integration_plugin(Path(profile["profile_root"]), integration)
    env = sanitized_candidate_environment(Path(profile["profile_root"]), Path(environment["environment_root"]))
    env["PYTHONPATH"] = str((integration / "src").resolve())
    check_code = (
        "from stoe_hermes.context_renderer import render_retrieved_context; import hashlib; "
        "c='same'; h=hashlib.sha256(c.encode()).hexdigest(); "
        "items=[{'sha256':h,'content':c,'ref':'A','relation':'evaluates','provenance':'p1'},"
        "{'sha256':h,'content':c,'ref':'B','relation':'correction_of','provenance':'p2'}]; "
        "r=render_retrieved_context(items,4000); "
        "assert r.count('PAYLOAD |')==1 and r.count('CONNECTION |')==2 and 'collapsed=1' in r"
    )
    tests = [
        run_bounded([environment["python"], "-m", "py_compile", str(candidate_path)], cwd=integration, env=env),
        run_bounded([environment["python"], "-c", check_code], cwd=integration, env=env),
    ]
    environment_fingerprint = sha256_bytes(json.dumps({"assembly": assembly, "profile": profile, "environment": environment, "plugin_loader": plugin_loader}, sort_keys=True).encode("utf-8"))
    release = ReleaseRecord(
        release_id="hermes-b-" + validation["candidate_sha256"][:12],
        source_repository=str(args.hermes_repo.resolve()), commit_sha=HERMES_SHA,
        parent_release="hermes-a-" + HERMES_SHA[:12], hermes_version=HERMES_VERSION,
        integration_plugin_version="0.1.0", model_configuration={"model": MODEL, "digest": MODEL_DIGEST},
        configuration_hash=profile["config_sha256"], environment_fingerprint=environment_fingerprint,
        test_results=tests, candidate_status="candidate" if all(item["passed"] for item in tests) else "rejected",
        activation_status="inactive", rollback_target="hermes-a-" + HERMES_SHA[:12], creation_action_id=ACTION_ID,
        activation_blockers=assembly["activation_blockers"],
    )
    atomic_json(runtime / "release.json", release.as_dict())
    atomic_json(runtime / "patch.json", patch)
    state.update({
        "status": "candidate_preserved" if release.candidate_status == "candidate" else "rejected",
        "candidate_sha256": validation["candidate_sha256"], "candidate_path": str(candidate_path),
        "release_path": str(runtime / "release.json"), "activation_status": "inactive",
        "activation_blockers": release.activation_blockers, "test_results": tests,
    })
    atomic_json(state_path, state)
    print(json.dumps({key: state[key] for key in ("status", "candidate_sha256", "raw_response_sha256", "activation_status", "activation_blockers")}, indent=2))
    return 0 if state["status"] == "candidate_preserved" else 2


if __name__ == "__main__":
    raise SystemExit(main())
