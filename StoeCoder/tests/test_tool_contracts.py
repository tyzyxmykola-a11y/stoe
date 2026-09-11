import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anti_loop import install_anti_loop
from inspection_navigation import install_inspection_navigation
from navigation_evidence import install_navigation_evidence
from repository_navigation import install_repository_navigation
from tool_contracts import install_tool_contracts


class DummyCoder:
    def __init__(self):
        self.generated = []
        self.events = []
        self._task_evidence = None

    def _event(self, source, message, level="info", **metadata):
        self.events.append((source, message, level, metadata))
        return "evt"

    def _execute_tool(self, task_id, step, worktree, request, allowed_paths):
        return {"ok": True, "kind": request.get("kind"), "executed": True}

    def _generate_role(self, *, role, prompt, **kwargs):
        self.generated.append({"role": role, "prompt": prompt, "kwargs": kwargs})
        return {"kind": "finish"}, {"model": "dummy"}


class ToolContractTests(unittest.TestCase):
    def test_canonical_contract_survives_all_navigation_wrappers(self):
        coder = DummyCoder()
        # This mirrors server installation order. The canonical contract is
        # intentionally installed first/innermost so it is the final writer.
        install_tool_contracts(coder)
        install_repository_navigation(coder)
        install_inspection_navigation(coder)
        install_anti_loop(coder)
        install_navigation_evidence(coder)

        coder._generate_role(
            role="coder",
            prompt={
                "objective": "Change an unrelated UI behavior safely",
                "available_tools": {"search": "base search", "inspect": "base inspect"},
            },
            action_id="TASK_x:coder:1",
        )

        sent = coder.generated[-1]["prompt"]["available_tools"]
        self.assertIn("typed evidence_items", sent["search"])
        self.assertIn("operator objective", sent["search"])
        self.assertIn("changing query wording", sent["search"])
        self.assertIn("negative evidence is conserved", sent["inspect"])
        self.assertIn("do not deepen an unrelated file", sent["inspect"])
        self.assertNotEqual("base search", sent["search"])
        self.assertNotEqual("base inspect", sent["inspect"])

    def test_non_coder_roles_are_not_rewritten(self):
        coder = DummyCoder()
        install_tool_contracts(coder)
        prompt = {"available_tools": {"search": "review search", "inspect": "review inspect"}}
        coder._generate_role(role="reviewer", prompt=prompt, action_id="TASK_x:reviewer:1")
        sent = coder.generated[-1]["prompt"]["available_tools"]
        self.assertEqual("review search", sent["search"])
        self.assertEqual("review inspect", sent["inspect"])


if __name__ == "__main__":
    unittest.main()
