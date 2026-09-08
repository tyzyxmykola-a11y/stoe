from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_hermes.split_cycle_v2_1 import (  # noqa: E402
    FIXED_PLAN,
    MAX_FORMAT_REPAIRS_PER_PLAN_STAGE,
    PLAN_OUTPUT_TOKENS,
    fixed_plan_schema,
    plan_with_one_repair,
    validate_fixed_plan,
)
from stoe_hermes.split_cycle import validate_code  # noqa: E402
from stoe_hermes.succession import EDITABLE_PATH, SuccessionError, sha256_bytes  # noqa: E402


class SplitCycleV21Tests(unittest.TestCase):
    def test_plan_is_only_fixed_identifiers_and_budget_is_1200(self):
        schema = fixed_plan_schema()
        self.assertEqual(1200, PLAN_OUTPUT_TOKENS)
        self.assertEqual(1, MAX_FORMAT_REPAIRS_PER_PLAN_STAGE)
        self.assertEqual(set(FIXED_PLAN), set(schema["required"]))
        self.assertTrue(all(len(prop["enum"]) == 1 for prop in schema["properties"].values()))
        self.assertEqual(FIXED_PLAN, validate_fixed_plan(copy.deepcopy(FIXED_PLAN)))
        with self.assertRaises(SuccessionError):
            validate_fixed_plan(dict(FIXED_PLAN, risk_id="free_form"))

    def test_malformed_parent_autoinjects_exactly_one_child(self):
        calls = []

        def call(call_id, prompt):
            calls.append((call_id, prompt))
            if len(calls) == 1:
                return {"diagnosis": "SCHEMA_NONCOMPLIANCE", "parsed": None}
            return {"diagnosis": "COMPLETE_STRUCTURED_OUTPUT", "parsed": copy.deepcopy(FIXED_PLAN)}

        plan, attempts = plan_with_one_repair(call, primary_id="plan", primary_prompt="objective")
        self.assertEqual(FIXED_PLAN, plan)
        self.assertEqual(2, len(attempts))
        self.assertEqual("plan_repair_1", calls[1][0])
        self.assertIn("PARENT_FAILURE_ID=SCHEMA_NONCOMPLIANCE", calls[1][1])

    def test_second_format_failure_stops_without_third_call(self):
        calls = []

        def call(call_id, prompt):
            calls.append(call_id)
            return {"diagnosis": "OUTPUT_TRUNCATION", "parsed": None}

        with self.assertRaisesRegex(SuccessionError, "after 1 repair"):
            plan_with_one_repair(call, primary_id="plan", primary_prompt="objective")
        self.assertEqual(["plan", "plan_repair_1"], calls)

    def test_transport_failure_does_not_trigger_format_retry(self):
        calls = []

        def call(call_id, prompt):
            calls.append(call_id)
            return {"diagnosis": "INTERRUPTED_STREAM", "parsed": None}

        with self.assertRaisesRegex(SuccessionError, "INTERRUPTED_STREAM"):
            plan_with_one_repair(call, primary_id="plan", primary_prompt="objective")
        self.assertEqual(["plan"], calls)

    def test_current_validator_rejects_parent_inherited_raise(self):
        parent = (ROOT / EDITABLE_PATH).read_text(encoding="utf-8")
        lines = parent.splitlines()
        start = next(index for index, line in enumerate(lines) if line.startswith("def render_retrieved_context("))
        replacement = lines[start:]
        header = next(index for index, line in enumerate(replacement) if "[stoe-memory] payloads=" in line)
        replacement[header] = replacement[header].replace("collapsed={collapsed}", "collapsed={collapsed} canonical_payloads={len(seen_payloads)}")
        proposal = {
            "format": "stoe.line_patch", "version": 3, "path": EDITABLE_PATH,
            "parent_sha256": sha256_bytes(parent.encode("utf-8")),
            "replacement_lines": replacement,
            "rationale": "disclosed inherited-syntax reproduction",
            "expected_tests": ["validator boundary"],
        }
        with self.assertRaisesRegex(SuccessionError, "forbidden syntax: Raise"):
            validate_code(proposal, parent, EDITABLE_PATH)


if __name__ == "__main__":
    unittest.main()
