import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anti_loop import install_anti_loop
from navigation_evidence import install_navigation_evidence
from repository_navigation import install_information_gain_tracking


class DummyCoder:
    def __init__(self):
        self.events = []
        self.generated = []
        self._task_evidence = None
        self.search_feedback = {}
        self.inspect_feedback = {}

    def _event(self, source, message, level="info", **metadata):
        self.events.append((source, message, level, metadata))
        return "evt"

    def _generate_role(self, *, role, prompt, **kwargs):
        self.generated.append({"role": role, "prompt": prompt, "kwargs": kwargs})
        return {"kind": "finish"}, {"model": "dummy"}

    def _execute_tool(self, task_id, step, worktree, request, allowed_paths):
        kind = request.get("kind")
        if kind == "search":
            query = request.get("query", "")
            feedback = self.search_feedback.get(query)
            if feedback is not None:
                return dict(feedback)
            return {
                "ok": True, "kind": "search", "executed": True,
                "query": query, "query_mode": "exact", "query_terms": [query],
                "matched_file_count": 0, "matched_files": [], "matches": [],
                "stdout": "", "exit_code": 1, "timed_out": False, "cancelled": False,
            }
        if kind == "inspect":
            key = (request.get("path", ""), request.get("query", ""))
            feedback = self.inspect_feedback.get(key)
            if feedback is not None:
                return dict(feedback)
            content = f"content for {request.get('path', '')} {request.get('query', '')}"
            return {
                "ok": True, "kind": "inspect", "executed": True,
                "path": request.get("path", ""), "query": request.get("query", ""),
                "content": content, "chars": len(content), "truncated": False,
            }
        if kind == "write":
            return {
                "ok": True, "kind": "write", "executed": True,
                "path": request.get("path", ""), "candidate_changed": True,
            }
        if kind == "run":
            return {
                "ok": True, "kind": "run", "executed": True,
                "exit_code": int(request.get("fake_exit_code", 0)),
                "timed_out": False, "cancelled": False,
            }
        return {"ok": True, "kind": kind, "executed": True}


def search_feedback(files, matches=None):
    return {
        "ok": True,
        "kind": "search",
        "executed": True,
        "query_mode": "exact",
        "query_terms": ["symbol"],
        "matched_file_count": len(files),
        "matched_files": list(files),
        "matches": list(matches or []),
        "stdout": "raw compact search",
        "exit_code": 0 if files else 1,
        "timed_out": False,
        "cancelled": False,
    }


class NavigationEvidenceTests(unittest.TestCase):
    def runtime(self, *, guarded=False, information_gain=False):
        coder = DummyCoder()
        if guarded:
            install_anti_loop(coder)
        install_navigation_evidence(coder)
        if information_gain:
            install_information_gain_tracking(coder)
        return coder

    def test_test_only_hits_are_not_presented_as_implementation_evidence(self):
        coder = self.runtime(guarded=True, information_gain=True)
        root = Path(tempfile.mkdtemp())
        coder.search_feedback["is_generation_model"] = search_feedback(
            ["StoeCoder/tests/test_inspection_navigation.py"],
            [{"path": "StoeCoder/tests/test_inspection_navigation.py", "line": 100, "text": "def is_generation_model"}],
        )

        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": "StoeCoder", "query": "is_generation_model"},
            None,
        )

        self.assertTrue(result["test_only"])
        self.assertFalse(result["source_evidence"])
        self.assertEqual([], result["matched_files"])
        self.assertEqual(["StoeCoder/tests/test_inspection_navigation.py"], result["test_files"])
        self.assertEqual([], result["matches"])
        self.assertIn("matched only tests", result["stdout"])
        self.assertIn("broader objective/domain terms", result["required_next_action"])
        self.assertFalse(result["information_gain"])

    def test_mixed_source_and_test_hits_keep_source_excerpts_only(self):
        coder = self.runtime()
        coder.search_feedback["embedding"] = search_feedback(
            ["StoeCoder/roles.py", "StoeCoder/tests/test_roles.py"],
            [
                {"path": "StoeCoder/roles.py", "line": 20, "text": "model eligibility"},
                {"path": "StoeCoder/tests/test_roles.py", "line": 30, "text": "fixture"},
            ],
        )

        result = coder._execute_tool(
            "TASK_x", 1, Path(tempfile.mkdtemp()),
            {"kind": "search", "path": "StoeCoder", "query": "embedding"},
            None,
        )

        self.assertTrue(result["source_evidence"])
        self.assertEqual(["StoeCoder/roles.py"], result["implementation_files"])
        self.assertEqual(["StoeCoder/tests/test_roles.py"], result["test_files"])
        self.assertEqual(["StoeCoder/roles.py"], result["matched_files"])
        self.assertEqual(["StoeCoder/roles.py"], [item["path"] for item in result["matches"]])

    def test_failed_strong_anchor_blocks_exact_guessed_symbol_search(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder.inspect_feedback[("StoeCoder/stoe_coder.py", "def is_generation_model")] = {
            "ok": False, "kind": "inspect", "executed": True,
            "path": "StoeCoder/stoe_coder.py", "query": "def is_generation_model",
            "anchored": True, "query_mode": "none", "match_count": 0,
            "error": "inspect anchor produced no matching lines",
        }

        first = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "inspect", "path": "StoeCoder/stoe_coder.py", "query": "def is_generation_model"},
            None,
        )
        blocked = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "search", "path": "StoeCoder", "query": "is_generation_model"},
            None,
        )

        self.assertEqual("is_generation_model", first["absent_symbol"])
        self.assertIn("Do not search the exact guessed symbol", first["required_next_action"])
        self.assertFalse(blocked["ok"])
        self.assertFalse(blocked["executed"])
        self.assertIn("guessed absent symbol rejected", blocked["error"])

    def test_exact_search_replay_is_blocked_after_intervening_read(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder.search_feedback["embedding"] = search_feedback(["StoeCoder/roles.py"])

        first = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": "StoeCoder", "query": "embedding"}, None,
        )
        coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "inspect", "path": "StoeCoder/roles.py"}, None,
        )
        replay = coder._execute_tool(
            "TASK_x", 3, root,
            {"kind": "search", "path": "StoeCoder", "query": "embedding"}, None,
        )

        self.assertTrue(first["ok"])
        self.assertFalse(replay["ok"])
        self.assertFalse(replay["executed"])
        self.assertIn("semantic replay rejected", replay["error"])

    def test_real_mutation_resets_semantic_replay_memory(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder.search_feedback["embedding"] = search_feedback(["StoeCoder/roles.py"])

        request = {"kind": "search", "path": "StoeCoder", "query": "embedding"}
        self.assertTrue(coder._execute_tool("TASK_x", 1, root, request, None)["ok"])
        coder._execute_tool("TASK_x", 2, root, {"kind": "inspect", "path": "StoeCoder/roles.py"}, None)
        coder._execute_tool("TASK_x", 3, root, {"kind": "write", "path": "StoeCoder/roles.py", "content": "x"}, None)
        allowed = coder._execute_tool("TASK_x", 4, root, request, None)

        self.assertTrue(allowed["ok"])

    def test_failed_run_resets_semantic_replay_memory(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder.search_feedback["embedding"] = search_feedback(["StoeCoder/roles.py"])

        request = {"kind": "search", "path": "StoeCoder", "query": "embedding"}
        self.assertTrue(coder._execute_tool("TASK_x", 1, root, request, None)["ok"])
        coder._execute_tool("TASK_x", 2, root, {"kind": "inspect", "path": "StoeCoder/roles.py"}, None)
        coder._execute_tool("TASK_x", 3, root, {"kind": "run", "fake_exit_code": 1}, None)
        allowed = coder._execute_tool("TASK_x", 4, root, request, None)

        self.assertTrue(allowed["ok"])

    def test_prompt_explains_test_only_and_replay_semantics(self):
        coder = self.runtime()
        coder._generate_role(role="coder", prompt={"available_tools": {"search": "compact search"}}, action_id="TASK_x:coder:1")
        search = coder.generated[-1]["prompt"]["available_tools"]["search"]
        self.assertIn("test-only hits are not implementation evidence", search)
        self.assertIn("exact read/search replays remain blocked", search)


if __name__ == "__main__":
    unittest.main()
