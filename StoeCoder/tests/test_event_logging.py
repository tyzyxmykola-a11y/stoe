import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_logging import install_event_logging


class FakeEvidence:
    selected_roles = [
        {"name": "coder", "resolved_model": "qwen3-coder:latest"},
        {"name": "reviewer", "resolved_model": "gemma4:26b"},
    ]


class FakeCoder:
    def __init__(self, root):
        self.artifact_root = Path(root)
        self._task_evidence = FakeEvidence()
        self.events = []
        self.state = {"active_action": None}

    def _load_state(self):
        return dict(self.state)

    def _event(self, source, message, level="info", **metadata):
        self.events.append({"source": source, "message": message, "level": level, "metadata": metadata})
        return "event"


class EventLoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.coder = FakeCoder(self.tmp.name)
        install_event_logging(self.coder)

    def tearDown(self):
        self.tmp.cleanup()

    def write_result(self, action_id, value, filename="result.json"):
        directory = self.coder.artifact_root / action_id.replace(":", "_")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_text(json.dumps(value), encoding="utf-8")

    def test_inspect_identifies_real_role_model_and_path(self):
        action_id = "TASK_x:coder:1"
        self.write_result(action_id, {"kind": "inspect", "path": "StoeCoder/static/index.html"})
        self.coder._event("Worker", "inspect requested", action_id=action_id, model="qwen3-coder:latest")
        event = self.coder.events[-1]
        self.assertEqual(event["source"], "Coder[qwen3-coder:latest]")
        self.assertEqual(event["message"], "inspect StoeCoder/static/index.html")
        self.assertEqual(event["metadata"]["kind"], "inspect")

    def test_write_does_not_leak_content(self):
        action_id = "TASK_x:coder:2"
        secret = "do-not-copy-this-content"
        self.write_result(action_id, {"kind": "write", "path": "StoeCoder/example.py", "content": secret})
        self.coder._event("Worker", "write requested", action_id=action_id, model="qwen3-coder:latest")
        rendered = json.dumps(self.coder.events[-1])
        self.assertIn("write StoeCoder/example.py", rendered)
        self.assertNotIn(secret, rendered)

    def test_search_and_run_are_bounded(self):
        action_id = "TASK_x:coder:3"
        self.write_result(action_id, {"kind": "search", "path": "StoeCoder", "query": "x" * 500})
        self.coder._event("Worker", "search requested", action_id=action_id, model="qwen3-coder:latest")
        self.assertLess(len(self.coder.events[-1]["message"]), 400)

        action_id = "TASK_x:coder:4"
        self.write_result(action_id, {"kind": "run", "cwd": "StoeCoder", "command": ["python", "-m", "unittest", "token=very-secret"]})
        self.coder._event("Worker", "run requested", action_id=action_id, model="qwen3-coder:latest")
        rendered = json.dumps(self.coder.events[-1])
        self.assertIn("token=<redacted>", rendered)
        self.assertNotIn("very-secret", rendered)

    def test_reviewer_model_is_visible(self):
        self.coder._event("Reviewer", "accept", model="gemma4:26b")
        self.assertEqual(self.coder.events[-1]["source"], "Reviewer[gemma4:26b]")

    def test_incomplete_response_uses_actual_done_reason(self):
        action_id = "TASK_x:coder:5"
        self.coder.state["active_action"] = action_id
        self.write_result(action_id, {"done_reason": "length"}, filename="raw_response.json")
        self.coder._event("Coder", "local worker response incomplete", task_id="TASK_x")
        event = self.coder.events[-1]
        self.assertEqual(event["source"], "Coder[qwen3-coder:latest]")
        self.assertEqual(event["message"], "response incomplete · done_reason=length")
        self.assertEqual(event["metadata"]["done_reason"], "length")

    def test_install_is_idempotent(self):
        install_event_logging(self.coder)
        self.coder._event("Reviewer", "accept", model="gemma4:26b")
        self.assertEqual(len(self.coder.events), 1)


if __name__ == "__main__":
    unittest.main()
