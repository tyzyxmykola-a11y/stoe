from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "agent" / "tools" / "hermes.py"
SPEC = importlib.util.spec_from_file_location("standalone_hermes", SCRIPT)
assert SPEC and SPEC.loader
hermes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hermes)


class StandaloneHermesTests(unittest.TestCase):
    def test_objective_is_bounded_to_documentation_target(self):
        self.assertEqual(hermes.DEFAULT_OBJECTIVE, hermes.validate_objective(hermes.DEFAULT_OBJECTIVE))
        for invalid in ("short", "Modify agent/src/security.py", "Document ../README.md", "Document stoe-hermes/README.md\nforce"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                hermes.validate_objective(invalid)

    def test_patch_validation_is_exact_and_authority_safe(self):
        parent = "a" * 64
        body = ("Hermes uses TaskScope so each model remains bounded. Restart recovery reads stable actions and "
                "SToE Memory. A trusted deterministic executor verifies the inert proposal before applying it. "
                "This separation keeps worker reasoning distinct from repository authority and preserves provenance. "
                "The ordinary terminal process reconstructs its observer, candidate identity, completed actions, and "
                "pending operation before proceeding; every privileged repository operation remains explicit.")
        patch = {"format": "stoe.documentation_append.v1", "path": hermes.TARGET, "parent_sha256": parent, "heading": hermes.HEADING, "body": body}
        self.assertEqual(patch, hermes.validate_patch(patch, parent))
        for mutation in ("force push", "merge to main", "unrestricted"):
            changed = dict(patch); changed["body"] = body + " " + mutation
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                hermes.validate_patch(changed, parent)

    def test_scope_is_single_file_and_preserves_forbidden_authority(self):
        scope = hermes.exact_scope(hermes.DEFAULT_OBJECTIVE, "hermes:standalone-v1:123456789abc")
        self.assertEqual([hermes.TARGET], scope["write_scope"])
        self.assertIn("force_push", scope["forbidden_capabilities"])
        self.assertIn("protected_evaluation", scope["forbidden_capabilities"])


if __name__ == "__main__":
    unittest.main()
