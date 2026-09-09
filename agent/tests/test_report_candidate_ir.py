from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.report_candidate_ir import (  # noqa: E402
    CONNECTION_FIELDS, COUNT_FIELDS, FORMAT, render_report_function,
    report_ir_schema, validate_report_ir,
)


class ReportCandidateIRTests(unittest.TestCase):
    def value(self):
        return {"format": FORMAT, "path": "agent/src/stoe_agent/development_report.py", "function": "render_retrieved_context", "parent_function_sha256": "a" * 64, "identity_field": "payload_sha256", "connection_fields": {name: True for name in CONNECTION_FIELDS}, "count_fields": {name: True for name in COUNT_FIELDS}, "unhashed_policy": "distinct", "order_policy": "preserve_input", "budget_policy": "complete_lines"}

    def test_ir_is_exact_and_has_no_code_channel(self):
        schema = report_ir_schema(path=self.value()["path"], function=self.value()["function"], parent_function_sha256="a" * 64)
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("source", schema["properties"])
        self.assertEqual(self.value(), validate_report_ir(self.value(), path=self.value()["path"], function=self.value()["function"], parent_function_sha256="a" * 64))

    def test_ir_rejects_omission_reordering_and_authority_fields(self):
        values = []
        missing = self.value(); missing.pop("path"); values.append(missing)
        omitted = self.value(); omitted["connection_fields"].pop("path"); values.append(omitted)
        authority = self.value(); authority["filesystem"] = True; values.append(authority)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_report_ir(value, path="agent/src/stoe_agent/development_report.py", function="render_retrieved_context", parent_function_sha256="a" * 64)

    def test_renderer_is_fixed_function_only_source(self):
        source = render_report_function(self.value())
        self.assertTrue(source.startswith("def render_retrieved_context"))
        self.assertIn("payload_sha256", source)
        self.assertNotIn("import ", source)


if __name__ == "__main__":
    unittest.main()
