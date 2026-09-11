import tempfile
import types
import unittest
from pathlib import Path

from anti_loop import install_anti_loop


class DummyCoder:
    def __init__(self):
        self.calls = []
        self.events = []

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


if __name__ == "__main__":
    unittest.main()
