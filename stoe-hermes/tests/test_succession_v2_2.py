from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_hermes.split_cycle_v2_2 import validate_code_v2_2  # noqa: E402
from stoe_hermes.succession import (  # noqa: E402
    EDITABLE_PATH,
    SuccessionError,
    reconstruct_candidate,
    sha256_bytes,
    validate_candidate_source_v2_2,
    validate_patch_envelope,
)


EXPECTED_CANDIDATE_SHA256 = "fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff"


class ParentRelativeValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = (ROOT / EDITABLE_PATH).read_text(encoding="utf-8")
        cls.parent_sha = sha256_bytes(cls.parent.encode("utf-8"))
        cls.proposal = json.loads(
            (ROOT / "stoe-hermes" / "evidence" / "v2_2" / "v2_1_candidate_patch.json").read_text(encoding="utf-8")
        )
        cls.candidate = reconstruct_candidate(cls.parent, cls.proposal)

    def assert_forbidden(self, candidate: str, node_type: str | None = None):
        pattern = "introduces or changes forbidden syntax"
        if node_type:
            pattern += f": {node_type}"
        with self.assertRaisesRegex(SuccessionError, pattern):
            validate_candidate_source_v2_2(self.parent, candidate)

    def test_exact_v2_1_candidate_is_reproduced_and_inherited_raise_is_accepted(self):
        sealed, candidate, validation = validate_code_v2_2(copy.deepcopy(self.proposal), self.parent, EDITABLE_PATH)
        self.assertEqual(EXPECTED_CANDIDATE_SHA256, sealed["candidate_sha256"])
        self.assertEqual(EXPECTED_CANDIDATE_SHA256, sha256_bytes(candidate.encode("utf-8")))
        self.assertEqual(1, validation["grandfathered_count"])
        evidence = validation["grandfathered_forbidden_nodes"][0]
        self.assertEqual("Raise", evidence["node_type"])
        self.assertEqual("normalized_ast_prefix_and_structural_path", evidence["comparison"])
        self.assertEqual(64, len(evidence["fingerprint"]))

    def test_harmless_formatting_normalizes_but_ast_rewrite_does_not(self):
        formatted = self.candidate.replace("if max_chars < 0:", "if (max_chars < 0):", 1)
        self.assertEqual(1, validate_candidate_source_v2_2(self.parent, formatted)["grandfathered_count"])
        rewritten = self.candidate.replace("if max_chars < 0:", "if 0 > max_chars:", 1)
        self.assert_forbidden(rewritten, "Raise")

    def test_second_raise_is_rejected(self):
        changed = self.candidate.replace(
            '        raise ValueError("max_chars must be non-negative")',
            '        raise ValueError("max_chars must be non-negative")\n        raise ValueError("max_chars must be non-negative")',
            1,
        )
        self.assert_forbidden(changed, "Raise")

    def test_modified_inherited_raise_is_rejected(self):
        changed = self.candidate.replace("max_chars must be non-negative", "negative budget", 1)
        self.assert_forbidden(changed, "Raise")

    def test_changed_exception_type_is_rejected(self):
        changed = self.candidate.replace("raise ValueError", "raise RuntimeError", 1)
        self.assert_forbidden(changed, "Raise")

    def test_changed_guard_is_rejected(self):
        changed = self.candidate.replace("if max_chars < 0:", "if max_chars <= 0:", 1)
        self.assert_forbidden(changed, "Raise")

    def test_new_prior_state_that_controls_guard_is_rejected(self):
        changed = self.candidate.replace("    if max_chars < 0:\n", "    max_chars = -1\n    if max_chars < 0:\n", 1)
        self.assert_forbidden(changed, "Raise")

    def test_relocated_raise_is_rejected(self):
        block = '    if max_chars < 0:\n        raise ValueError("max_chars must be non-negative")\n'
        changed = self.candidate.replace(block, "", 1)
        changed = changed.replace("    collapsed = 0\n", "    collapsed = 0\n" + block, 1)
        self.assert_forbidden(changed, "Raise")

    def test_duplicate_surrounding_block_is_rejected(self):
        block = '    if max_chars < 0:\n        raise ValueError("max_chars must be non-negative")\n'
        changed = self.candidate.replace(block, block + block, 1)
        self.assert_forbidden(changed, "Raise")

    def test_equivalent_raise_in_new_branch_is_rejected(self):
        insertion = '    if max_chars == 0:\n        raise ValueError("max_chars must be non-negative")\n'
        changed = self.candidate.replace("    logical_lines: list[str] = []\n", insertion + "    logical_lines: list[str] = []\n", 1)
        self.assert_forbidden(changed, "Raise")

    def test_different_forbidden_construct_is_rejected(self):
        changed = self.candidate.replace("    logical_lines: list[str] = []\n", "    while False:\n        pass\n    logical_lines: list[str] = []\n", 1)
        self.assert_forbidden(changed, "While")

    def test_import_and_other_authority_checks_remain_rejected(self):
        altered_import = self.candidate.replace("import hashlib\n", "import hashlib\nimport os\n", 1)
        with self.assertRaisesRegex(SuccessionError, "changed imports"):
            validate_candidate_source_v2_2(self.parent, altered_import)
        authority = self.candidate.replace("    logical_lines: list[str] = []\n", "    open('active_release.json')\n    logical_lines: list[str] = []\n", 1)
        with self.assertRaisesRegex(SuccessionError, "capability"):
            validate_candidate_source_v2_2(self.parent, authority)

    def test_malformed_patch_wrong_parent_and_outside_authority_are_rejected(self):
        malformed = copy.deepcopy(self.proposal)
        malformed["replacement_lines"] = ["def broken(:"]
        with self.assertRaises(SuccessionError):
            validate_code_v2_2(malformed, self.parent, EDITABLE_PATH)
        wrong_parent = copy.deepcopy(self.proposal)
        wrong_parent["parent_sha256"] = "0" * 64
        with self.assertRaisesRegex(SuccessionError, "stale parent"):
            validate_code_v2_2(wrong_parent, self.parent, EDITABLE_PATH)
        outside = {key: self.proposal[key] for key in ("format", "version", "path", "parent_sha256", "replacement_lines")}
        outside["path"] = "stoe-hermes/src/stoe_hermes/succession.py"
        with self.assertRaises(SuccessionError):
            validate_patch_envelope(outside, parent_sha256=self.parent_sha)

    def test_v2_2_manifest_tracks_every_committed_qualification_artifact(self):
        manifest = json.loads((ROOT / "stoe-hermes" / "HERMES_AB_V2_2_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(EXPECTED_CANDIDATE_SHA256, manifest["candidate"]["candidate_sha256"])
        self.assertEqual("inactive", manifest["candidate"]["activation"])
        for relative, expected in manifest["files"].items():
            if relative.startswith("agent/runtime/"):
                continue
            path = ROOT / "stoe-hermes" / relative
            self.assertEqual(expected, hashlib.sha256(path.read_bytes()).hexdigest(), relative)


if __name__ == "__main__":
    unittest.main()
