from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))
TEST_TMP = ROOT / "agent" / "runtime" / "local_worker_tests"
TEST_TMP.mkdir(parents=True, exist_ok=True)

from stoe_agent.local_workers import (  # noqa: E402
    LocalWorkerOrchestrator,
    MachineSnapshot,
    OllamaAPI,
    ResourcePolicy,
    TaskDescriptor,
    WorkerContractError,
    WorkerUnavailable,
    capture_machine_snapshot,
    compact_result,
    govern_dispatch,
    load_registry,
    parse_model_inventory,
    record_delegation,
    registry_fingerprint,
    result_schema,
    route_model,
    validate_task_packet,
    validate_worker_result,
)


ACTION = "worker:local-v1:test"
MODEL = "fixture:small"


def packet() -> dict:
    return {
        "action_id": ACTION,
        "role": "scout",
        "goal": "Identify the validator function from supplied excerpts.",
        "constraints": ["analysis only", "no patch application"],
        "relevant_context": ["stoe-hermes/src/stoe_hermes/succession.py: validate_candidate_source"],
        "allowed_paths": ["stoe-hermes/src/stoe_hermes/succession.py"],
        "expected_output_schema": result_schema(ACTION, "scout", MODEL),
        "resource_limits": {"mode": "interactive", "max_output_tokens": 400},
        "time_limit_seconds": 30,
        "security_sensitivity": "medium",
        "provenance": {"observer_state_ref": "STATE_fixture"},
    }


def worker_result(**updates) -> dict:
    value = {
        "action_id": ACTION, "status": "success", "worker_role": "scout", "model": MODEL,
        "files_examined": 1, "decision": "Inspect validate_candidate_source.",
        "evidence": ["succession.py contains the validator"], "failures": [], "failure_condition": "",
        "files": ["stoe-hermes/src/stoe_hermes/succession.py"], "test_results": [], "artifact_paths": [],
        "hashes": [], "unresolved": ["parent-relative matching policy"], "confidence": 0.9,
        "recommended_next_action": "Codex inspects the cited function.",
    }
    value.update(updates)
    return value


def models(*, loaded=False, role_score=0.8, size=2_000_000_000) -> list[dict]:
    return [{"model": MODEL, "digest": "d" * 64, "size_bytes": size, "context_capacity": 8192, "loaded": loaded, "observations": ["fixture qualification"], "role_scores": {"scout": role_score}}]


def snapshot(**updates) -> MachineSnapshot:
    values = dict(captured_at=0.0, mode="interactive", total_ram_bytes=64 * 1024**3, available_ram_bytes=40 * 1024**3, process_ram_bytes=None, cpu_percent=None, cpu_count=16, gpu_name=None, gpu_percent=None, total_vram_bytes=None, free_vram_bytes=None, loaded_models=(), active_workers=0, active_heavy_workers=0, unavailable_metrics=("gpu",))
    values.update(updates)
    return MachineSnapshot(**values)


class FakeAPI:
    def __init__(self, value: bytes | Exception):
        self.value = value
        self.calls = []

    def request(self, path, payload=None, timeout=None):
        self.calls.append((path, payload, timeout))
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class FakeField:
    def __init__(self):
        self.nodes = []
        self.edges = []

    def add_ip(self, **kwargs):
        self.nodes.append(kwargs)
        return {"ref": kwargs["ref"]}

    def add_relation(self, **kwargs):
        self.edges.append(kwargs)
        return kwargs

    def record_evaluation(self, **kwargs):
        self.nodes.append(kwargs)
        return {"ref": "EVAL_fixture"}


class LocalWorkerTests(unittest.TestCase):
    def test_model_discovery_parsing_and_loaded_state(self):
        tags = {"models": [{"name": MODEL, "digest": "d" * 64, "size": 123, "details": {"parameter_size": "4B", "quantization_level": "Q4"}}]}
        found = parse_model_inventory(tags, {"models": [{"name": MODEL}]})
        self.assertEqual(MODEL, found[0]["model"])
        self.assertTrue(found[0]["loaded"])
        self.assertEqual("Q4", found[0]["quantization"])

    def test_task_packet_is_compact_and_validated(self):
        self.assertEqual(ACTION, validate_task_packet(packet())["action_id"])
        bad = packet(); bad["role"] = "shell"
        with self.assertRaises(WorkerContractError): validate_task_packet(bad)

    def test_path_traversal_and_protected_scope_fail_closed(self):
        for path in ("../x", ".git/config", ".env"):
            bad = packet(); bad["allowed_paths"] = [path]
            with self.subTest(path=path), self.assertRaises(WorkerContractError): validate_task_packet(bad)

    def test_worker_result_schema_and_malformed_output(self):
        self.assertEqual("success", validate_worker_result(worker_result(), action_id=ACTION, role="scout", model=MODEL)["status"])
        for bad in ({}, dict(worker_result(), unexpected=True), dict(worker_result(), model="wrong")):
            with self.assertRaises(WorkerContractError): validate_worker_result(bad, action_id=ACTION, role="scout", model=MODEL)

    def test_secret_pattern_is_rejected(self):
        bad = packet(); bad["relevant_context"] = ["api_key=github_pat_abcdefghijklmnopqrstuvwxyz"]
        with self.assertRaises(WorkerContractError): validate_task_packet(bad)

    def test_missing_gpu_instrumentation_is_explicit(self):
        with patch("stoe_agent.local_workers._nvidia_snapshot", return_value=(None, None, None, None)), patch("stoe_agent.local_workers._windows_memory", return_value=(None, None)):
            value = capture_machine_snapshot()
        self.assertIn("gpu", value.unavailable_metrics)
        self.assertIsNone(value.free_vram_bytes)

    def test_full_power_never_enters_automatically(self):
        with self.assertRaisesRegex(WorkerContractError, "explicit human"):
            ResourcePolicy(mode="full_power")
        self.assertEqual("full_power", ResourcePolicy(mode="full_power", explicit_full_power=True).mode)

    def test_governor_refuses_low_memory_and_serializes_heavy_worker(self):
        task = TaskDescriptor(role="scout")
        selected = {"action": "RUN", "expected_resource_use": {"model_size_bytes": 12 * 1024**3}}
        low = govern_dispatch(task, selected, snapshot(available_ram_bytes=12 * 1024**3), ResourcePolicy())
        self.assertEqual("RUN_SMALLER_MODEL", low["action"])
        busy = govern_dispatch(task, selected, snapshot(active_heavy_workers=1), ResourcePolicy())
        self.assertEqual("SERIALIZE", busy["action"])

    def test_deterministic_tool_bypasses_model_dispatch(self):
        task = TaskDescriptor(role="scout", deterministic_sufficient=True)
        routed = route_model(task, [], snapshot())
        self.assertEqual("USE_DETERMINISTIC_TOOL_INSTEAD", routed["action"])

    def test_router_prefers_adequate_loaded_model(self):
        candidate_models = models(loaded=False) + [{**models(loaded=True, role_score=0.76)[0], "model": "fixture:loaded", "digest": "e" * 64}]
        routed = route_model(TaskDescriptor(role="scout"), candidate_models, snapshot(loaded_models=("fixture:loaded",)))
        self.assertEqual("fixture:loaded", routed["selected_model"])

    def test_router_prefers_smaller_practical_model_under_pressure(self):
        candidate_models = models(size=2 * 1024**3) + [{**models(role_score=0.9, size=20 * 1024**3)[0], "model": "fixture:huge", "digest": "e" * 64}]
        routed = route_model(TaskDescriptor(role="scout", latency_priority=1.0), candidate_models, snapshot(available_ram_bytes=22 * 1024**3))
        self.assertEqual(MODEL, routed["selected_model"])

    def test_stale_registry_is_invalidated(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps({"fingerprint": "old"}), encoding="utf-8")
            self.assertIsNone(load_registry(path, expected_fingerprint="new"))
            self.assertEqual(64, len(registry_fingerprint(models(), "1", "hardware")))

    def test_compact_packet_rejects_excessive_return_and_preserves_artifact_refs(self):
        value = worker_result(evidence=["e" * 600] * 20, artifact_paths=["runtime/full.json"], hashes=["sha256=x"])
        compact = compact_result(value, max_tokens=400)
        self.assertLessEqual(compact["return_packet_tokens_estimated"], 400)
        self.assertEqual(["runtime/full.json"], compact["artifact_paths"])

    def test_worker_has_no_self_application_or_authority_fields(self):
        schema = result_schema(ACTION, "scout", MODEL)
        for forbidden in ("command", "apply", "commit", "activate", "memory_write"):
            self.assertNotIn(forbidden, schema["properties"])
        self.assertFalse(schema["additionalProperties"])

    def test_malformed_ollama_response_fails_closed_and_raw_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            api = FakeAPI(b"not-json")
            orchestrator = LocalWorkerOrchestrator(api=api, artifact_root=Path(tmp))
            with self.assertRaisesRegex(WorkerContractError, "malformed"):
                orchestrator.run(packet(), TaskDescriptor(role="scout"), {"models": models()}, snapshot())
            raw = next(Path(tmp).rglob("raw_response.json"))
            self.assertEqual(b"not-json", raw.read_bytes())

    def test_timeout_or_unavailable_ollama_is_bounded(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            orchestrator = LocalWorkerOrchestrator(api=FakeAPI(WorkerUnavailable("timeout")), artifact_root=Path(tmp))
            with self.assertRaisesRegex(WorkerUnavailable, "timeout"):
                orchestrator.run(packet(), TaskDescriptor(role="scout"), {"models": models()}, snapshot())

    def test_successful_run_is_artifact_backed_and_resumable(self):
        envelope = {"response": json.dumps(worker_result()), "prompt_eval_count": 100, "eval_count": 50}
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            orchestrator = LocalWorkerOrchestrator(api=FakeAPI(json.dumps(envelope).encode()), artifact_root=Path(tmp))
            outcome = orchestrator.run(packet(), TaskDescriptor(role="scout"), {"models": models()}, snapshot())
            self.assertTrue(Path(outcome["artifact"]["path"]).is_file())
            self.assertTrue(Path(outcome["resume_path"]).is_file())
            self.assertLessEqual(outcome["compact_result"]["return_packet_tokens_estimated"], 400)
            self.assertEqual(64, len(outcome["artifact"]["raw_sha256"]))

    def test_trusted_field_recorder_preserves_failure_and_relations(self):
        field = FakeField()
        failure = worker_result(status="failure", decision="schema failed", failures=["malformed JSON"], failure_condition="missing terminator")
        refs = record_delegation(field, task=packet(), result=failure, artifact={"path": "runtime/raw.json", "sha256": "a" * 64}, session_id="worker:test")
        self.assertEqual(5, len(refs))
        self.assertTrue(any(node.get("origin") == "failure_history" for node in field.nodes))
        self.assertEqual({"depends_on", "generated_by"}, {edge["relation"] for edge in field.edges})


if __name__ == "__main__":
    unittest.main()
