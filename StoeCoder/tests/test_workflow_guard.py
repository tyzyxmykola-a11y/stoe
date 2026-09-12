import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anti_loop import install_anti_loop
from verification_policy import worker_verification_commands
from workflow_guard import install_workflow_guard


DEFAULT_PATH = "StoeCoder/README.md"


class DummyCoder:
    def __init__(self):
        self.calls = []
        self.events = []
        self._task_evidence = None
        self.fail_next_run = False

    def _event(self, source, message, level="info", **metadata):
        self.events.append((source, message, level, metadata))
        return "evt"

    def _execute_tool(self, task_id, step, worktree, request, allowed_paths):
        self.calls.append((task_id, step, dict(request)))
        kind = request["kind"]
        if kind == "write":
            target = Path(worktree) / request["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(request.get("content", ""), encoding="utf-8", newline="\n")
            return {"ok": True, "kind": kind, "path": request["path"], "bytes": target.stat().st_size}
        if kind == "run":
            failed = self.fail_next_run
            self.fail_next_run = False
            return {
                "ok": not failed,
                "kind": kind,
                "exit_code": 1 if failed else 0,
                "timed_out": False,
                "cancelled": False,
            }
        if kind == "finish":
            return {"ok": True, "kind": kind, "summary": request.get("summary", "")}
        return {"ok": True, "kind": kind, "path": request.get("path", "")}


class WorkflowGuardTests(unittest.TestCase):
    def runtime(self):
        coder = DummyCoder()
        install_anti_loop(coder)
        install_workflow_guard(coder)
        return coder

    @staticmethod
    def write(coder, root, step=1, content="new\n", path=DEFAULT_PATH):
        return coder._execute_tool(
            "TASK_x", step, root,
            {"kind": "write", "path": path, "content": content},
            None,
        )

    @staticmethod
    def run_verification(coder, root, step=2, path=DEFAULT_PATH, fail=False):
        command = worker_verification_commands([path])[0]
        coder.fail_next_run = fail
        return coder._execute_tool(
            "TASK_x", step, root,
            {"kind": "run", "command": command, "cwd": "."},
            None,
        )

    @staticmethod
    def diff(coder, root, step=3, path=DEFAULT_PATH):
        return coder._execute_tool(
            "TASK_x", step, root,
            {"kind": "run", "command": ["git", "diff", "--", path], "cwd": "."},
            None,
        )

    def test_premature_diff_is_rejected_until_verification_passes(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.write(coder, root)

        blocked = self.diff(coder, root, step=2)
        self.assertFalse(blocked["ok"])
        self.assertFalse(blocked["executed"])
        self.assertIn("premature git diff rejected", blocked["error"])
        self.assertEqual(1, len(coder.calls))

        verified = self.run_verification(coder, root, step=3)
        self.assertEqual("tests", verified["workflow_run_kind"])
        self.assertEqual("tests_passed", verified["stage_guard_after"])
        diff = self.diff(coder, root, step=4)
        self.assertEqual("diff", diff["workflow_run_kind"])
        self.assertEqual("diff_inspected", diff["stage_guard_after"])

    def test_stoecoder_change_requires_policy_selected_command(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.write(coder, root)

        wrong = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "run", "command": ["python", "-m", "pytest", "tests/", "-v"], "cwd": "."},
            None,
        )
        self.assertFalse(wrong["ok"])
        self.assertFalse(wrong["executed"])
        self.assertIn("expected exact command", wrong["error"])
        self.assertEqual(1, len(coder.calls))

        expected = worker_verification_commands([DEFAULT_PATH])[0]
        exact = coder._execute_tool(
            "TASK_x", 3, root,
            {"kind": "run", "command": expected, "cwd": "."},
            None,
        )
        self.assertTrue(exact["ok"])
        self.assertEqual("tests", exact["workflow_run_kind"])
        self.assertEqual("tests_passed", exact["stage_guard_after"])

    def test_path_without_worker_suite_advances_directly_to_diff(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.write(coder, root, path="README.md")
        state = coder._stoe_workflow_state["TASK_x"]
        self.assertTrue(state["tests_run"])
        diff = self.diff(coder, root, step=2, path="README.md")
        self.assertTrue(diff["ok"])
        self.assertEqual("diff_inspected", diff["stage_guard_after"])

    def test_after_verification_only_final_diff_run_is_allowed(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.write(coder, root)
        self.run_verification(coder, root)

        repeated = self.run_verification(coder, root, step=3)
        self.assertFalse(repeated["ok"])
        self.assertFalse(repeated["executed"])
        self.assertIn("expected final git diff", repeated["error"])
        self.assertEqual(2, len(coder.calls))

    def test_after_diff_run_is_rejected_and_finish_is_allowed(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.write(coder, root)
        self.run_verification(coder, root)
        self.diff(coder, root)

        blocked = coder._execute_tool(
            "TASK_x", 4, root,
            {"kind": "run", "command": ["python", "-V"], "cwd": "."},
            None,
        )
        self.assertFalse(blocked["ok"])
        self.assertIn("ready to finish", blocked["error"])
        finished = coder._execute_tool("TASK_x", 5, root, {"kind": "finish", "summary": "ready"}, None)
        self.assertTrue(finished["ok"])

    def test_finish_is_rejected_before_verification_and_diff(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.write(coder, root)

        before_verification = coder._execute_tool("TASK_x", 2, root, {"kind": "finish"}, None)
        self.assertFalse(before_verification["ok"])
        self.assertIn("finish rejected before workflow gates", before_verification["error"])
        self.run_verification(coder, root, step=3)
        before_diff = coder._execute_tool("TASK_x", 4, root, {"kind": "finish"}, None)
        self.assertFalse(before_diff["ok"])
        self.assertIn("finish rejected before workflow gates", before_diff["error"])
        self.diff(coder, root, step=5)
        self.assertTrue(coder._execute_tool("TASK_x", 6, root, {"kind": "finish"}, None)["ok"])

    def test_identical_successful_pre_edit_run_without_transition_does_not_count_as_progress(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        search = {"kind": "search", "path": ".", "query": "alpha"}
        self.assertTrue(coder._execute_tool("TASK_x", 1, root, search, None)["ok"])

        run_request = {"kind": "run", "command": ["python", "-V"], "cwd": "."}
        run = coder._execute_tool("TASK_x", 2, root, run_request, None)
        self.assertTrue(run["ok"])
        self.assertFalse(run["workflow_transitioned"])

        repeated_search = coder._execute_tool("TASK_x", 3, root, search, None)
        self.assertFalse(repeated_search["ok"])
        self.assertIn("duplicate read-only action rejected", repeated_search["error"])

        repeated_run = coder._execute_tool("TASK_x", 4, root, run_request, None)
        self.assertFalse(repeated_run["ok"])
        self.assertIn("did not advance workflow state", repeated_run["error"])

    def test_failed_verification_requires_corrective_change_before_retry(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.write(coder, root)
        failed = self.run_verification(coder, root, step=2, fail=True)
        self.assertEqual(1, failed["exit_code"])
        self.assertEqual("run_failed", failed["stage_guard_after"])

        retry = self.run_verification(coder, root, step=3)
        self.assertFalse(retry["ok"])
        self.assertFalse(retry["executed"])
        self.assertIn("verification failure", retry["error"])

        changed = self.write(coder, root, step=4, content="newer\n")
        self.assertTrue(changed["candidate_changed"])
        retried_after_change = self.run_verification(coder, root, step=5, fail=True)
        self.assertEqual(1, retried_after_change["exit_code"])

    def test_second_identical_stage_violation_fails_closed(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.write(coder, root)
        self.diff(coder, root, step=2)
        with self.assertRaisesRegex(RuntimeError, "repeated stage-invalid action"):
            self.diff(coder, root, step=3)


if __name__ == "__main__":
    unittest.main()
