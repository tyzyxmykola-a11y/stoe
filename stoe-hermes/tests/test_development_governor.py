from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_hermes.development_governor import (  # noqa: E402
    ALLOWED_CAPABILITIES, ESCALATION_REASONS, REQUIRED_FORBIDDEN,
    TASK_SCOPE_FORMAT, TaskScopeError, validate_repair_scope, validate_task_scope,
)


def scope(task_id="hermes:governor:test:0001"):
    return {"format": TASK_SCOPE_FORMAT, "task_id": task_id, "parent_refs": ["IP_parent"], "role": "coder", "objective": "Add one bounded documentation section.", "read_scope": ["stoe-hermes/README.md"], "write_scope": ["stoe-hermes/README.md"], "allowed_capabilities": sorted(ALLOWED_CAPABILITIES), "forbidden_capabilities": sorted(REQUIRED_FORBIDDEN), "invariants": ["No authority expansion"], "success_criteria": ["Required section is present"], "resource_budget": {"input_tokens": 3000, "output_tokens": 900, "timeout_seconds": 300}, "recovery_budget": {"planner": 1, "coder": 2, "reviewer": 1}, "escalation_boundary": sorted(ESCALATION_REASONS)}


class TaskScopeTests(unittest.TestCase):
    def test_valid_scope(self):
        self.assertEqual("coder", validate_task_scope(scope())["role"])

    def test_rejects_path_traversal_protected_scope_and_authority(self):
        values = []
        traversal = scope(); traversal["write_scope"] = ["../README.md"]; values.append(traversal)
        protected = scope(); protected["read_scope"] = ["agent/protected_evals/cases.json"]; protected["write_scope"] = protected["read_scope"]; values.append(protected)
        authority = scope(); authority["allowed_capabilities"].append("network"); values.append(authority)
        weakened = scope(); weakened["forbidden_capabilities"].remove("force_push"); values.append(weakened)
        for value in values:
            with self.subTest(value=value), self.assertRaises(TaskScopeError):
                validate_task_scope(value)

    def test_exact_scope_cannot_be_changed_by_worker(self):
        expected = scope()
        changed = scope(); changed["write_scope"] = ["stoe-hermes/README.md", "README.md"]; changed["read_scope"].append("README.md")
        with self.assertRaises(TaskScopeError):
            validate_task_scope(changed, exact=expected)

    def test_repair_must_descend_without_budget_or_scope_expansion(self):
        parent = scope()
        child = scope("hermes:governor:test:0002"); child["parent_refs"] = [parent["task_id"]]; child["resource_budget"]["output_tokens"] = 800
        self.assertEqual(child["task_id"], validate_repair_scope(parent, child)["task_id"])
        child["resource_budget"]["output_tokens"] = 1000
        with self.assertRaises(TaskScopeError):
            validate_repair_scope(parent, child)

    def test_budget_types_fail_closed(self):
        malformed = scope()
        malformed["resource_budget"]["input_tokens"] = "3000"
        with self.assertRaises(TaskScopeError):
            validate_task_scope(malformed)


if __name__ == "__main__":
    unittest.main()
