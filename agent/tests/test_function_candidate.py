from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.function_candidate import (  # noqa: E402
    FORMAT,
    FunctionCandidateError,
    function_artifact_schema,
    reconstruct_module,
    sha256_text,
    target_function,
    validate_function_artifact,
)


PATH = "agent/src/stoe_agent/development_report.py"
NAME = "render_retrieved_context"
PARENT = "from __future__ import annotations\n\nfrom typing import Any\n\ndef render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:\n    return ''\n"


def artifact(source="def render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:\n    return 'ok'\n"):
    _, parent = target_function(PARENT, NAME)
    return {"format": FORMAT, "path": PATH, "function": NAME, "parent_function_sha256": sha256_text(parent), "replacement_source": source}


class FunctionCandidateTests(unittest.TestCase):
    def test_schema_is_exact_and_parent_bound(self):
        schema = function_artifact_schema(path=PATH, function=NAME, parent_function_sha256="a" * 64)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual({"a" * 64}, set(schema["properties"]["parent_function_sha256"]["enum"]))

    def test_valid_single_function_reconstructs_without_module_changes(self):
        candidate = reconstruct_module(PARENT, artifact(), expected_path=PATH, expected_function=NAME)
        self.assertTrue(candidate.startswith("from __future__ import annotations"))
        self.assertEqual(1, candidate.count("def render_retrieved_context"))
        self.assertIn("return 'ok'", candidate)

    def test_rejects_stale_parent_and_extra_fields(self):
        stale = artifact(); stale["parent_function_sha256"] = "0" * 64
        extra = {**artifact(), "rationale": "hidden channel"}
        for value in (stale, extra):
            with self.subTest(value=value), self.assertRaises(FunctionCandidateError):
                validate_function_artifact(value, expected_path=PATH, expected_function=NAME, parent_source=PARENT)

    def test_rejects_imports_module_code_and_extra_functions(self):
        values = [
            "import os\ndef render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:\n    return ''\n",
            "x = 1\ndef render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:\n    return ''\n",
            "def render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:\n    def hidden():\n        return 1\n    return ''\n",
        ]
        for source in values:
            with self.subTest(source=source), self.assertRaises(FunctionCandidateError):
                validate_function_artifact(artifact(source), expected_path=PATH, expected_function=NAME, parent_source=PARENT)

    def test_rejects_wrong_function_decorator_and_signature(self):
        values = [
            "def other(items: list[dict[str, Any]], max_chars: int) -> str:\n    return ''\n",
            "@staticmethod\ndef render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:\n    return ''\n",
            "def render_retrieved_context(items, max_chars, authority=False):\n    return ''\n",
        ]
        for source in values:
            with self.subTest(source=source), self.assertRaises(FunctionCandidateError):
                validate_function_artifact(artifact(source), expected_path=PATH, expected_function=NAME, parent_source=PARENT)


if __name__ == "__main__":
    unittest.main()
