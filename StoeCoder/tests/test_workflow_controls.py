import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verification_policy import worker_verification_commands
from workflow_controls import compact_observation, install_workflow_controls, workflow_state


STOECODER_PATH = "StoeCoder/README.md"
STOECODER_VERIFY = worker_verification_commands([STOECODER_PATH])[0]


class DummyCoder:
    def __init__(self):
        self.generated = []
        self._stoe_workflow_state = {}
        self._task_evidence = None

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

    def test_after_stoecoder_write_stage_requires_policy_verification_then_diff(self):
        history = [
            {"request": {"kind": "inspect", "path": STOECODER_PATH}, "feedback": {"ok": True, "content": "old", "chars": 3}},
            {"request": {"kind": "write", "path": STOECODER_PATH}, "feedback": {"ok": True, "candidate_changed": True, "path": STOECODER_PATH}},
        ]
        visible = compact_observation(history)
        state = visible[0]["workflow_state"]
        self.assertEqual("candidate_changed", state["stage"])
        self.assertFalse(state["inspect_same_file_allowed"])
        self.assertEqual(STOECODER_PATH, state["last_changed_path"])
        self.assertEqual(STOECODER_VERIFY, state["required_next_command"])
        self.assertEqual(1, state["verification_total"])
        self.assertNotIn("content", visible[1]["feedback"])
        self.assertTrue(visible[1]["feedback"]["content_omitted"])

    def test_path_without_worker_suite_advances_directly_to_diff(self):
        history = [
            {"request": {"kind": "write", "path": "README.md"}, "feedback": {"ok": True, "candidate_changed": True, "path": "README.md"}},
        ]
        state = workflow_state(history)
        self.assertEqual("tests_passed", state["stage"])
        self.assertTrue(state["tests_seen_after_last_change"])
        self.assertEqual([], state["verification_commands"])
        self.assertEqual(["git", "diff", "--", "README.md"], state["required_next_command"])

    def test_generic_successful_run_does_not_satisfy_policy_verification(self):
        history = [
            {"request": {"kind": "write", "path": STOECODER_PATH}, "feedback": {"ok": True, "candidate_changed": True, "path": STOECODER_PATH}},
            {"request": {"kind": "run", "command": ["python", "-V"]}, "feedback": {"exit_code": 0, "timed_out": False, "cancelled": False, "workflow_run_kind": "other"}},
        ]
        state = workflow_state(history)
        self.assertEqual("candidate_changed", state["stage"])
        self.assertFalse(state["tests_seen_after_last_change"])
        self.assertEqual(STOECODER_VERIFY, state["required_next_command"])

    def test_policy_verification_then_diff_advances_state_to_ready_to_finish(self):
        history = [
            {"request": {"kind": "write", "path": STOECODER_PATH}, "feedback": {"ok": True, "candidate_changed": True, "path": STOECODER_PATH}},
            {"request": {"kind": "run", "command": STOECODER_VERIFY}, "feedback": {"exit_code": 0, "timed_out": False, "cancelled": False, "workflow_run_kind": "tests"}},
            {"request": {"kind": "run", "command": ["git", "diff", "--", STOECODER_PATH]}, "feedback": {"exit_code": 0, "timed_out": False, "cancelled": False, "workflow_run_kind": "diff"}},
        ]
        state = workflow_state(history)
        self.assertEqual("ready_to_finish", state["stage"])
        self.assertTrue(state["tests_seen_after_last_change"])
        self.assertTrue(state["diff_seen_after_last_change"])
        self.assertEqual(["finish"], state["required_next_actions"])

    def test_failed_policy_command_allows_evidence_driven_reinspection(self):
        history = [
            {"request": {"kind": "write", "path": STOECODER_PATH}, "feedback": {"ok": True, "candidate_changed": True, "path": STOECODER_PATH}},
            {"request": {"kind": "run", "command": STOECODER_VERIFY}, "feedback": {"exit_code": 1, "timed_out": False, "cancelled": False, "workflow_run_kind": "tests"}},
        ]
        state = workflow_state(history)
        self.assertEqual("run_failed", state["stage"])
        self.assertTrue(state["inspect_same_file_allowed"])
        self.assertTrue(state["last_run_failed"])

    def test_rejected_run_does_not_create_false_run_failed_state(self):
        history = [
            {"request": {"kind": "write", "path": STOECODER_PATH}, "feedback": {"ok": True, "candidate_changed": True, "path": STOECODER_PATH}},
            {"request": {"kind": "run", "command": ["python", "-m", "pytest"]}, "feedback": {"ok": False, "executed": False, "error": "rejected"}},
        ]
        state = workflow_state(history)
        self.assertEqual("candidate_changed", state["stage"])
        self.assertFalse(state["last_run_failed"])
        self.assertEqual(STOECODER_VERIFY, state["required_next_command"])

    def test_failed_run_keeps_latest_reinspection_content_visible(self):
        history = [
            {"request": {"kind": "write", "path": STOECODER_PATH}, "feedback": {"ok": True, "candidate_changed": True, "path": STOECODER_PATH}},
            {"request": {"kind": "run", "command": STOECODER_VERIFY}, "feedback": {"exit_code": 1, "timed_out": False, "cancelled": False, "workflow_run_kind": "tests"}},
            {"request": {"kind": "inspect", "path": STOECODER_PATH}, "feedback": {"ok": True, "content": "FULL FILE CONTENT", "chars": 17}},
        ]
        visible = compact_observation(history)
        self.assertEqual("run_failed", visible[0]["workflow_state"]["stage"])
        inspect_feedback = visible[-1]["feedback"]
        self.assertEqual("FULL FILE CONTENT", inspect_feedback["content"])
        self.assertNotIn("content_omitted", inspect_feedback)

    def test_generate_prompt_uses_runtime_state_after_history_window_moves_on(self):
        coder = DummyCoder()
        install_workflow_controls(coder)
        coder._stoe_workflow_state["TASK_x"] = {
            "candidate_changed": True,
            "last_changed_path": STOECODER_PATH,
            "verification_commands": [STOECODER_VERIFY],
            "verification_index": 1,
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
            ["git", "diff", "--", STOECODER_PATH],
            sent["workflow_state"]["required_next_command"],
        )
        self.assertIn("Do not re-inspect", sent["instruction"])
        self.assertIn("required_next_command", sent["available_tools"]["run"])
        self.assertEqual("tests_passed", sent["recent_tool_feedback"][0]["workflow_state"]["stage"])

    def test_generate_prompt_candidate_changed_names_policy_selected_command(self):
        coder = DummyCoder()
        install_workflow_controls(coder)
        coder._stoe_workflow_state["TASK_x"] = {
            "candidate_changed": True,
            "last_changed_path": STOECODER_PATH,
            "verification_commands": [STOECODER_VERIFY],
            "verification_index": 0,
            "tests_run": False,
            "diff_inspected": False,
            "last_run_failed": False,
        }
        prompt = {
            "recent_tool_feedback": [{"workflow_state": workflow_state([])}],
            "available_tools": {"run": "execute argv"},
        }
        coder._generate_role(action_id="TASK_x:coder:4", role="coder", prompt=prompt, schema={}, output_tokens=10, seed=1)
        sent = coder.generated[-1]["prompt"]
        self.assertEqual(STOECODER_VERIFY, sent["workflow_state"]["required_next_command"])
        self.assertIn(repr(STOECODER_VERIFY), sent["instruction"])
        self.assertIn("repository policy", sent["available_tools"]["run"])

    def test_generate_prompt_after_diff_directs_finish(self):
        coder = DummyCoder()
        install_workflow_controls(coder)
        coder._stoe_workflow_state["TASK_x"] = {
            "candidate_changed": True,
            "last_changed_path": STOECODER_PATH,
            "verification_commands": [STOECODER_VERIFY],
            "verification_index": 1,
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
