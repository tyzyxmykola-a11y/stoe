import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anti_loop import install_anti_loop
from repository_navigation import (
    _keyword_pattern,
    install_information_gain_tracking,
    install_repository_navigation,
)


class FakeResult:
    def __init__(self, stdout="", *, exit_code=0, stderr=""):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.duration_seconds = 0.01
        self.stdout_artifact = ""
        self.stderr_artifact = ""
        self.timed_out = False
        self.cancelled = False


class FakeRunner:
    def __init__(self):
        self.files_by_query = {}
        self.excerpts_by_query = {}
        self.calls = []

    def run(self, *, action_id, command, cwd, timeout, env=None):
        self.calls.append((action_id, list(command), Path(cwd)))
        marker = command.index("--")
        query = command[marker + 1]
        if "-l" in command:
            files = self.files_by_query.get(query, [])
            return FakeResult("\n".join(files) + ("\n" if files else ""), exit_code=0 if files else 1)
        excerpts = self.excerpts_by_query.get(query, [])
        return FakeResult("\n".join(excerpts) + ("\n" if excerpts else ""), exit_code=0 if excerpts else 1)


class DummyCoder:
    def __init__(self):
        self._runner = FakeRunner()
        self._task_evidence = None
        self.events = []
        self.generated = []
        self.inspect_content = {}
        self.core_calls = []

    def _event(self, source, message, level="info", **metadata):
        self.events.append((source, message, level, metadata))
        return "evt"

    def _generate_role(self, *, role, prompt, **kwargs):
        self.generated.append({"role": role, "prompt": prompt, "kwargs": kwargs})
        return {"kind": "finish"}, {"model": "dummy"}

    def _execute_tool(self, task_id, step, worktree, request, allowed_paths):
        self.core_calls.append((task_id, step, dict(request)))
        kind = request["kind"]
        if kind == "inspect":
            path = request.get("path", "")
            if path == "missing.py":
                return {"ok": False, "error": "file not found", "path": path}
            content = self.inspect_content.get(path, "")
            return {"ok": True, "kind": "inspect", "path": path, "content": content, "chars": len(content)}
        if kind == "run":
            return {"ok": True, "kind": "run", "exit_code": 0, "timed_out": False, "cancelled": False}
        return {"ok": True, "kind": kind, "path": request.get("path", "")}


class RepositoryNavigationTests(unittest.TestCase):
    def runtime(self):
        coder = DummyCoder()
        install_repository_navigation(coder)
        install_anti_loop(coder)
        install_information_gain_tracking(coder)
        return coder

    def test_search_returns_ranked_compact_repository_map(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder._runner.files_by_query["embedding"] = [
            "research/paper.md",
            "StoeCoder/README.md",
            "StoeCoder/static/roles.js",
            "StoeCoder/roles.py",
            "results/archive.json",
        ]
        coder._runner.excerpts_by_query["embedding"] = [
            "StoeCoder/roles.py:20:embedding = model_name.endswith('-embedding')",
            "StoeCoder/static/roles.js:9:const embedding = name.includes('embedding');",
        ]

        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": ".", "query": "embedding"},
            None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual("exact", result["query_mode"])
        self.assertEqual(["StoeCoder/roles.py", "StoeCoder/static/roles.js"], result["matched_files"][:2])
        self.assertLessEqual(len(result["matched_files"]), 12)
        self.assertLessEqual(len(result["matches"]), 16)
        self.assertIn("matched files:", result["stdout"])
        self.assertTrue(result["information_gain"])
        self.assertEqual(0, coder._stoe_workflow_state["TASK_x"]["consecutive_exploration"])

    def test_natural_language_query_falls_back_to_ranked_keyword_coverage(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        query = "model selection manual generation eligibility"
        coder._runner.files_by_query.update({
            "model": ["docs/model.md", "StoeCoder/ui_server.py", "StoeCoder/roles.py"],
            "selection": ["StoeCoder/roles.py"],
            "manual": ["StoeCoder/static/roles.js", "StoeCoder/roles.py"],
            "generation": ["StoeCoder/stoe_coder.py", "StoeCoder/roles.py"],
            "eligibility": ["StoeCoder/roles.py"],
        })
        pattern = _keyword_pattern(["model", "selection", "manual", "generation", "eligibility"])
        coder._runner.excerpts_by_query[pattern] = [
            "StoeCoder/roles.py:44:def resolve(self, requested_roles, chooser):",
            "StoeCoder/static/roles.js:22:manualModelSelect.appendChild(option);",
        ]

        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": ".", "query": query},
            None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual("keyword_fallback", result["query_mode"])
        self.assertEqual(["model", "selection", "manual", "generation", "eligibility"], result["query_terms"])
        self.assertEqual("StoeCoder/roles.py", result["matched_files"][0])
        self.assertIn("keywords: model, selection, manual, generation, eligibility", result["stdout"])
        self.assertTrue(result["information_gain"])

    def test_missing_search_base_falls_back_to_repository_root(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        query = "embedding model"
        coder._runner.files_by_query.update({
            "embedding": ["StoeCoder/roles.py"],
            "model": ["StoeCoder/ui_server.py", "StoeCoder/roles.py"],
        })

        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": "src", "query": query},
            None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual("src", result["base_fallback_from"])
        self.assertEqual(".", result["base"])
        self.assertEqual("StoeCoder/roles.py", result["matched_files"][0])
        self.assertIn("searched repository root instead", result["stdout"])
        self.assertTrue(result["information_gain"])

    def test_new_search_files_reset_stagnation_but_same_files_do_not(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        for query in ("alpha", "beta", "gamma", "delta", "epsilon"):
            coder._runner.files_by_query[query] = ["StoeCoder/roles.py"]
            coder._runner.excerpts_by_query[query] = [f"StoeCoder/roles.py:1:{query}"]

        first = coder._execute_tool("TASK_x", 1, root, {"kind": "search", "path": ".", "query": "alpha"}, None)
        self.assertTrue(first["information_gain"])
        self.assertEqual(0, coder._stoe_workflow_state["TASK_x"]["consecutive_exploration"])

        for step, query, expected in ((2, "beta", 1), (3, "gamma", 2), (4, "delta", 3)):
            result = coder._execute_tool("TASK_x", step, root, {"kind": "search", "path": ".", "query": query}, None)
            self.assertFalse(result["information_gain"])
            self.assertEqual(expected, coder._stoe_workflow_state["TASK_x"]["consecutive_exploration"])

        blocked = coder._execute_tool("TASK_x", 5, root, {"kind": "search", "path": ".", "query": "epsilon"}, None)
        self.assertFalse(blocked["ok"])
        self.assertFalse(blocked["executed"])
        self.assertIn("consecutive exploration limit reached", blocked["error"])

    def test_missing_inspect_is_not_useful_and_new_search_recovers(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        missing = coder._execute_tool("TASK_x", 1, root, {"kind": "inspect", "path": "missing.py"}, None)
        state = coder._stoe_workflow_state["TASK_x"]
        self.assertFalse(missing["information_gain"])
        self.assertEqual(0, missing["useful_exploration_count"])
        self.assertEqual(1, state["consecutive_exploration"])
        self.assertIn("search from repository root", missing["required_next_action"])

        coder._runner.files_by_query["roles"] = ["StoeCoder/roles.py"]
        coder._runner.excerpts_by_query["roles"] = ["StoeCoder/roles.py:1:class RoleRegistry:"]
        search = coder._execute_tool("TASK_x", 2, root, {"kind": "search", "path": ".", "query": "roles"}, None)
        self.assertTrue(search["information_gain"])
        self.assertEqual(1, search["useful_exploration_count"])
        self.assertEqual(0, state["consecutive_exploration"])

    def test_duplicate_rejection_does_not_consume_more_stagnation(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        request = {"kind": "inspect", "path": "missing.py"}
        coder._execute_tool("TASK_x", 1, root, request, None)
        state = coder._stoe_workflow_state["TASK_x"]
        self.assertEqual(1, state["consecutive_exploration"])

        duplicate = coder._execute_tool("TASK_x", 2, root, request, None)
        self.assertFalse(duplicate["ok"])
        self.assertFalse(duplicate["executed"])
        self.assertEqual(1, state["consecutive_exploration"])

    def test_full_inspect_content_is_information_gain(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder._execute_tool("TASK_x", 1, root, {"kind": "inspect", "path": "missing.py"}, None)
        coder.inspect_content["StoeCoder/roles.py"] = "class RoleRegistry:\n    pass\n"
        result = coder._execute_tool("TASK_x", 2, root, {"kind": "inspect", "path": "StoeCoder/roles.py"}, None)
        self.assertTrue(result["information_gain"])
        self.assertEqual(0, coder._stoe_workflow_state["TASK_x"]["consecutive_exploration"])

    def test_coder_prompt_describes_compact_search_contract(self):
        coder = DummyCoder()
        install_repository_navigation(coder)
        prompt = {"available_tools": {"search": "old search description"}}
        coder._generate_role(role="coder", prompt=prompt, action_id="TASK_x:coder:1")
        sent = coder.generated[-1]["prompt"]
        self.assertIn("natural-language multi-term queries", sent["available_tools"]["search"])
        self.assertIn("missing bases fall back to repository root", sent["available_tools"]["search"])
        self.assertIn("matched_files/excerpts", sent["available_tools"]["search"])


if __name__ == "__main__":
    unittest.main()
