import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anti_loop import install_anti_loop
from inspection_navigation import install_inspection_navigation
from repository_navigation import install_information_gain_tracking


class DummyCoder:
    def __init__(self):
        self.generated = []
        self.next_result = {"kind": "finish"}
        self.events = []
        self._task_evidence = None

    def _event(self, source, message, level="info", **metadata):
        self.events.append((source, message, level, metadata))
        return "evt"

    def _generate_role(self, *, role, prompt, **kwargs):
        self.generated.append({"role": role, "prompt": prompt, "kwargs": kwargs})
        return dict(self.next_result), {"model": "dummy"}

    def _execute_tool(self, task_id, step, worktree, request, allowed_paths):
        if request["kind"] != "inspect":
            return {"ok": True, "kind": request["kind"]}
        target = Path(worktree) / request.get("path", "")
        if not target.is_file():
            return {"ok": False, "kind": "inspect", "path": request.get("path", ""), "error": "file not found"}
        data = target.read_text(encoding="utf-8", errors="replace")
        return {
            "ok": True,
            "kind": "inspect",
            "path": request["path"],
            "chars": len(data),
            "content": data[:16_000],
            "truncated": len(data) > 16_000,
        }


class InspectionNavigationTests(unittest.TestCase):
    def runtime(self, *, information_gain=False):
        coder = DummyCoder()
        install_inspection_navigation(coder)
        install_anti_loop(coder)
        if information_gain:
            install_information_gain_tracking(coder)
        return coder

    def large_file(self, root: Path) -> Path:
        target = root / "StoeCoder" / "large.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"line_{index} = {index}\n" for index in range(2200)]
        lines[1800] = "def manual_model_selection_eligibility():\n"
        lines[1801] = "    return embedding_model_is_blocked\n"
        target.write_text("".join(lines), encoding="utf-8", newline="\n")
        return target

    def test_truncated_unanchored_inspect_points_to_query_anchor(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.large_file(root)
        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "inspect", "path": "StoeCoder/large.py"},
            None,
        )
        self.assertTrue(result["truncated"])
        self.assertTrue(result["anchor_available"])
        self.assertIn("query", result["required_next_action"])

    def test_anchored_inspect_reads_relevant_window_beyond_prefix(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.large_file(root)
        coder._execute_tool("TASK_x", 1, root, {"kind": "inspect", "path": "StoeCoder/large.py"}, None)
        result = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "inspect", "path": "StoeCoder/large.py", "query": "manual_model_selection_eligibility"},
            None,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["anchored"])
        self.assertEqual("symbol", result["query_mode"])
        self.assertIn("manual_model_selection_eligibility", result["content"])
        self.assertIn(1801, result["match_lines"])
        self.assertLess(result["chars"], 16_001)

    def test_code_signature_anchor_matches_declaration_strongly(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.large_file(root)
        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "inspect", "path": "StoeCoder/large.py", "query": "def manual_model_selection_eligibility(self):"},
            None,
        )
        self.assertTrue(result["ok"])
        self.assertEqual("symbol", result["query_mode"])
        self.assertIn("manual_model_selection_eligibility", result["content"])

    def test_missing_code_symbol_does_not_fall_back_to_generic_def_lines(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.large_file(root)
        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "inspect", "path": "StoeCoder/large.py", "query": "def is_generation_model"},
            None,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("none", result["query_mode"])
        self.assertEqual(0, result["match_count"])
        self.assertIn("anchor is absent", result["required_next_action"])

    def test_natural_language_anchor_falls_back_to_keywords(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.large_file(root)
        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "inspect", "path": "StoeCoder/large.py", "query": "manual model selection eligibility"},
            None,
        )
        self.assertTrue(result["ok"])
        self.assertEqual("keyword_fallback", result["query_mode"])
        self.assertIn("manual_model_selection_eligibility", result["content"])

    def test_different_inspect_anchors_are_distinct_read_actions(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        target = self.large_file(root)
        with target.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("def reviewer_model_selection():\n    pass\n")
        first = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "inspect", "path": "StoeCoder/large.py", "query": "manual_model_selection"},
            None,
        )
        second = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "inspect", "path": "StoeCoder/large.py", "query": "reviewer_model_selection"},
            None,
        )
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])

    def test_repeated_same_anchor_is_rejected(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        self.large_file(root)
        request = {"kind": "inspect", "path": "StoeCoder/large.py", "query": "manual_model_selection"}
        self.assertTrue(coder._execute_tool("TASK_x", 1, root, request, None)["ok"])
        repeated = coder._execute_tool("TASK_x", 2, root, request, None)
        self.assertFalse(repeated["ok"])
        self.assertFalse(repeated["executed"])
        self.assertIn("duplicate read-only action rejected", repeated["error"])

    def test_anchored_windows_create_distinct_information_gain(self):
        coder = self.runtime(information_gain=True)
        root = Path(tempfile.mkdtemp())
        target = self.large_file(root)
        with target.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("def reviewer_model_selection():\n    return generation_model\n")
        first = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "inspect", "path": "StoeCoder/large.py", "query": "manual_model_selection"},
            None,
        )
        second = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "inspect", "path": "StoeCoder/large.py", "query": "reviewer_model_selection"},
            None,
        )
        self.assertTrue(first["information_gain"])
        self.assertTrue(second["information_gain"])
        self.assertEqual(2, second["useful_exploration_count"])

    def test_malformed_search_command_is_canonicalized_to_query(self):
        coder = DummyCoder()
        coder.next_result = {"kind": "search", "command": ["search", "model selection eligibility embedding"]}
        install_inspection_navigation(coder)
        result, _ = coder._generate_role(role="coder", prompt={"available_tools": {}}, action_id="TASK_x:coder:1")
        self.assertEqual("search", result["kind"])
        self.assertEqual("model selection eligibility embedding", result["query"])
        self.assertNotIn("command", result)

    def test_existing_query_is_not_rewritten(self):
        coder = DummyCoder()
        coder.next_result = {"kind": "search", "query": "embedding", "command": ["search", "wrong"]}
        install_inspection_navigation(coder)
        result, _ = coder._generate_role(role="coder", prompt={"available_tools": {}}, action_id="TASK_x:coder:1")
        self.assertEqual("embedding", result["query"])
        self.assertEqual(["search", "wrong"], result["command"])

    def test_prompt_describes_query_addressable_inspect(self):
        coder = DummyCoder()
        install_inspection_navigation(coder)
        coder._generate_role(role="coder", prompt={"available_tools": {}}, action_id="TASK_x:coder:1")
        prompt = coder.generated[-1]["prompt"]
        self.assertIn("optional query", prompt["available_tools"]["inspect"])
        self.assertIn("matching line windows", prompt["available_tools"]["inspect"])
        self.assertIn("require the requested symbol to exist", prompt["available_tools"]["inspect"])


if __name__ == "__main__":
    unittest.main()
