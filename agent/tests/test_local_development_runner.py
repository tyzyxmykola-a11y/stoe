from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_development import LocalDevelopmentError  # noqa: E402
from stoe_agent.local_development_runner import LocalDevelopmentRunner  # noqa: E402


DIGEST = "d" * 64
ACTION = "worker:local-development-v2:planner-successor-v1"


class FakeAPI:
    def __init__(self, *, response: bytes | None = None, error: Exception | None = None):
        self.response = response or self.valid_response()
        self.error = error
        self.calls = 0
        self.payload = None

    @staticmethod
    def valid_response() -> bytes:
        control = {
            "status": "success",
            "decision": "Use the smallest existing interface.",
            "evidence": ["The supplied component already exposes the required boundary."],
            "risks": [],
            "next_action": "Generate one bounded candidate.",
        }
        return json.dumps({"done": True, "done_reason": "stop", "response": json.dumps(control), "prompt_eval_count": 240, "eval_count": 58}).encode()

    def json(self, path, payload=None):
        if path == "/api/version":
            return {"version": "0.test"}
        if path == "/api/tags":
            return {"models": [{"name": "fixture:planner", "digest": DIGEST}]}
        raise AssertionError(path)

    def request(self, path, payload=None, *, timeout=None):
        self.calls += 1
        self.payload = payload
        if self.error:
            raise self.error
        return self.response


def run(runner):
    return runner.run_planner(
        action_id=ACTION,
        model="fixture:planner",
        expected_digest=DIGEST,
        goal="Plan one bounded reporting improvement.",
        constraints=["No authority expansion", "Do not write code"],
        context_items=["STOE_REF=IP_ldv2stage000001 OUTCOME=pending CONTENT=Build successor stage runner."],
    )


class LocalDevelopmentRunnerTests(unittest.TestCase):
    def test_one_call_uses_canonical_schema_and_compact_role_context(self):
        with tempfile.TemporaryDirectory() as raw:
            api = FakeAPI()
            result = run(LocalDevelopmentRunner(api=api, artifact_root=Path(raw)))
            self.assertEqual("completed", result["status"])
            self.assertTrue(result["called_model"])
            self.assertEqual(1, api.calls)
            self.assertEqual(False, api.payload["stream"])
            self.assertIs(False, api.payload["think"])
            self.assertEqual(False, api.payload["format"]["additionalProperties"])
            self.assertIn("smallest implementable next step", api.payload["system"])
            self.assertNotIn("ChatGPT is the SToE architect", api.payload["system"])
            self.assertEqual(1200, api.payload["options"]["num_predict"])

    def test_completed_action_replays_without_model_call(self):
        with tempfile.TemporaryDirectory() as raw:
            api = FakeAPI()
            runner = LocalDevelopmentRunner(api=api, artifact_root=Path(raw))
            first = run(runner)
            second = run(runner)
            self.assertFalse(second["called_model"])
            self.assertTrue(second["recovered"])
            self.assertEqual(first["envelope"], second["envelope"])
            self.assertEqual(1, api.calls)

    def test_provider_error_closes_action_uncertain_without_retry(self):
        with tempfile.TemporaryDirectory() as raw:
            api = FakeAPI(error=TimeoutError("fixture"))
            runner = LocalDevelopmentRunner(api=api, artifact_root=Path(raw))
            with self.assertRaisesRegex(LocalDevelopmentError, "uncertain"):
                run(runner)
            with self.assertRaisesRegex(LocalDevelopmentError, "closed"):
                run(runner)
            self.assertEqual(1, api.calls)

    def test_started_action_recovers_preserved_raw_without_model_call(self):
        with tempfile.TemporaryDirectory() as raw:
            api = FakeAPI()
            runner = LocalDevelopmentRunner(api=api, artifact_root=Path(raw))
            run(runner)
            run_dir = next(Path(raw).iterdir())
            manifest_path = run_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "started"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (run_dir / "validated_envelope.json").unlink()
            recovered = run(runner)
            self.assertTrue(recovered["recovered"])
            self.assertFalse(recovered["called_model"])
            self.assertEqual(1, api.calls)

    def test_malformed_response_is_preserved_and_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            api = FakeAPI(response=json.dumps({"done": False, "response": "{}"}).encode())
            runner = LocalDevelopmentRunner(api=api, artifact_root=Path(raw))
            with self.assertRaises(LocalDevelopmentError):
                run(runner)
            run_dir = next(Path(raw).iterdir())
            self.assertTrue((run_dir / "raw_response.json").is_file())
            self.assertEqual("failed", json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["status"])
            with self.assertRaisesRegex(LocalDevelopmentError, "closed"):
                run(runner)
            self.assertEqual(1, api.calls)

    def test_identity_or_prompt_change_cannot_reuse_action(self):
        with tempfile.TemporaryDirectory() as raw:
            api = FakeAPI()
            runner = LocalDevelopmentRunner(api=api, artifact_root=Path(raw))
            run(runner)
            with self.assertRaisesRegex(LocalDevelopmentError, "identity mismatch"):
                runner.run_planner(action_id=ACTION, model="fixture:planner", expected_digest=DIGEST, goal="Different goal", constraints=["No authority expansion"], context_items=["bounded"])
            self.assertEqual(1, api.calls)


if __name__ == "__main__":
    unittest.main()
