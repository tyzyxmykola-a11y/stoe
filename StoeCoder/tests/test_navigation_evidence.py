import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anti_loop import install_anti_loop
from navigation_evidence import install_navigation_evidence


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
                result = dict(feedback)
                result.setdefault("query", query)
                return result
            return {
                "ok": True, "kind": "search", "executed": True,
                "query": query, "query_mode": "exact", "query_terms": [query],
                "base": request.get("path", "."),
                "matched_file_count": 0, "matched_files": [], "matches": [],
                "stdout": "", "exit_code": 1, "timed_out": False, "cancelled": False,
            }
        if kind == "inspect":
            key = (request.get("path", ""), request.get("query", ""))
            feedback = self.inspect_feedback.get(key)
            if feedback is not None:
                return dict(feedback)
            content = f"content for {request.get('path', '')}"
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
        "query_terms": ["term"],
        "base": "StoeCoder",
        "matched_file_count": len(files),
        "matched_files": list(files),
        "matches": list(matches or []),
        "stdout": "raw compact search",
        "exit_code": 0 if files else 1,
        "timed_out": False,
        "cancelled": False,
    }


class NavigationEvidenceTests(unittest.TestCase):
    def runtime(self):
        coder = DummyCoder()
        install_anti_loop(coder)
        install_navigation_evidence(coder)
        return coder

    def test_search_preserves_all_hits_and_types_their_provenance(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        files = [
            "StoeCoder/roles.py",
            "StoeCoder/tests/test_roles.py",
            "StoeCoder/roles.json",
            "StoeCoder/README.md",
            "agent/runtime/cache.json",
        ]
        coder.search_feedback["role model"] = search_feedback(
            files,
            [
                {"path": "StoeCoder/roles.py", "line": 20, "text": "class RoleRegistry:"},
                {"path": "StoeCoder/tests/test_roles.py", "line": 30, "text": "class RoleTests:"},
            ],
        )

        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": "StoeCoder", "query": "role model"},
            None,
        )

        self.assertEqual(files, result["matched_files"])
        kinds = {item["path"]: item["source_kind"] for item in result["evidence_items"]}
        self.assertEqual("implementation", kinds["StoeCoder/roles.py"])
        self.assertEqual("test", kinds["StoeCoder/tests/test_roles.py"])
        self.assertEqual("config", kinds["StoeCoder/roles.json"])
        self.assertEqual("docs", kinds["StoeCoder/README.md"])
        self.assertEqual("runtime", kinds["agent/runtime/cache.json"])
        self.assertTrue(result["information_gain"])
        self.assertIn("source kinds:", result["evidence_summary"])

    def test_test_only_search_is_useful_evidence_without_becoming_implementation(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder.search_feedback["missing behavior"] = search_feedback(
            ["StoeCoder/tests/test_behavior.py"],
            [{"path": "StoeCoder/tests/test_behavior.py", "line": 10, "text": "expected behavior"}],
        )

        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": "StoeCoder", "query": "missing behavior"},
            None,
        )

        self.assertTrue(result["information_gain"])
        self.assertEqual(["StoeCoder/tests/test_behavior.py"], result["matched_files"])
        self.assertEqual("test", result["evidence_items"][0]["source_kind"])
        self.assertNotIn("implementation files", result["evidence_summary"])

    def test_rephrased_search_returning_same_evidence_is_not_progress(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        feedback = search_feedback(
            ["StoeCoder/roles.py"],
            [{"path": "StoeCoder/roles.py", "line": 20, "text": "manual model selection"}],
        )
        coder.search_feedback["manual generation selection"] = feedback
        coder.search_feedback["selection generation manual"] = feedback

        first = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": "StoeCoder", "query": "manual generation selection"}, None,
        )
        second = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "search", "path": "StoeCoder", "query": "selection generation manual"}, None,
        )

        self.assertTrue(first["information_gain"])
        self.assertFalse(second["information_gain"])
        self.assertEqual(0, second["novel_evidence_count"])
        self.assertEqual(1, coder._stoe_workflow_state["TASK_x"]["consecutive_exploration"])

    def test_negative_anchored_inspect_is_conserved_as_evidence(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder.inspect_feedback[("StoeCoder/core.py", "def missing_handler")] = {
            "ok": False, "kind": "inspect", "executed": True,
            "path": "StoeCoder/core.py", "query": "def missing_handler",
            "anchored": True, "query_mode": "none", "match_count": 0,
            "error": "inspect anchor produced no matching lines",
        }

        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "inspect", "path": "StoeCoder/core.py", "query": "def missing_handler"}, None,
        )

        self.assertTrue(result["information_gain"])
        self.assertEqual("negative", result["evidence_items"][0]["polarity"])
        self.assertEqual("implementation", result["evidence_items"][0]["source_kind"])
        self.assertIn("negative evidence", result["required_next_action"])
        self.assertEqual(0, coder._stoe_workflow_state["TASK_x"]["consecutive_exploration"])

    def test_different_anchors_with_same_content_are_not_new_evidence(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        content = "class Registry:\n    def choose(self):\n        pass\n"
        coder.inspect_feedback[("StoeCoder/roles.py", "Registry")] = {
            "ok": True, "kind": "inspect", "executed": True,
            "path": "StoeCoder/roles.py", "query": "Registry",
            "content": content, "chars": len(content), "truncated": False,
        }
        coder.inspect_feedback[("StoeCoder/roles.py", "choose")] = {
            "ok": True, "kind": "inspect", "executed": True,
            "path": "StoeCoder/roles.py", "query": "choose",
            "content": content, "chars": len(content), "truncated": False,
        }

        first = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "inspect", "path": "StoeCoder/roles.py", "query": "Registry"}, None,
        )
        second = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "inspect", "path": "StoeCoder/roles.py", "query": "choose"}, None,
        )

        self.assertTrue(first["information_gain"])
        self.assertFalse(second["information_gain"])

    def test_mutation_advances_epoch_and_reactivates_prior_evidence(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder.search_feedback["registry"] = search_feedback(["StoeCoder/roles.py"])
        request = {"kind": "search", "path": "StoeCoder", "query": "registry"}

        first = coder._execute_tool("TASK_x", 1, root, request, None)
        mutation = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "write", "path": "StoeCoder/roles.py", "content": "changed"}, None,
        )
        second = coder._execute_tool("TASK_x", 3, root, request, None)

        self.assertTrue(first["information_gain"])
        self.assertTrue(mutation["evidence_state_changed"])
        self.assertEqual(1, mutation["evidence_epoch"])
        self.assertTrue(second["information_gain"])
        self.assertEqual(1, second["evidence_epoch"])

    def test_failed_execution_advances_epoch_and_reactivates_prior_evidence(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder.search_feedback["registry"] = search_feedback(["StoeCoder/roles.py"])
        request = {"kind": "search", "path": "StoeCoder", "query": "registry"}

        self.assertTrue(coder._execute_tool("TASK_x", 1, root, request, None)["information_gain"])
        failed = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "run", "command": ["python", "tool.py"], "fake_exit_code": 1}, None,
        )
        second = coder._execute_tool("TASK_x", 3, root, request, None)

        self.assertTrue(failed["evidence_state_changed"])
        self.assertEqual(1, failed["evidence_epoch"])
        self.assertTrue(second["information_gain"])

    def test_reordered_negative_query_has_same_family_and_is_not_new(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())

        first = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": "StoeCoder", "query": "manual routing policy"}, None,
        )
        second = coder._execute_tool(
            "TASK_x", 2, root,
            {"kind": "search", "path": "StoeCoder", "query": "policy routing manual"}, None,
        )

        self.assertTrue(first["information_gain"])
        self.assertFalse(second["information_gain"])
        self.assertEqual(
            first["evidence_items"][0]["query_family"],
            second["evidence_items"][0]["query_family"],
        )

    def test_prompt_describes_generic_evidence_model_without_task_vocabulary(self):
        coder = self.runtime()
        coder._generate_role(
            role="coder",
            prompt={"available_tools": {"search": "compact search", "inspect": "bounded inspect"}},
            action_id="TASK_x:coder:1",
        )
        tools = coder.generated[-1]["prompt"]["available_tools"]
        joined = tools["search"] + " " + tools["inspect"]
        self.assertIn("typed evidence_items", joined)
        self.assertIn("source_kind is provenance rather than truth", joined)
        self.assertIn("changing query wording", joined)
        self.assertIn("negative observations are conserved", joined)
        self.assertNotIn("embedding", joined.lower())
        self.assertNotIn("is_generation_model", joined)


if __name__ == "__main__":
    unittest.main()
