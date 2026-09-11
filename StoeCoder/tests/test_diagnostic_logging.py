import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diagnostic_logging import _failure_class, _redact_tail, install_diagnostic_logging


class DummyCoder:
    def __init__(self):
        self.artifact_root = Path(tempfile.mkdtemp())
        self.events = []
        self._task_evidence = SimpleNamespace(selected_roles=[
            {"name": "coder", "resolved_model": "qwen3-coder:latest"},
            {"name": "reviewer", "resolved_model": "gemma4:26b"},
        ])

    def _event(self, source, message, level="info", **metadata):
        self.events.append({"source": source, "message": message, "level": level, "metadata": metadata})
        return "evt"

    def _generate_role(self, *, role, **kwargs):
        return {"kind": "inspect", "path": "README.md"}, {
            "model": "qwen3-coder:latest", "digest": "d" * 64,
            "duration_seconds": 0.25, "prompt_tokens": 100, "output_tokens": 20,
        }

    def _execute_tool(self, task_id, step, worktree, request, allowed_paths):
        if request["kind"] == "inspect":
            return {"ok": True, "path": request.get("path"), "chars": 1234, "truncated": False}
        if request["kind"] == "run":
            return {"exit_code": 1, "duration_seconds": 0.5, "stderr": "token=abc123 failure", "stdout": "", "timed_out": False, "cancelled": False}
        return {"ok": True}

    def _verification_commands(self, touched):
        return [["git", "diff", "--check"]]

    def _verify_candidate(self, task_id, workspace, touched):
        return []

    def _review(self, task_id, objective, diff, tests, metrics):
        return {"verdict": "reject", "summary": "bad candidate", "defects": ["wrong file"]}

    def _integrate(self, task_id, parent_head, candidate_root, touched):
        return None

    def _rollback(self, parent_head, touched):
        return None

    def _task_main(self, task_id, objective, commit_requested, push_requested, allowed_paths):
        return None

    def _load_state(self):
        return {"task_report": {"outcome": "failure", "failure_condition": "deterministic verification failed: x"}}


class DiagnosticLoggingTests(unittest.TestCase):
    def test_failure_classification(self):
        self.assertEqual(_failure_class("deterministic verification failed: x"), "verification_failed")
        self.assertEqual(_failure_class("independent reviewer rejected candidate: x"), "review_rejected")
        self.assertEqual(_failure_class("coder repeated identical read-only action after trusted rejection"), "action_loop")

    def test_redacts_sensitive_tail(self):
        rendered = _redact_tail("line\ntoken=abc123 failure\npassword=hunter2")
        self.assertNotIn("abc123", rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertIn("token=<redacted>", rendered)

    def test_model_call_logs_tokens_and_model(self):
        coder = DummyCoder()
        install_diagnostic_logging(coder)
        coder._generate_role(role="coder", action_id="TASK_x:coder:1", prompt={}, schema={}, output_tokens=10, seed=1)
        event = coder.events[-1]
        self.assertEqual(event["source"], "Coder[qwen3-coder:latest]")
        self.assertIn("100→20 tokens", event["message"])

    def test_inspect_result_is_logged_without_content(self):
        coder = DummyCoder()
        install_diagnostic_logging(coder)
        coder._execute_tool("TASK_x", 1, Path("."), {"kind": "inspect", "path": "README.md"}, None)
        event = coder.events[-1]
        self.assertIn("step 1/14 · inspect result", event["message"])
        self.assertIn("chars=1234", event["message"])
        self.assertNotIn("content", str(event))

    def test_failed_run_output_is_bounded_and_redacted(self):
        coder = DummyCoder()
        install_diagnostic_logging(coder)
        coder._execute_tool("TASK_x", 2, Path("."), {"kind": "run", "command": ["python", "x.py"], "cwd": "."}, None)
        event = coder.events[-1]
        self.assertIn("exit=1", event["message"])
        self.assertIn("token=<redacted>", event["message"])
        self.assertNotIn("abc123", event["message"])

    def test_review_defects_are_visible(self):
        coder = DummyCoder()
        install_diagnostic_logging(coder)
        result = coder._review("TASK_x", "objective", "diff", [], [])
        self.assertEqual(result["verdict"], "reject")
        self.assertTrue(any("defect · wrong file" in event["message"] for event in coder.events))


if __name__ == "__main__":
    unittest.main()
