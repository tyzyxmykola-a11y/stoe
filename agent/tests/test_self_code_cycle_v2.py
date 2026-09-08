from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from stoe_agent.self_code_cycle_v2 import (
    EDITABLE_PATH,
    FORMAT,
    PARENT_SHA256,
    MAX_RESPONSE_BYTES,
    SelfCodeCycleV2,
    VERSION,
    DuplicateJSONKeyError,
    V2BoundaryError,
    analyze_ollama_stream,
    canonicalize_payloads,
    reconstruct_candidate,
    record_transport_termination,
    strict_json_loads,
    validate_candidate_source,
    validate_patch_envelope,
)


def envelope(lines=None):
    return {
        "format": FORMAT,
        "version": VERSION,
        "path": EDITABLE_PATH,
        "parent_sha256": PARENT_SHA256,
        "replacement_lines": lines or [
            "def render_retrieved_context(items, max_chars):",
            "    return \"\"",
        ],
        "rationale": "Keep the report bounded.",
        "expected_effect": "Return a deterministic report.",
        "risk_notes": [],
    }


def event(response, *, done=True, reason="done", prompt=10, output=20):
    return (json.dumps({"response": response, "done": done, "done_reason": reason, "prompt_eval_count": prompt, "eval_count": output}) + "\n").encode()


class SelfCodeCycleV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.parent = (cls.repo_root / EDITABLE_PATH).read_text(encoding="utf-8")

    def test_raw_stream_classifies_complete_structured_output(self):
        raw = event(json.dumps(envelope()))
        result = analyze_ollama_stream(raw, output_limit_tokens=100)
        self.assertEqual("COMPLETE_STRUCTURED_OUTPUT", result["diagnosis"])
        self.assertTrue(result["stream_complete"])
        self.assertEqual(30, result["total_tokens"])

    def test_truncated_interrupted_broken_and_extra_prose_are_distinguished(self):
        truncated = analyze_ollama_stream(event('{"format":"stoe.line', reason="length", output=10), output_limit_tokens=10)
        self.assertEqual("OUTPUT_TRUNCATION", truncated["diagnosis"])
        interrupted = analyze_ollama_stream(event('{"format":', done=False, reason=""), output_limit_tokens=100)
        self.assertEqual("INTERRUPTED_STREAM", interrupted["diagnosis"])
        broken_escape = analyze_ollama_stream(event('{"x":"\\q"}'), output_limit_tokens=100)
        self.assertEqual("SCHEMA_NONCOMPLIANCE", broken_escape["diagnosis"])
        missing_terminator = analyze_ollama_stream(event('{"x":"open'), output_limit_tokens=100)
        self.assertEqual("SCHEMA_NONCOMPLIANCE", missing_terminator["diagnosis"])
        prose = analyze_ollama_stream(event('Here is the patch: {"x":1}'), output_limit_tokens=100)
        self.assertEqual("SCHEMA_NONCOMPLIANCE", prose["diagnosis"])

    def test_duplicate_json_fields_are_rejected_at_every_depth(self):
        with self.assertRaises(DuplicateJSONKeyError):
            strict_json_loads('{"path":"a","path":"b"}')
        raw = event('{"format":"stoe.line_patch","version":2,"version":3}')
        result = analyze_ollama_stream(raw, output_limit_tokens=100)
        self.assertIn("duplicate JSON field", result["parser_error"])

    def test_stream_reconstruction_error_is_not_mislabeled_as_schema_failure(self):
        raw = b'{not an event}\n' + event(json.dumps(envelope()))
        result = analyze_ollama_stream(raw, output_limit_tokens=100)
        self.assertEqual("STREAM_RECONSTRUCTION_FAILURE", result["diagnosis"])

    def test_wire_capture_limit_is_bounded_but_not_confused_with_model_truncation(self):
        self.assertGreaterEqual(MAX_RESPONSE_BYTES, 1_000_000)
        result = analyze_ollama_stream(event('{"open":', done=False), output_limit_tokens=1400)
        record_transport_termination(result, "RuntimeError: raw response exceeded byte limit")
        self.assertEqual("RAW_CAPTURE_LIMIT_ABORT", result["diagnosis"])
        self.assertEqual("trusted_raw_capture_byte_limit", result["termination_reason"])

    def test_envelope_rejects_malicious_path_stale_parent_oversize_and_hidden_code(self):
        mutations = []
        path = envelope()
        path["path"] = "../agent/src/stoe_agent/development_report.py"
        mutations.append(path)
        protected = envelope()
        protected["path"] = "agent/src/stoe_agent/supervisor.py"
        mutations.append(protected)
        stale = envelope()
        stale["parent_sha256"] = "0" * 64
        mutations.append(stale)
        oversized = envelope(["def render_retrieved_context(items, max_chars):", "    value = \"" + "x" * 181 + "\""])
        mutations.append(oversized)
        hidden = envelope()
        hidden["rationale"] = "Use __builtins__.open('cases.json')"
        mutations.append(hidden)
        extra = envelope()
        extra["dependency_change"] = "requirements.txt"
        mutations.append(extra)
        for value in mutations:
            with self.subTest(value=value):
                with self.assertRaises(V2BoundaryError):
                    validate_patch_envelope(value)

    def test_reconstruction_validates_utf8_size_line_count_capability_and_sha(self):
        patch = envelope()
        candidate = reconstruct_candidate(self.parent, patch)
        result = validate_candidate_source(self.parent, candidate)
        self.assertEqual(hashlib.sha256(candidate.encode()).hexdigest(), result["candidate_sha256"])
        authority = envelope([
            "def render_retrieved_context(items, max_chars):",
            "    return open('cases.json').read()",
        ])
        with self.assertRaisesRegex(V2BoundaryError, "capability allowlist"):
            validate_candidate_source(self.parent, reconstruct_candidate(self.parent, authority))

    def test_canonical_payload_dedup_preserves_all_connections(self):
        content = "one canonical payload " * 40
        digest = hashlib.sha256(content.encode()).hexdigest()
        instances = [
            {"ref": "A", "relation": "evaluates", "direction": "outgoing", "provenance": "evaluation", "content": content, "payload_sha256": digest, "canonical_path": "artifact.json"},
            {"ref": "B", "relation": "invalidates", "direction": "incoming", "provenance": "failure_history", "content": content, "payload_sha256": digest, "canonical_path": "artifact.json"},
        ]
        result = canonicalize_payloads(instances)
        self.assertEqual(1, len(result["canonical_payloads"]))
        self.assertEqual(2, len(result["connections"]))
        self.assertEqual(1, result["collapsed_payload_copies"])
        self.assertGreater(result["tokens_before"], result["tokens_after"])

    def test_declared_payload_hash_must_match_content(self):
        with self.assertRaisesRegex(V2BoundaryError, "does not match"):
            canonicalize_payloads([{"ref": "A", "content": "x", "payload_sha256": "0" * 64}])

    def test_started_stable_action_is_never_repeated_after_interruption(self):
        class MustNotCallClient:
            def generate(self, **kwargs):
                raise AssertionError("provider call was repeated")

        state = {
            "action_id": "test",
            "status": "running",
            "calls": {"stable-call": {"status": "started"}},
        }
        cycle = SelfCodeCycleV2.__new__(SelfCodeCycleV2)
        cycle.evidence = self.repo_root / "agent" / "self_code_candidates"
        cycle.client = MustNotCallClient()
        cycle._state = lambda: state
        cycle._save = lambda value: self.fail("started calls must fail before state mutation")
        with self.assertRaisesRegex(RuntimeError, "cannot be repeated"):
            cycle._call(
                call_id="stable-call",
                system="system",
                prompt="prompt",
                schema={},
                num_predict=1,
                seed=1,
                capability={"effective_context_tokens": 1024},
            )


if __name__ == "__main__":
    unittest.main()
