from __future__ import annotations

import hashlib
import json
import shutil
import unittest
import uuid
from pathlib import Path

from stoe_agent.ollama import ModelIdentity
from stoe_agent.self_code_cycle import (
    ACTION_ID,
    EDITABLE_PATH,
    MAX_PATCH_BYTES,
    PATCH_FORMAT,
    PATCH_VERSION,
    PatchBoundaryError,
    SelfCodeModificationCycle,
    apply_in_isolated_directory,
    restore_isolated_parent,
    validate_patch_artifact,
)
from stoe_agent.supervisor import RebuildSupervisor, SupervisorConfig


SAFE_SOURCE = '''def render_retrieved_context(items, max_chars):
    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    lines = []
    seen_hashes = set()
    used = 0
    for item in items:
        digest = str(item.get("sha256", ""))
        if digest and digest in seen_hashes:
            continue
        if digest:
            seen_hashes.add(digest)
        line = " | ".join((str(item.get("ref", "unknown")), str(item.get("origin", "unknown")), str(item.get("kind", "unknown")), str(item.get("outcome", "unknown")), str(item.get("content", "")).replace("\\n", " ")))
        addition = line if not lines else "\\n" + line
        if used + len(addition) > max_chars:
            continue
        lines.append(line)
        used += len(addition)
    return "\\n".join(lines)
'''


class FakeModel:
    def identity(self):
        return ModelIdentity("gemma4:26b", "f" * 64, "test")

    def context_capabilities(self):
        return {"advertised_context_tokens": 32768, "source": "test_double"}


class SelfCodeCycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.parent = cls.repo_root / Path(*EDITABLE_PATH.split("/"))

    def setUp(self):
        self.root = self.repo_root / "agent" / f"self_code_test_{uuid.uuid4().hex}"
        self.root.mkdir()

    def tearDown(self):
        if self.root.resolve().parent != (self.repo_root / "agent").resolve():
            raise RuntimeError("refusing unsafe test cleanup")
        shutil.rmtree(self.root, ignore_errors=True)

    def artifact(self, *, source: str = SAFE_SOURCE, path: str = EDITABLE_PATH):
        return {
            "format": PATCH_FORMAT,
            "version": PATCH_VERSION,
            "objective": "Deduplicate identical retrieved artifacts while preserving provenance.",
            "rationale": "Repeated hashes waste the bounded context budget.",
            "file": {
                "path": path,
                "base_sha256": hashlib.sha256(self.parent.read_bytes()).hexdigest(),
                "content": source,
            },
            "expected_effect": "One rendered entry per non-empty content hash.",
            "risks": ["Different references with identical content collapse."],
            "suggested_test_ids": ["duplicate_hash_fixture", "character_budget_fixture"],
        }

    def supervisor(self):
        return RebuildSupervisor(
            SupervisorConfig.defaults(repo_root=self.repo_root, model="unused", runtime_dir=self.root / "runtime"),
            model_client=object(),
        )

    def test_valid_patch_is_inert_and_applies_only_in_isolated_directory(self):
        artifact = self.artifact()
        validation = validate_patch_artifact(artifact, repo_root=self.repo_root)
        before = self.parent.read_bytes()
        isolated = apply_in_isolated_directory(
            artifact, repo_root=self.repo_root, candidate_root=self.root / "candidate"
        )
        self.assertTrue(validation["passed"])
        self.assertEqual(before, self.parent.read_bytes())
        self.assertNotEqual(validation["base_sha256"], isolated["candidate_sha256"])
        self.assertIn("development_report.py", isolated["diff"])

    def test_boundary_rejects_traversal_protected_dependencies_binary_secrets_and_oversize(self):
        attacks = []
        for path in (
            "../agent/src/stoe_agent/development_report.py",
            "agent/src/stoe_agent/supervisor.py",
            "agent/protected_evals/cases.json",
            "pyproject.toml",
            ".git/config",
        ):
            value = self.artifact(path=path)
            attacks.append(value)
        for source in (
            SAFE_SOURCE + "\x00",
            SAFE_SOURCE + '\nPASSWORD = "this-is-a-generated-secret"\n',
            "import os\n" + SAFE_SOURCE,
            "open('cases.json').read()\n" + SAFE_SOURCE,
            "def render_retrieved_context(items, max_chars):\n    return __builtins__['open']('x').read()\n",
            "while True:\n    pass\n" + SAFE_SOURCE,
        ):
            attacks.append(self.artifact(source=source))
        for value in attacks:
            with self.subTest(path=value["file"]["path"], suffix=value["file"]["content"][-30:]):
                with self.assertRaises(PatchBoundaryError):
                    validate_patch_artifact(value, repo_root=self.repo_root)
        huge = self.artifact()
        huge["rationale"] = "x" * MAX_PATCH_BYTES
        with self.assertRaises(PatchBoundaryError):
            validate_patch_artifact(huge, repo_root=self.repo_root)

    def test_parent_hash_mismatch_and_noop_fail_closed(self):
        wrong = self.artifact()
        wrong["file"]["base_sha256"] = "0" * 64
        with self.assertRaisesRegex(PatchBoundaryError, "parent source hash mismatch"):
            validate_patch_artifact(wrong, repo_root=self.repo_root)
        noop = self.artifact(source=self.parent.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(PatchBoundaryError, "import"):
            apply_in_isolated_directory(noop, repo_root=self.repo_root, candidate_root=self.root / "noop")

    def test_interrupted_generation_requires_reconciliation_and_never_calls_model(self):
        supervisor = self.supervisor()
        cycle = SelfCodeModificationCycle(supervisor, model_client=FakeModel())
        cycle._save_state(
            {
                "action_id": ACTION_ID,
                "status": "generation_started",
                "objective": "bounded objective",
                "proposal": None,
            }
        )
        result = cycle.run("bounded objective", allow_generation=True)
        self.assertEqual("RECONCILIATION_REQUIRED", result["decision"])
        self.assertEqual("generation_uncertain", json.loads(cycle.state_path.read_text())["status"])

    def test_rollback_restores_isolated_copy_without_touching_active_source(self):
        candidate_root = self.root / "candidate"
        apply_in_isolated_directory(self.artifact(), repo_root=self.repo_root, candidate_root=candidate_root)
        active_before = self.parent.read_bytes()
        restored = restore_isolated_parent(repo_root=self.repo_root, candidate_root=candidate_root)
        self.assertEqual(restored["expected_sha256"], restored["restored_sha256"])
        self.assertEqual(active_before, self.parent.read_bytes())

    def test_malformed_artifacts_fail_closed(self):
        for value in (None, [], {}, {"format": PATCH_FORMAT}):
            with self.subTest(value=value):
                with self.assertRaises(PatchBoundaryError):
                    validate_patch_artifact(value, repo_root=self.repo_root)


if __name__ == "__main__":
    unittest.main()
