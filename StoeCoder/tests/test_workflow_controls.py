import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow_controls import compact_observation, install_workflow_controls, workflow_state


class DummyCoder:
    def __init__(self):
        self.generated = []
        self._stoe_workflow_state = {}

    def _worker_observation(self, history):
        return history[-6:]

    def _generate_role(self, *, action_id, role, prompt, **kwargs):
        self.generated.append({"action_id": action_id, "role": role, "prompt": prompt, "kwargs": kwargs})
        return {"kind": "finish"}, {"model": "dummy", "action_id": action_id}


class WorkflowControlsTests(unittest.TestCase):
    def test_pre_edit_keeps_only_latest_needed_inspect_content(self):
        history = [
            {"request": {"kind": "inspect", "path": "a.txt"}, "feedback": {"ok": True, "content": "A" * 100, "chars": 100}},
            {"request": {"kind": "inspect", "path": "b.txt"}, "feedback": {"ok": True, "content": "B" * 100, "chars": 100}},
        ]
        visible = compact_observation(history)
        self.assertEqual("pre_edit", visible[0]["workflow_state"]["stage"])
        self.assertNotIn("content", visible[1]["feedback"])
        self.assertTrue(visible[1]["feedback"]["content_omitted"])
        self.assertEqual("B" * 100, visible[2]["feedback"]["content"])

    def test_after_real_write_inspect_content_is_omitted_and_stage_requires_tests_diff_finish(self):
        history = [
            {"request": {"kind": "inspect", "path": "README.md"}, "feedback": {"ok": True, "content": "old", "chars": 3}},
            {"request": {"kind": "write", "path": "README.md"}, "feedback": {"ok": True, "candidate_changed": True, "path": "README.md"}},
        ]
        visible = compact_observation(history)
        state = visible[0]["workflow_state"]
        self.assertEqual("candidate_changed", state["stage"])
        self.assertFalse(state["inspect_same_file_allowed"])
        self.assertEqual("README.md", state["last_changed_path"])
        self.assertEqual(
            ["run relevant deterministic tests", "run git diff for the final candidate", "finish"],
            state["required_next_actions"],
        )
        self.assertNotIn("content", visible[1]["feedback"])
        self.assertTrue(visible[1]["feedback"]["content_omitted"])

    def test_generic_successful_run_does_not_count_as_tests(self):
        history = [
            {"request": {"kind": "write", "path": "README.md"}, "feedback": {"ok": True, "candidate_changed": True, "path": "README.md"}},
            {"request": {"kind": "run", "command": ["python", "-V"]}, "feedback": {"exit_code": 0, "timed_out": False, "cancelled": False, "workflow_run_kind": "other"}},
        ]
        state = workflow_state(history)
        self.assertEqual("candidate_changed", state["stage"])
        self.assertFalse(state["tests_seen_after_last_change"])

    def test_tests_then_diff_advance_state_to_ready_to_finish(self):
        history = [
            {"request": {"kind": "write", "path": "README.md"}, "feedback": {"ok": True, "candidate_changed": True, "path": "README.md"}},
            {"request": {"kind": "run", "command": ["python", "-m", "unittest"]}, "feedback": {"exit_code": 0, "timed_out": False, "cancelled": False, "workflow_run_kind": "tests"}},
            {"request": {"kind": "run", "command": ["git", "diff", "--", "README.md"]}, "feedback": {"exit_code": 0, "timed_out": False, "cancelled": False, "workflow_run_kind": "diff"}},
        ]
        state = workflow_state(history)
        self.assertEqual("ready_to_finish", state["stage"])
        self.assertTrue(state["tests_seen_after_last_change"])
        self.assertTrue(state["diff_seen_after_last_change"])
        self.assertEqual(["finish"], state["required_next_actions"])

    def test_failed_run_allows_evidence_driven_reinspection(self):
        history = [
            {"request": {"kind": "write", "path": "README.md"}, "feedback": {"ok": True, "candidate_changed": True, "path": "README.md"}},
            {"request": {"kind": "run", "command": ["python", "-m", "unittest"]}, "feedback": {"exit_code": 1, "timed_out": False, "cancelled": False, "workflow_run_kind": "tests"}},
        ]
        state = workflow_state(history)
        self.assertEqual("run_failed", state["stage"])
        self.assertTrue(state["inspect_same_file_allowed"])
        self.assertTrue(state["last_run_failed"])

    def test_generate_prompt_uses_runtime_state_after_history_window_moves_on(self):
        coder = DummyCoder()
        install_workflow_controls(coder)
        coder._stoe_workflow_state["TASK_x"] = {
            "candidate_changed": True,
            "last_changed_path": "StoeCoder/README.md",
            "tests_run": True,
            "diff_inspected": False,
            "last_run_failed": False,
        }
        prompt = {
            "recent_tool_feedback": [{"workflow_state": workflow_state([])}],
            "available_tools": {"run": "execute argv"},
            "instruction": "old instruction",
        }
        coder._generate_role(action_id="TASK_x:coder:9", role="coder", prompt=prompt, schema={}, output_tokens=10, seed=1)
        sent = coder.generated[-1]["prompt"]
        self.assertEqual("tests_passed", sent["workflow_state"]["stage"])
        self.assertFalse(sent["workflow_state"]["inspect_same_file_allowed"])
        self.assertEqual(
            ["git", "diff", "--", "StoeCoder/README.md"],
            sent["workflow_state"]["required_next_command"],
        )
        self.assertIn("Do not re-inspect", sent["instruction"])
        self.assertIn("git diff", sent["available_tools"]["run"])
        self.assertEqual("tests_passed", sent["recent_tool_feedback"][0]["workflow_state"]["stage"])

    def test_generate_prompt_after_diff_directs_finish(self):
        coder = DummyCoder()
        install_workflow_controls(coder)
        coder._stoe_workflow_state["TASK_x"] = {
            "candidate_changed": True,
            "last_changed_path": "README.md",
            "tests_run": True,
            "diff_inspected": True,
            "last_run_failed": False,
        }
        prompt = {"recent_tool_feedback": [], "available_tools": {"run": "execute argv"}}
        coder._generate_role(action_id="TASK_x:coder:7", role="coder", prompt=prompt, schema={}, output_tokens=10, seed=1)
        sent = coder.generated[-1]["prompt"]
        self.assertEqual("ready_to_finish", sent["workflow_state"]["stage"])
        self.assertIn("choose finish now", sent["instruction"])


if __name__ == "__main__":
    unittest.main()
