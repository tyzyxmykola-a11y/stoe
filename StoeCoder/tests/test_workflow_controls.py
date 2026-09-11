import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow_controls import compact_observation, install_workflow_controls, workflow_state


class DummyCoder:
    def __init__(self):
        self.generated = []

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
            {"request": {"kind": "write", "path": "README.md"}, "feedback": {"ok": True, "candidate_changed": True}},
        ]
        visible = compact_observation(history)
        state = visible[0]["workflow_state"]
        self.assertEqual("candidate_changed", state["stage"])
        self.assertFalse(state["inspect_same_file_allowed"])
        self.assertEqual(
            ["run relevant deterministic tests", "run git diff for the final candidate", "finish"],
            state["required_next_actions"],
        )
        self.assertNotIn("content", visible[1]["feedback"])
        self.assertTrue(visible[1]["feedback"]["content_omitted"])

    def test_tests_and_diff_advance_state_to_ready_to_finish(self):
        history = [
            {"request": {"kind": "write", "path": "README.md"}, "feedback": {"ok": True, "candidate_changed": True}},
            {"request": {"kind": "run", "command": ["python", "-m", "unittest"]}, "feedback": {"exit_code": 0, "timed_out": False, "cancelled": False}},
            {"request": {"kind": "run", "command": ["git", "diff", "--", "README.md"]}, "feedback": {"exit_code": 0, "timed_out": False, "cancelled": False}},
        ]
        state = workflow_state(history)
        self.assertEqual("ready_to_finish", state["stage"])
        self.assertTrue(state["tests_seen_after_last_change"])
        self.assertTrue(state["diff_seen_after_last_change"])
        self.assertEqual(["finish"], state["required_next_actions"])

    def test_generate_prompt_becomes_stateful_after_change(self):
        coder = DummyCoder()
        install_workflow_controls(coder)
        history = [
            {"request": {"kind": "inspect", "path": "README.md"}, "feedback": {"ok": True, "content": "old", "chars": 3}},
            {"request": {"kind": "write", "path": "README.md"}, "feedback": {"ok": True, "candidate_changed": True}},
        ]
        observation = coder._worker_observation(history)
        prompt = {
            "recent_tool_feedback": observation,
            "available_tools": {"run": "execute argv"},
            "instruction": "old instruction",
        }
        coder._generate_role(action_id="TASK_x:coder:3", role="coder", prompt=prompt, schema={}, output_tokens=10, seed=1)
        sent = coder.generated[-1]["prompt"]
        self.assertEqual("candidate_changed", sent["workflow_state"]["stage"])
        self.assertFalse(sent["workflow_state"]["inspect_same_file_allowed"])
        self.assertIn("Do not re-inspect", sent["instruction"])
        self.assertIn("git diff", sent["available_tools"]["run"])


if __name__ == "__main__":
    unittest.main()
