import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anti_loop import install_anti_loop
from navigation_evidence import _query_family, install_navigation_evidence


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

    def prime_objective(self, coder, task_id, objective):
        coder._generate_role(
            role="coder",
            prompt={"objective": objective, "available_tools": {}},
            action_id=f"{task_id}:coder:1",
        )

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
            {"kind": "search", "path": "StoeCoder", "query": "role model"}, None,
        )
        self.assertEqual(files, result["matched_files"])
        kinds = {item["path"]: item["source_kind"] for item in result["evidence_items"]}
        self.assertEqual("implementation", kinds["StoeCoder/roles.py"])
        self.assertEqual("test", kinds["StoeCoder/tests/test_roles.py"])
        self.assertEqual("config", kinds["StoeCoder/roles.json"])
        self.assertEqual("docs", kinds["StoeCoder/README.md"])
        self.assertEqual("runtime", kinds["agent/runtime/cache.json"])
        self.assertTrue(result["information_gain"])
        self.assertTrue(result["connected_progress"])
        self.assertIn("source kinds:", result["evidence_summary"])

    def test_test_only_search_is_conserved_without_becoming_implementation(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        coder.search_feedback["missing behavior"] = search_feedback(
            ["StoeCoder/tests/test_behavior.py"],
            [{"path": "StoeCoder/tests/test_behavior.py", "line": 10, "text": "expected behavior"}],
        )
        result = coder._execute_tool(
            "TASK_x", 1, root,
            {"kind": "search", "path": "StoeCoder", "query": "missing behavior"}, None,
        )
        self.assertTrue(result["information_gain"])
        self.assertEqual("test", result["evidence_items"][0]["source_kind"])
        self.assertNotIn("implementation files", result["evidence_summary"])

    def test_rephrased_search_returning_same_evidence_is_not_novel(self):
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
        self.assertFalse(second["connected_progress"])
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
        self.assertIn("negative evidence", result["required_next_action"])

    def test_different_anchors_with_same_content_are_not_new_evidence(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        content = "class Registry:\n    def choose(self):\n        pass\n"
        for query in ("Registry", "choose"):
            coder.inspect_feedback[("StoeCoder/roles.py", query)] = {
                "ok": True, "kind": "inspect", "executed": True,
                "path": "StoeCoder/roles.py", "query": query,
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

    def test_objective_search_opens_and_ranks_candidate_frontier(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        task = "TASK_ui"
        self.prime_objective(coder, task, "Show terminal task_report results in the conversation UI")
        coder.search_feedback["task_report"] = search_feedback(
            ["StoeCoder/stoe_coder.py", "StoeCoder/static/roles.js"],
            [{"path": "StoeCoder/static/roles.js", "line": 70, "text": "const report=state.task_report;"}],
        )
        search = coder._execute_tool(
            task, 1, root,
            {"kind": "search", "path": ".", "query": "task_report"}, None,
        )
        self.assertTrue(search["connected_progress"])
        self.assertEqual("objective_search", search["connection_basis"])
        self.assertEqual("StoeCoder/static/roles.js", search["matched_files"][0])
        self.assertEqual(
            ["StoeCoder/static/roles.js", "StoeCoder/stoe_coder.py"],
            search["connected_frontier"],
        )

        inspect = coder._execute_tool(
            task, 2, root,
            {"kind": "inspect", "path": "StoeCoder/stoe_coder.py"}, None,
        )
        self.assertTrue(inspect["connected_progress"])
        self.assertEqual("connected_path_first_inspect", inspect["connection_basis"])
        self.assertEqual(["StoeCoder/static/roles.js"], inspect["connected_frontier"])

    def test_new_but_ungrounded_anchor_does_not_reset_stagnation(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        task = "TASK_ui"
        self.prime_objective(coder, task, "Show terminal task_report results in the conversation UI")
        coder.search_feedback["task_report"] = search_feedback(
            ["StoeCoder/stoe_coder.py", "StoeCoder/static/roles.js"],
            [{"path": "StoeCoder/static/roles.js", "line": 70, "text": "const report=state.task_report;"}],
        )
        coder._execute_tool(task, 1, root, {"kind": "search", "path": ".", "query": "task_report"}, None)
        coder._execute_tool(task, 2, root, {"kind": "inspect", "path": "StoeCoder/stoe_coder.py"}, None)
        unrelated = coder._execute_tool(
            task, 3, root,
            {"kind": "inspect", "path": "StoeCoder/stoe_coder.py", "query": "def _load_state"}, None,
        )
        self.assertTrue(unrelated["information_gain"])
        self.assertFalse(unrelated["connected_progress"])
        self.assertEqual("ungrounded_anchor", unrelated["connection_basis"])
        self.assertEqual(1, coder._stoe_workflow_state[task]["consecutive_exploration"])
        self.assertIn("StoeCoder/static/roles.js", unrelated["required_next_action"])

    def test_invented_objective_like_symbol_does_not_create_connection(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        task = "TASK_ui"
        self.prime_objective(coder, task, "Append task_report as one SYSTEM message in the conversation UI")
        coder.search_feedback["task_report"] = search_feedback(
            ["StoeCoder/stoe_coder.py", "StoeCoder/static/roles.js"],
            [{"path": "StoeCoder/static/roles.js", "line": 70, "text": "const report=state.task_report;"}],
        )
        coder._execute_tool(task, 1, root, {"kind": "search", "path": ".", "query": "task_report"}, None)
        coder._execute_tool(task, 2, root, {"kind": "inspect", "path": "StoeCoder/stoe_coder.py"}, None)

        invented = coder._execute_tool(
            task, 3, root,
            {"kind": "inspect", "path": "StoeCoder/stoe_coder.py", "query": "def _add_task_report_message"}, None,
        )
        self.assertTrue(invented["information_gain"])
        self.assertFalse(invented["connected_progress"])
        self.assertEqual("ungrounded_anchor", invented["connection_basis"])
        self.assertIn("StoeCoder/static/roles.js", invented["required_next_action"])

        coder.search_feedback["_add_task_report_message"] = search_feedback(["StoeCoder/stoe_coder.py"])
        invented_search = coder._execute_tool(
            task, 4, root,
            {"kind": "search", "path": ".", "query": "_add_task_report_message"}, None,
        )
        self.assertFalse(invented_search["connected_progress"])
        self.assertEqual("ungrounded_search", invented_search["connection_basis"])

    def test_search_excerpt_can_ground_later_anchor(self):
        coder = self.runtime()
        root = Path(tempfile.mkdtemp())
        task = "TASK_ui"
        self.prime_objective(coder, task, "Render task_report in the conversation UI")
        coder.search_feedback["task_report"] = search_feedback(
            ["StoeCoder/static/roles.js"],
            [{"path": "StoeCoder/static/roles.js", "line": 70, "text": "function renderTaskReport(state) {"}],
        )
        coder._execute_tool(task, 1, root, {"kind": "search", "path": ".", "query": "task_report"}, None)
        coder._execute_tool(task, 2, root, {"kind": "inspect", "path": "StoeCoder/static/roles.js"}, None)
        coder.inspect_feedback[("StoeCoder/static/roles.js", "renderTaskReport")] = {
            "ok": True, "kind": "inspect", "executed": True,
            "path": "StoeCoder/static/roles.js", "query": "renderTaskReport",
            "content": "function renderTaskReport(state) { return state.task_report; }",
            "chars": 61, "truncated": False,
        }
        grounded = coder._execute_tool(
            task, 3, root,
            {"kind": "inspect", "path": "StoeCoder/static/roles.js", "query": "renderTaskReport"}, None,
        )
        self.assertTrue(grounded["connected_progress"])
        self.assertEqual("grounded_path_extension", grounded["connection_basis"])

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

    def test_query_family_splits_code_identifiers_and_ignores_word_order(self):
        self.assertEqual(_query_family("task_report handler"), _query_family("handler task report"))
        self.assertEqual(_query_family("manual routing policy"), _query_family("policy-routing_manual"))

    def test_generate_captures_objective_terms_without_rewriting_tools(self):
        coder = self.runtime()
        prompt = {"objective": "Render task_report in conversation UI", "available_tools": {"search": "unchanged"}}
        coder._generate_role(role="coder", prompt=prompt, action_id="TASK_obj:coder:1")
        self.assertIn("task", coder._stoe_evidence_objective_terms["TASK_obj"])
        self.assertIn("report", coder._stoe_evidence_objective_terms["TASK_obj"])
        self.assertEqual("unchanged", coder.generated[-1]["prompt"]["available_tools"]["search"])


if __name__ == "__main__":
    unittest.main()
