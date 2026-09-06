from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from stoe_agent.research_state import ResearchStateStore
from stoe_agent.token_budget import ContextBudgetExceeded, TokenBudgetManager, TokenEstimator


class ContinuityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent_root = Path(__file__).resolve().parents[1]
        cls.repo_root = cls.agent_root.parent

    def make_root(self, label: str) -> Path:
        root = self.agent_root / f"continuity_test_{label}_{uuid.uuid4().hex}"
        root.mkdir()
        self.addCleanup(self._remove_root, root)
        return root

    def _remove_root(self, root: Path) -> None:
        if root.resolve().parent != self.agent_root.resolve():
            raise RuntimeError("refusing to remove continuity fixture outside agent root")
        shutil.rmtree(root, ignore_errors=True)

    def make_store(self, root: Path, runtime_name: str = "runtime") -> ResearchStateStore:
        return ResearchStateStore(
            runtime_dir=root / runtime_name,
            checkpoint_dir=root / "checkpoints",
            project_root=root,
        )

    def populated_state(self) -> dict:
        state = ResearchStateStore.empty_state()
        state.update(
            {
                "objective": "Continue a synthetic SToE research project.",
                "current_task": "Resume without repeating the completed action.",
                "active_hypothesis": {
                    "claim_type": "hypothesis",
                    "claim": "Compact state can preserve continuity.",
                    "source_refs": ["FULL"],
                },
                "evidence": [
                    {
                        "claim_type": "fact",
                        "kind": "failure",
                        "stance": "failure",
                        "claim": "A semantically distant rejected path remains relevant.",
                        "source_refs": ["FAILURE"],
                    }
                ],
                "author_definitions": [
                    {
                        "claim_type": "author_definition",
                        "claim": "Stopped processes are not continuously active.",
                        "source_refs": ["AUTHOR"],
                    }
                ],
                "corrections": [
                    {
                        "claim_type": "correction",
                        "claim": "Behavioral improvement is not mechanism proof.",
                        "source_refs": ["CORRECTION"],
                    }
                ],
                "decisions": [{"decision": "Keep the result", "reason": "Fixed rule", "source_refs": ["EVAL"]}],
                "unresolved_questions": [
                    {"claim_type": "question", "question": "What failed?", "source_refs": ["FAILURE"]}
                ],
                "versions": {"active": {"version": "v2", "sha256": "a" * 64}, "candidate": None},
                "actions": [
                    {
                        "action_id": "completed:model-call",
                        "description": "Synthetic completed call",
                        "status": "completed",
                        "started_at": "2026-01-01T00:00:00+00:00",
                        "completed_at": "2026-01-01T00:00:01+00:00",
                        "result_refs": ["EVAL"],
                    }
                ],
                "next_executable_step": "Investigate the unresolved failure.",
            }
        )
        return state

    def test_budget_accounts_for_reserves_and_labels_fallback(self):
        manager = TokenBudgetManager(context_limit_tokens=1000, checkpoint_reserve_tokens=100)
        plan = manager.require_plan(
            system="system rules",
            prompt="task " * 100,
            reserved_generation_tokens=200,
            categories={
                "task_context": "task " * 30,
                "retrieved_material": "memory " * 20,
                "tool_results": "result " * 10,
            },
        )
        self.assertTrue(plan["fits"])
        self.assertFalse(plan["estimator"]["exact"])
        self.assertEqual(100, plan["estimated"]["checkpoint_reserve"])
        self.assertGreater(plan["estimated"]["category_attribution"]["tool_results"], 0)
        with self.assertRaises(ContextBudgetExceeded):
            manager.require_plan(
                system="x" * 1000,
                prompt="y" * 2000,
                reserved_generation_tokens=400,
            )

    def test_oversized_tool_output_is_compact_but_exactly_recoverable(self):
        root = self.make_root("tool")
        store = self.make_store(root)
        output = "FULL-OUTPUT\n" + ("0123456789" * 10_000)
        result = store.preserve_tool_output(
            ref="TOOL_BIG",
            output=output,
            summary="Synthetic oversized tool output.",
            preview_tokens=40,
        )
        self.assertTrue(result["truncation"]["full_content_preserved"])
        self.assertLess(len(result["preview"]), len(output))
        self.assertEqual(output, store.load_artifact("TOOL_BIG"))

    def test_compact_context_preserves_failures_corrections_and_source_access(self):
        root = self.make_root("context")
        source = root / "full_source.txt"
        exact = "exact source text\n" * 100
        source.write_text(exact, encoding="utf-8")
        store = self.make_store(root)
        store.save(self.populated_state())
        artifact = store.register_artifact(
            ref="FULL",
            path=source,
            summary="Summary only; not exact source.",
            kind="source",
            provenance="synthetic_fixture",
        )
        self.assertEqual("full_source.txt", artifact["path"])
        context = store.build_resume_context(max_tokens=1200)
        self.assertIn("semantically distant rejected path", context["context"])
        self.assertIn("Behavioral improvement is not mechanism proof", context["context"])
        self.assertIn("summary_is_exact_source", context["context"])
        self.assertNotIn(exact, context["context"])
        self.assertEqual(exact, store.load_artifact("FULL"))
        delta = store.context_delta({"FULL": artifact["sha256"]})
        self.assertEqual(["FULL"], delta["unchanged_refs"])
        self.assertFalse(delta["changed"])

    def test_checkpoint_resumes_in_fresh_process_and_deduplicates_action(self):
        root = self.make_root("resume")
        store = self.make_store(root, "runtime_one")
        store.save(self.populated_state())
        checkpoint = store.checkpoint(reason="synthetic boundary")
        self.assertTrue(checkpoint["created"])

        env = dict(os.environ)
        source_root = str((self.agent_root / "src").resolve())
        env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "stoe_agent.state_worker",
                "--runtime-dir",
                str(root / "runtime_two"),
                "--checkpoint-dir",
                str(root / "checkpoints"),
                "--project-root",
                str(root),
                "--max-tokens",
                "1400",
            ],
            cwd=self.agent_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        resumed = json.loads(completed.stdout)
        self.assertTrue(resumed["ok"])
        self.assertIn("Continue a synthetic SToE research project", resumed["context"])
        second_store = self.make_store(root, "runtime_two")
        duplicate = second_store.begin_action(
            action_id="completed:model-call", description="Must not run twice"
        )
        self.assertTrue(duplicate["duplicate_completed"])
        self.assertFalse(duplicate["started"])
        second_store.begin_action(action_id="interrupted:step", description="Synthetic interrupted step")
        uncertain = second_store.begin_action(
            action_id="interrupted:step", description="Must reconcile before retry"
        )
        self.assertTrue(uncertain["requires_reconciliation"])
        self.assertFalse(uncertain["started"])


if __name__ == "__main__":
    unittest.main()
