from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_hermes.split_cycle import validate_code, validate_plan, validate_review  # noqa: E402
from stoe_hermes.succession import EDITABLE_PATH, SuccessionError, sha256_bytes  # noqa: E402


class SplitCycleV2Tests(unittest.TestCase):
    def test_artifacts_are_bounded_and_role_separated(self):
        path = EDITABLE_PATH
        plan = {
            "format": "stoe.development_plan", "version": 1,
            "observed_limitation": "duplicate payloads", "target_behavior": "one payload and all connections",
            "editable_file": path, "relevant_interfaces": ["render"], "invariants": ["preserve relations"],
            "acceptance_tests": ["one payload"], "risks": ["budget"], "estimated_patch_lines": 2,
        }
        self.assertEqual(plan, validate_plan(plan, path))
        with self.assertRaisesRegex(SuccessionError, "executable"):
            validate_plan(dict(plan, observed_limitation="def escape(): pass"), path)
        review = {
            "format": "stoe.candidate_review", "version": 1, "verdict": "approve",
            "implements_plan": True, "preserves_connections": True, "likely_regressions": [],
            "unnecessary_complexity": "none", "suspicious_or_unrelated": False, "summary": "bounded",
        }
        self.assertEqual(review, validate_review(review))
        parent = (ROOT / path).read_text(encoding="utf-8")
        proposal = {
            "format": "stoe.line_patch", "version": 3, "path": path,
            "parent_sha256": sha256_bytes(parent.encode("utf-8")),
            "replacement_lines": ["def render_retrieved_context(items, max_chars):", "    return str(len(items))[:max_chars]"],
            "rationale": "bounded fixture", "expected_tests": ["syntax"],
        }
        sealed, candidate, validation = validate_code(proposal, parent, path)
        self.assertEqual(validation["candidate_sha256"], sealed["candidate_sha256"])
        self.assertIn("render_retrieved_context", candidate)


if __name__ == "__main__":
    unittest.main()
