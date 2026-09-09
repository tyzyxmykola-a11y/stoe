from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_workers import (  # noqa: E402
    LocalWorkerOrchestrator,
    OllamaAPI,
    ResourcePolicy,
    TaskDescriptor,
    capture_machine_snapshot,
    chunk_context_text,
    compact_failed_response,
    environment_summary,
    redact_python_assignments,
    record_delegation,
    registry_fingerprint,
    result_schema,
    save_registry,
)
from stoe_agent.token_budget import TokenEstimator  # noqa: E402


RUNTIME = ROOT / "agent" / "runtime" / "local_workers_v1"
SESSION = "development:local-workers-v1"
PILOT_ACTION = "worker:hermes-v2.2:validator-analysis-v1"
TARGET = "stoe-hermes/src/stoe_hermes/succession.py"


def field_store():
    core = ROOT / "plugins" / "stoe-memory" / "core.py"
    spec = importlib.util.spec_from_file_location("stoe_local_worker_memory", core)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the repository SToE Memory implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    store = module.FieldStore()
    store.initialize()
    return store


def add_repository_evidence(discovery: dict) -> None:
    manifest_path = ROOT / "stoe-hermes" / "HERMES_AB_V2_1_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gemma = manifest["models"]["gemma"]
    coder = manifest["models"]["coder"]
    for model in discovery["models"]:
        if model["model"] == gemma["name"] and model["digest"] == gemma["digest"]:
            model["observations"].append("v2.1 fixed-table plan was schema-valid on first attempt")
            model["role_scores"].update({"planner": 0.86, "reviewer": 0.76, "summarizer": 0.72})
            model["json_reliability"] = 1.0
        if model["model"] == coder["name"] and model["digest"] == coder["digest"]:
            model["observations"].append("v2.1 inert coding patch was complete and schema-valid")
            model["role_scores"].update({"coder": 0.88, "reviewer": 0.58, "scout": 0.62})
            model["json_reliability"] = 1.0


def discover(api: OllamaAPI, mode: str) -> tuple[dict, object]:
    discovery = api.discover()
    add_repository_evidence(discovery)
    snapshot = capture_machine_snapshot(mode=mode, loaded_models=discovery["loaded_models"])
    hardware_key = json.dumps({"ram": snapshot.total_ram_bytes, "gpu": snapshot.gpu_name, "vram": snapshot.total_vram_bytes, "cpu_count": snapshot.cpu_count}, sort_keys=True)
    discovery["fingerprint"] = registry_fingerprint(discovery["models"], discovery["ollama_version"], hardware_key)
    discovery["hardware"] = environment_summary(snapshot)
    save_registry(RUNTIME / "capability_registry.json", discovery)
    return discovery, snapshot


def function_excerpt(path: Path, function_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == function_name)
    lines = source.splitlines()
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def pilot(api: OllamaAPI, observer_state_ref: str) -> dict:
    discovery, snapshot = discover(api, "interactive")
    store = field_store()
    retrieval = store.navigate(observer_state_ref=observer_state_ref, include_seed=False, include_failures=True, limit=6, max_depth=4, per_item_chars=450, total_chars=2_700, run_label="local_worker_validator_analysis")
    target_path = ROOT / TARGET
    full_source = target_path.read_text(encoding="utf-8")
    narrowed = function_excerpt(target_path, "validate_candidate_source")
    narrowed = redact_python_assignments(narrowed, {"secret_patterns"})
    context = chunk_context_text("SOURCE_EXCERPT", narrowed)
    context.extend(f"STOE_REF={item['ref']} ORIGIN={item['origin']} OUTCOME={item['outcome']} CONTENT={item['content']}" for item in retrieval["selected_items"])
    task = TaskDescriptor(role="reviewer", difficulty="high", code_heavy=True, estimated_input_tokens=TokenEstimator().estimate("\n".join(context)), required_output_tokens=650, requires_json=True, security_sensitive=True, quality_priority=1.0, latency_priority=0.25)
    packet = {
        "action_id": PILOT_ACTION, "role": "reviewer",
        "goal": "Analyze the supplied protected validator excerpt and conserved v2.1 failure. Recommend a narrow parent-relative policy for inherited ast.Raise without writing or applying code.",
        "constraints": ["analysis only", "no code or patch", "no filesystem or tools", "all authority-bearing constructs remain rejected", "candidate remains byte-identical", "cite supplied evidence only"],
        "relevant_context": context, "allowed_paths": [TARGET],
        "expected_output_schema": result_schema(PILOT_ACTION, "reviewer", "selected-at-dispatch", [TARGET]),
        "resource_limits": {"mode": "interactive", "one_heavy_worker": True, "max_output_tokens": 650, "operator_ram_reserve_bytes": 10 * 1024**3, "operator_vram_reserve_bytes": 2 * 1024**3},
        "time_limit_seconds": 420, "security_sensitivity": "high",
        "provenance": {"observer_state_ref": observer_state_ref, "retrieval_run_id": retrieval["run_id"], "release": "2d31df76e2350b2845be27adf757228988670359"},
    }
    orchestrator = LocalWorkerOrchestrator(api=api, artifact_root=RUNTIME / "artifacts", policy=ResourcePolicy(mode="interactive"))
    outcome = orchestrator.run(packet, task, discovery, snapshot)
    if outcome["compact_result"] is None:
        return {"status": "deferred", "outcome": outcome, "narrowing": {"full_source_bytes": len(full_source.encode()), "narrowed_bytes": len(narrowed.encode())}}
    result_artifact = json.loads(Path(outcome["artifact"]["path"]).read_text(encoding="utf-8"))
    refs = record_delegation(store, task=packet, result=result_artifact, artifact={"path": outcome["artifact"]["path"], "sha256": outcome["artifact"]["sha256"]}, session_id=SESSION)
    evaluation = {
        "schema_valid": True,
        "full_source_tokens_estimated": TokenEstimator().estimate(full_source),
        "narrowed_source_tokens_estimated": TokenEstimator().estimate(narrowed),
        "compact_return_tokens_estimated": outcome["compact_result"]["return_packet_tokens_estimated"],
        "local_delegation_ratio": round(1 - len(narrowed.encode()) / max(1, len(full_source.encode())), 4),
        "compression_ratio": round(TokenEstimator().estimate(narrowed) / max(1, outcome["compact_result"]["return_packet_tokens_estimated"]), 3),
    }
    report = {"status": "completed", "registry_fingerprint": discovery["fingerprint"], "machine_snapshot": snapshot.__dict__, "retrieval_run_id": retrieval["run_id"], "outcome": outcome, "field_refs": refs, "evaluation": evaluation}
    report_path = RUNTIME / "LOCAL_WORKER_PILOT.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return report


def summarize_pilot_failure() -> dict:
    raw_path = RUNTIME / "artifacts" / PILOT_ACTION.replace(":", "_") / "raw_response.json"
    value = compact_failed_response(
        raw_path,
        action_id=PILOT_ACTION,
        role="reviewer",
        model="gemma4:12b",
        parser_error="Unterminated JSON string after Ollama exhausted the configured output limit.",
    )
    summary_path = raw_path.parent / "failure_summary.json"
    summary_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return {"status": "completed", "failure_summary_path": str(summary_path), **value}


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded trusted SToE local-worker orchestration")
    parser.add_argument("command", choices=["discover", "pilot", "summarize-failure"])
    parser.add_argument("--observer-state", default="STATE_ea54e40a1786498c")
    args = parser.parse_args()
    api = OllamaAPI()
    if args.command == "discover":
        value = discover(api, "interactive")[0]
    elif args.command == "pilot":
        value = pilot(api, args.observer_state)
    else:
        value = summarize_pilot_failure()
    print(json.dumps(value, indent=2, sort_keys=True, default=str))
    return 0 if value.get("status", "completed") in {"completed", "success"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
