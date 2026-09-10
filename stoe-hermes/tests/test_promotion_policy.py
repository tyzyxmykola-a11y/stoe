from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_hermes.promotion import ApprovedRelease, StandingPolicySupervisor, resolve_active_renderer  # noqa: E402
from stoe_hermes.succession import EDITABLE_PATH, SuccessionError, sha256_bytes  # noqa: E402


class StandingPromotionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pointer = self.root / "releases" / "active.json"
        self.pointer.parent.mkdir()
        self.pointer.write_text('{"release_id":"A","environment_fingerprint":"a"}\n', encoding="utf-8")
        self.source = self.root / "context_renderer.py"
        self.parent = b"def render_retrieved_context(items, max_chars):\n    return 'parent'\n"
        self.candidate_source = b"def render_retrieved_context(items, max_chars):\n    return 'candidate'\n"
        self.source.write_bytes(self.parent)
        self.rollback = self.root / "releases" / "A" / "context_renderer.py"
        self.rollback.parent.mkdir()
        self.rollback.write_bytes(self.parent)
        self.artifact = self.root / "releases" / "B" / "context_renderer.py"
        self.artifact.parent.mkdir()
        self.artifact.write_bytes(self.candidate_source)
        self.policy = json.loads((ROOT / "stoe-hermes" / "policies" / "bounded_succession_v1.json").read_text(encoding="utf-8"))
        self.policy["status"] = "active"
        self.record = ApprovedRelease(
            release_id="B",
            parent_release="A",
            hermes_commit="b" * 40,
            hermes_version="0.20.3",
            integration_plugin_version="0.1.0",
            model_configuration={},
            configuration_hash="c" * 64,
            environment_fingerprint="d" * 64,
            candidate_status="approved",
            rollback_target="A",
            editable_path=EDITABLE_PATH,
            parent_source_sha256=sha256_bytes(self.parent),
            candidate_source_sha256=sha256_bytes(self.candidate_source),
            candidate_artifact="releases/B/context_renderer.py",
            authorization_policy_id=self.policy["policy_id"],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def qualification(self) -> dict:
        return {
            "editable_path": EDITABLE_PATH,
            "parent_source_sha256": sha256_bytes(self.parent),
            "candidate_source_sha256": sha256_bytes(self.candidate_source),
            "protected_validation_passed": True,
            "protected_evaluation_passed": True,
            "authority_expansion": False,
            "rollback_available": True,
        }

    def activate(self, health: bool = True) -> dict:
        return StandingPolicySupervisor(self.pointer).activate(
            self.record,
            policy=self.policy,
            qualification=self.qualification(),
            source_path=self.source,
            candidate_source=self.candidate_source,
            rollback_source_path=self.rollback,
            health_check=lambda: health,
        )

    def test_exact_qualified_successor_is_activated(self):
        result = self.activate()
        self.assertEqual("active", result["status"])
        self.assertEqual(self.parent, self.source.read_bytes())
        self.assertEqual("B", json.loads(self.pointer.read_text())["release_id"])
        self.assertEqual("A", result["rollback_target"])
        self.assertEqual("candidate", resolve_active_renderer(self.pointer)([], 100))

    def test_failed_health_restores_source_and_pointer(self):
        before = self.pointer.read_bytes()
        result = self.activate(health=False)
        self.assertEqual("rolled_back", result["status"])
        self.assertEqual(self.parent, self.source.read_bytes())
        self.assertEqual(before, self.pointer.read_bytes())

    def test_artifact_traversal_and_hash_mismatch_fail_closed(self):
        self.record.candidate_artifact = "../outside.py"
        with self.assertRaisesRegex(SuccessionError, "release store"):
            self.activate()
        self.record.candidate_artifact = "releases/B/context_renderer.py"
        self.artifact.write_bytes(b"changed\n")
        with self.assertRaisesRegex(SuccessionError, "artifact bytes"):
            self.activate()

    def test_authority_expansion_fails_closed(self):
        qualification = self.qualification()
        qualification["authority_expansion"] = True
        with self.assertRaisesRegex(SuccessionError, "qualification"):
            StandingPolicySupervisor(self.pointer).activate(
                self.record, policy=self.policy, qualification=qualification,
                source_path=self.source, candidate_source=self.candidate_source,
                rollback_source_path=self.rollback, health_check=lambda: True,
            )
        self.assertEqual(self.parent, self.source.read_bytes())

    def test_identity_and_policy_changes_fail_closed(self):
        self.record.candidate_source_sha256 = "0" * 64
        with self.assertRaisesRegex(SuccessionError, "candidate source identity"):
            self.activate()
        self.record.candidate_source_sha256 = sha256_bytes(self.candidate_source)
        self.policy["allowed_editable_paths"] = ["broader.py"]
        with self.assertRaisesRegex(SuccessionError, "editable boundary"):
            self.activate()


if __name__ == "__main__":
    unittest.main()
