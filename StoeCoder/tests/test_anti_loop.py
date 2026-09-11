import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anti_loop import install_anti_loop


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
        return {"ok": True, "kind": request["kind"], "path": request.get("path", "")}


class AntiLoopTests(unittest.TestCase):
    def runtime(self):
        coder = DummyCoder()
        install_anti_loop(coder)
        return coder

    def test_duplicate_inspect_rejected_without_reexecution(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        req = {"kind": "inspect", "path": "StoeCoder/README.md"}
        self.assertTrue(coder._execute_tool("TASK_x", 1, root, req, None)["ok"])
        second = coder._execute_tool("TASK_x", 2, root, req, None)
        self.assertFalse(second["ok"])
        self.assertFalse(second["executed"])
        self.assertEqual(len(coder.calls), 1)
        self.assertIn("duplicate read-only action rejected", second["error"])

    def test_second_duplicate_after_rejection_fails_closed(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        req = {"kind": "inspect", "path": "StoeCoder/README.md"}
        coder._execute_tool("TASK_x", 1, root, req, None)
        coder._execute_tool("TASK_x", 2, root, req, None)
        with self.assertRaisesRegex(RuntimeError, "repeated identical read-only action"):
            coder._execute_tool("TASK_x", 3, root, req, None)
        self.assertEqual(len(coder.calls), 1)

    def test_three_distinct_explorations_allowed_then_fourth_rejected(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        for step, path in enumerate(("a", "b", "c"), 1):
            result = coder._execute_tool("TASK_x", step, root, {"kind": "inspect", "path": path}, None)
            self.assertTrue(result["ok"])
        result = coder._execute_tool("TASK_x", 4, root, {"kind": "inspect", "path": "d"}, None)
        self.assertFalse(result["ok"])
        self.assertIn("consecutive exploration limit reached", result["error"])
        self.assertEqual(len(coder.calls), 3)

    def test_progress_action_resets_exploration_budget(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        for step, path in enumerate(("a", "b", "c"), 1):
            coder._execute_tool("TASK_x", step, root, {"kind": "inspect", "path": path}, None)
        coder._execute_tool("TASK_x", 4, root, {"kind": "run", "command": ["python", "-V"], "cwd": "."}, None)
        result = coder._execute_tool("TASK_x", 5, root, {"kind": "inspect", "path": "d"}, None)
        self.assertTrue(result["ok"])

    def test_search_signature_includes_query_and_path(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        first = {"kind": "search", "path": "StoeCoder", "query": "alpha"}
        second = {"kind": "search", "path": "StoeCoder", "query": "beta"}
        self.assertTrue(coder._execute_tool("TASK_x", 1, root, first, None)["ok"])
        self.assertTrue(coder._execute_tool("TASK_x", 2, root, second, None)["ok"])
        self.assertEqual(len(coder.calls), 2)

    def test_noop_write_is_rejected_and_does_not_reset_read_guard(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        target = root / "README.md"
        target.write_text("same\n", encoding="utf-8", newline="\n")
        inspect = {"kind": "inspect", "path": "README.md"}
        self.assertTrue(coder._execute_tool("TASK_x", 1, root, inspect, None)["ok"])
        write = coder._execute_tool("TASK_x", 2, root, {"kind": "write", "path": "README.md", "content": "same\n"}, None)
        self.assertFalse(write["ok"])
        self.assertFalse(write["executed"])
        self.assertFalse(write["candidate_changed"])
        self.assertIn("no-op write rejected", write["error"])
        repeated = coder._execute_tool("TASK_x", 3, root, inspect, None)
        self.assertFalse(repeated["ok"])
        self.assertIn("duplicate read-only action rejected", repeated["error"])
        self.assertEqual(len(coder.calls), 1)

    def test_guard_failure_preserves_candidate_diff_stats(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        target = root / "sample.txt"
        target.write_text("one\n", encoding="utf-8", newline="\n")
        subprocess.run(["git", "add", "sample.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=root, check=True, capture_output=True)
        target.write_text("two\n", encoding="utf-8", newline="\n")
        coder._task_evidence = types.SimpleNamespace(files=[], additions=0, deletions=0, binary_files=0)
        req = {"kind": "inspect", "path": "sample.txt"}
        coder._execute_tool("TASK_x", 1, root, req, None)
        coder._execute_tool("TASK_x", 2, root, req, None)
        with self.assertRaisesRegex(RuntimeError, "repeated identical read-only action"):
            coder._execute_tool("TASK_x", 3, root, req, None)
        self.assertEqual(["sample.txt"], coder._task_evidence.files)
        self.assertEqual(1, coder._task_evidence.additions)
        self.assertEqual(1, coder._task_evidence.deletions)


if __name__ == "__main__":
    unittest.main()
