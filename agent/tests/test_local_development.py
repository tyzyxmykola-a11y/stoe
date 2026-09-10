from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_development import (  # noqa: E402
    FIELDS,
    MAX_RAW_BYTES,
    LocalDevelopmentError,
    control_schema,
    load_instructions,
    model_instructions,
    parse_preserved_control,
    record_envelope,
    trusted_envelope,
    validate_candidate_artifact,
    validate_control,
)
from stoe_agent.local_workers import result_schema  # noqa: E402


def control(**updates):
    value = {"status": "success", "decision": "Use the existing adapter.", "evidence": ["Interface is already bounded."], "risks": [], "next_action": "Implement one focused change."}
    value.update(updates)
    return value


def ollama_envelope(value=None, **updates):
    envelope = {
        "done": True,
        "done_reason": "stop",
        "response": json.dumps(value or control()),
    }
    envelope.update(updates)
    return json.dumps(envelope).encode()


class FakeField:
    def __init__(self):
        self.nodes = {}
        self.edges = []

    def get_ip(self, ref):
        if ref not in self.nodes:
            raise KeyError(ref)
        return self.nodes[ref]

    def add_ip(self, **kwargs):
        self.nodes[kwargs["ref"]] = kwargs
        return {"ref": kwargs["ref"]}

    def add_relation(self, **kwargs):
        self.edges.append(kwargs)

    def record_evaluation(self, **kwargs):
        return {"evaluation": {"ref": "EVAL_v2"}}


class LocalDevelopmentV2Tests(unittest.TestCase):
    def test_exactly_five_fields_and_extra_rejected(self):
        self.assertEqual(FIELDS, set(validate_control(control())))
        with self.assertRaises(LocalDevelopmentError):
            validate_control({**control(), "model": "untrusted"})

    def test_status_evidence_and_risk_invariants(self):
        with self.assertRaisesRegex(LocalDevelopmentError, "evidence"):
            validate_control(control(evidence=[]))
        for status in ("failure", "deferred"):
            with self.subTest(status=status), self.assertRaisesRegex(LocalDevelopmentError, "risks"):
                validate_control(control(status=status, evidence=[], risks=[]))

    def test_v2_schema_excludes_supervisor_metadata(self):
        schema = control_schema()
        self.assertEqual(FIELDS, set(schema["properties"]))
        for name in ("action_id", "role", "model", "digest", "artifact_paths", "hashes", "test_results"):
            self.assertNotIn(name, schema["properties"])
        with self.assertRaisesRegex(LocalDevelopmentError, "supervisor-known metadata"):
            validate_control(control(decision="Used worker:v2:planner:secret"), known_metadata=("worker:v2:planner:secret",))

    def test_role_loader_is_hash_bound_and_selective(self):
        text, artifacts = model_instructions("planner")
        self.assertIn("smallest implementable", text)
        self.assertNotIn("Independently inspect", text)
        self.assertNotIn("ChatGPT is the SToE architect", text)
        self.assertNotIn("Escalate when", text)
        self.assertEqual({"architecture", "escalation", "contract", "role"}, set(artifacts))
        self.assertTrue(all(len(item["sha256"]) == 64 for item in artifacts.values()))

    def test_test_analyst_is_a_hash_bound_non_coding_role(self):
        text, artifacts = model_instructions("test_analyst")
        self.assertIn("smallest exact behavioral defect", text)
        self.assertIn("Do not write implementation", text)
        self.assertEqual({"architecture", "escalation", "contract", "role"}, set(artifacts))
        envelope = trusted_envelope(control(status="failure", evidence=[], risks=["exact failed assertion"]), action_id="worker:v2:test-analysis:1", role="test_analyst", model="local", digest="d" * 64, instructions=artifacts)
        self.assertEqual("test_analyst", envelope["role"])

    def test_instruction_content_hash_is_verified_before_trust(self):
        instructions = load_instructions("planner")
        instructions["role"]["content"] += "tampered"
        with self.assertRaisesRegex(LocalDevelopmentError, "does not match"):
            trusted_envelope(control(), action_id="worker:v2:plan:1", role="planner", model="local", digest="d" * 64, instructions=instructions)

    def test_trusted_envelope_adds_identity_and_separate_artifact(self):
        instructions = load_instructions("coder")
        artifact = {"path": "candidate.json", "sha256": "c" * 64, "size_bytes": 120}
        value = trusted_envelope(control(), action_id="worker:v2:coder:1", role="coder", model="local", digest="d" * 64, instructions=instructions, artifact=artifact)
        self.assertEqual(artifact, value["candidate_artifact"])
        self.assertNotIn("candidate_artifact", value["control"])
        failed = trusted_envelope(control(status="failure", evidence=[], risks=["exact blocker"]), action_id="worker:v2:coder:2", role="coder", model="local", digest="d" * 64, instructions=instructions)
        self.assertEqual("exact blocker", failed["failure_condition"])

    def test_successful_coder_requires_strict_inert_artifact(self):
        instructions = load_instructions("coder")
        with self.assertRaisesRegex(LocalDevelopmentError, "requires"):
            trusted_envelope(control(), action_id="worker:v2:coder:3", role="coder", model="local", digest="d" * 64, instructions=instructions)
        invalid = [
            {"path": "../candidate.json", "sha256": "c" * 64, "size_bytes": 20},
            {"path": "candidate.py", "sha256": "c" * 64, "size_bytes": 20},
            {"path": "candidate.json", "sha256": "bad", "size_bytes": 20},
            {"path": "candidate.json", "sha256": "c" * 64, "size_bytes": 0},
            {"path": "candidate.json", "sha256": "c" * 64, "size_bytes": 20, "content": "print(1)"},
        ]
        for artifact in invalid:
            with self.subTest(artifact=artifact), self.assertRaises(LocalDevelopmentError):
                validate_candidate_artifact(artifact)

    def test_malformed_and_truncated_raw_are_preserved_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "agent" / "runtime") as raw:
            path = Path(raw) / "raw.json"
            for payload in (b"not-json", json.dumps({"response": '{"status":"success"'}).encode()):
                with self.assertRaises(LocalDevelopmentError):
                    parse_preserved_control(payload, path)
                self.assertEqual(payload, path.read_bytes())
                path.unlink()

    def test_incomplete_and_length_limited_envelopes_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "agent" / "runtime") as raw:
            path = Path(raw) / "raw.json"
            for payload in (
                ollama_envelope(done=False),
                ollama_envelope(done_reason="length"),
                ollama_envelope(done_reason="error"),
            ):
                with self.subTest(payload=payload), self.assertRaises(LocalDevelopmentError):
                    parse_preserved_control(payload, path)
                self.assertEqual(payload, path.read_bytes())

    def test_oversized_raw_is_capped_with_explicit_metadata(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "agent" / "runtime") as raw:
            path = Path(raw) / "raw.json"
            payload = b"x" * (MAX_RAW_BYTES + 7)
            with self.assertRaisesRegex(LocalDevelopmentError, "capped evidence"):
                parse_preserved_control(payload, path)
            self.assertEqual(MAX_RAW_BYTES, path.stat().st_size)
            metadata = json.loads(path.with_suffix(".json.metadata.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata["truncated"])
            self.assertEqual(MAX_RAW_BYTES + 7, metadata["original_bytes"])
            self.assertEqual(MAX_RAW_BYTES, metadata["preserved_bytes"])

    def test_v1_contract_remains_available(self):
        self.assertIn("action_id", result_schema("worker:v1:test", "planner", "fixture")["properties"])

    def test_successful_result_records_instruction_provenance(self):
        instructions = load_instructions("reviewer")
        envelope = trusted_envelope(control(), action_id="worker:v2:review:1", role="reviewer", model="local", digest="d" * 64, instructions=instructions)
        field = FakeField()
        refs = record_envelope(field, envelope, goal="Review candidate", session_id="test")
        self.assertEqual(4, len(refs["instructions"]))
        result = field.nodes[refs["result"]]
        self.assertEqual(envelope["control"], result["metadata"]["control"])
        self.assertEqual({"depends_on", "generated_by", "evaluates"}, {edge["relation"] for edge in field.edges})
        node_count, edge_count = len(field.nodes), len(field.edges)
        replayed = record_envelope(field, envelope, goal="Review candidate", session_id="test")
        self.assertEqual(refs, replayed)
        self.assertEqual(node_count, len(field.nodes))
        self.assertEqual(edge_count, len(field.edges))

    def test_candidate_is_canonical_artifact_ip_with_typed_links(self):
        instructions = load_instructions("coder")
        artifact = {"path": "candidate.json", "sha256": "c" * 64, "size_bytes": 120}
        envelope = trusted_envelope(control(), action_id="worker:v2:coder:4", role="coder", model="local", digest="d" * 64, instructions=instructions, artifact=artifact)
        field = FakeField()
        refs = record_envelope(field, envelope, goal="Build candidate", session_id="test")
        self.assertEqual("ArtifactIP", field.nodes[refs["artifact"]]["kind"])
        linked = {(edge["source_ref"], edge["target_ref"], edge["relation"]) for edge in field.edges}
        self.assertIn((refs["artifact"], refs["action"], "generated_by"), linked)
        self.assertIn((refs["result"], refs["artifact"], "depends_on"), linked)

    def test_existing_instruction_ref_must_match_full_sha_metadata(self):
        instructions = load_instructions("reviewer")
        envelope = trusted_envelope(control(), action_id="worker:v2:review:collision", role="reviewer", model="local", digest="d" * 64, instructions=instructions)
        item = envelope["instruction_artifacts"]["contract"]
        ref = "LDI_" + item["sha256"][:16]
        field = FakeField()
        field.nodes[ref] = {"ref": ref, "content": "wrong", "kind": "InstructionArtifactIP", "metadata": {**item, "sha256": "0" * 64}}
        with self.assertRaisesRegex(LocalDevelopmentError, "collision"):
            record_envelope(field, envelope, goal="Review candidate", session_id="test")


if __name__ == "__main__":
    unittest.main()
