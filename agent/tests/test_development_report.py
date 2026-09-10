from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.development_report import render_retrieved_context  # noqa: E402


class DevelopmentReportTests(unittest.TestCase):
    def test_canonical_payload_is_once_and_every_connection_survives(self):
        items = [
            {"ref": "A", "origin": "evaluation", "kind": "result", "outcome": "failed", "path": "A->X", "content": "same", "payload_sha256": "a" * 64},
            {"ref": "B", "origin": "failure_history", "kind": "correction", "outcome": "supported", "path": "B->Y", "content": "same", "payload_sha256": "a" * 64},
        ]
        before = copy.deepcopy(items)
        observed = render_retrieved_context(items, 4000)
        self.assertEqual(1, observed.count(" | same"))
        self.assertIn("CONNECTION | A | evaluation | result | failed | A->X", observed)
        self.assertIn("CONNECTION | B | failure_history | correction | supported | B->Y", observed)
        self.assertIn("canonical_payload_count=1", observed)
        self.assertIn("collapsed_duplicate_count=1", observed)
        self.assertEqual(before, items)

    def test_unhashed_records_are_distinct_and_budget_is_bounded(self):
        items = [
            {"ref": "U1", "content": "same"},
            {"ref": "U2", "content": "same"},
        ]
        observed = render_retrieved_context(items, 4000)
        self.assertEqual(2, observed.count(" | same"))
        self.assertIn("canonical_payload_count=2", observed)
        self.assertIn("collapsed_duplicate_count=0", observed)
        self.assertLessEqual(len(render_retrieved_context(items, 80)), 80)
        with self.assertRaises(ValueError):
            render_retrieved_context(items, -1)


if __name__ == "__main__":
    unittest.main()
