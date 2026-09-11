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
        return {"ok": True, "kind": request["kind"], "path": request.get("path", "")}


class WorkflowGuardFreshStateTests(unittest.TestCase):
    def test_first_inspect_lets_anti_loop_initialize_runtime_state(self):
        coder = DummyCoder()
        install_anti_loop(coder)
        install_workflow_guard(coder)
        root = Path(tempfile.mkdtemp())
        (root / "README.md").write_text("hello\n", encoding="utf-8", newline="\n")

        result = coder._execute_tool(
            "TASK_fresh", 1, root,
            {"kind": "inspect", "path": "README.md"},
            None,
        )

        self.assertTrue(result["ok"])
        state = coder._stoe_workflow_state["TASK_fresh"]
        self.assertEqual(("inspect", "README.md", ""), state["last_read_signature"])
        self.assertEqual(1, state["consecutive_exploration"])
        self.assertEqual(1, len(coder.calls))


if __name__ == "__main__":
    unittest.main()
