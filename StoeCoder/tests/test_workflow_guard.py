import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anti_loop import install_anti_loop
from workflow_guard import install_workflow_guard


class DummyCoder:
    def __init__(self):
        self.calls = []
        self.events = []
        self._task_evidence = None

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
            failed = "--fail" in (request.get("command") or [])
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
    def write(coder, root, step=1, content="new\n"):
        return coder._execute_tool(
            "TASK_x", step, root,
            {"kind": "write", "path": "README.md", "content": content},
            None,
        )

    @staticmethod
    def run_tests(coder, root, step=2, fail=False):
        command = ["python", "-m", "unittest", "discover", "-s", "tests", "-q"]
        if fail:
            command.append("--fail")
        return coder._execute_tool(
            "TASK_x", step, root,
            {"kind": "run", "command": command, "cwd": "."},
            None,
        )

    @staticmethod
    def diff(coder, root, step=3):
        return coder._execute_tool(
            "TASK_x", step, root,
            {"kind": "run", "command": ["git", "diff", "--", "README.md"], "cwd": "."},
            None,
        )

    def test_premature_diff_is_rejected_until_tests_pass(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        (root / "README.md").write_text("old\n", encoding="utf-8", newline="\n")
        self.write(coder, root)

        blocked = self.diff(coder, root, step=2)
        self.assertFalse(blocked["ok"])
        self.assertFalse(blocked["executed"])
        self.assertIn("premature git diff rejected", blocked["error"])
        self.assertEqual(1, len(coder.calls))

        tests = self.run_tests(coder, root, step=3)
        self.assertEqual("tests", tests["workflow_run_kind"])
        self.assertEqual("tests_passed", tests["stage_guard_after"])
        diff = self.diff(coder, root, step=4)
        self.assertEqual("diff", diff["workflow_run_kind"])
        self.assertEqual("diff_inspected", diff["stage_guard_after"])

    def test_after_tests_only_final_diff_run_is_allowed(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        (root / "README.md").write_text("old\n", encoding="utf-8", newline="\n")
        self.write(coder, root)
        self.run_tests(coder, root)

        repeated_tests = self.run_tests(coder, root, step=3)
        self.assertFalse(repeated_tests["ok"])
        self.assertFalse(repeated_tests["executed"])
        self.assertIn("expected final git diff", repeated_tests["error"])
        self.assertEqual(2, len(coder.calls))

    def test_after_diff_run_is_rejected_and_finish_is_allowed(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        (root / "README.md").write_text("old\n", encoding="utf-8", newline="\n")
        self.write(coder, root)
        self.run_tests(coder, root)
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

    def test_finish_is_rejected_before_tests_and_diff(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        (root / "README.md").write_text("old\n", encoding="utf-8", newline="\n")
        self.write(coder, root)

        before_tests = coder._execute_tool("TASK_x", 2, root, {"kind": "finish"}, None)
        self.assertFalse(before_tests["ok"])
        self.assertIn("finish rejected before workflow gates", before_tests["error"])
        self.run_tests(coder, root, step=3)
        before_diff = coder._execute_tool("TASK_x", 4, root, {"kind": "finish"}, None)
        self.assertFalse(before_diff["ok"])
        self.assertIn("finish rejected before workflow gates", before_diff["error"])
        self.diff(coder, root, step=5)
        self.assertTrue(coder._execute_tool("TASK_x", 6, root, {"kind": "finish"}, None)["ok"])

    def test_identical_successful_run_without_transition_does_not_count_as_progress(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        (root / "README.md").write_text("old\n", encoding="utf-8", newline="\n")
        self.write(coder, root)
        search = {"kind": "search", "path": ".", "query": "alpha"}
        self.assertTrue(coder._execute_tool("TASK_x", 2, root, search, None)["ok"])

        run = coder._execute_tool(
            "TASK_x", 3, root,
            {"kind": "run", "command": ["python", "-V"], "cwd": "."},
            None,
        )
        self.assertTrue(run["ok"])
        self.assertFalse(run["workflow_transitioned"])

        repeated_search = coder._execute_tool("TASK_x", 4, root, search, None)
        self.assertFalse(repeated_search["ok"])
        self.assertIn("duplicate read-only action rejected", repeated_search["error"])

        repeated_run = coder._execute_tool(
            "TASK_x", 5, root,
            {"kind": "run", "command": ["python", "-V"], "cwd": "."},
            None,
        )
        self.assertFalse(repeated_run["ok"])
        self.assertIn("did not advance workflow state", repeated_run["error"])

    def test_identical_failed_run_requires_new_candidate_evidence_before_retry(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        (root / "README.md").write_text("old\n", encoding="utf-8", newline="\n")
        self.write(coder, root)
        failed = self.run_tests(coder, root, step=2, fail=True)
        self.assertEqual(1, failed["exit_code"])
        self.assertEqual("run_failed", failed["stage_guard_after"])

        retry = self.run_tests(coder, root, step=3, fail=True)
        self.assertFalse(retry["ok"])
        self.assertFalse(retry["executed"])
        self.assertIn("identical failed run rejected", retry["error"])

        changed = self.write(coder, root, step=4, content="newer\n")
        self.assertTrue(changed["candidate_changed"])
        retried_after_change = self.run_tests(coder, root, step=5, fail=True)
        self.assertEqual(1, retried_after_change["exit_code"])

    def test_second_identical_stage_violation_fails_closed(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        (root / "README.md").write_text("old\n", encoding="utf-8", newline="\n")
        self.write(coder, root)
        self.diff(coder, root, step=2)
        with self.assertRaisesRegex(RuntimeError, "repeated stage-invalid action"):
            self.diff(coder, root, step=3)


if __name__ == "__main__":
    unittest.main()
