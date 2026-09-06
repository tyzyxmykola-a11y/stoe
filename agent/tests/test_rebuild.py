from __future__ import annotations

import json
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from stoe_agent.ollama import ModelIdentity
from stoe_agent.selector_loader import load_selector
from stoe_agent.static_gate import validate_candidate_source
from stoe_agent.supervisor import RebuildSupervisor, SupervisorConfig


IMPROVED_SOURCE = r'''from __future__ import annotations

import re


def _tokens(value):
    return {token for token in re.findall(r"[a-z0-9]+", str(value).lower()) if len(token) > 2}


def _joined(values):
    return " ".join(str(value) for value in (values or []))


def _similarity(left, right):
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / (len(a | b) ** 0.5)


def select_context(observer_state, items, max_items, max_chars):
    goal = str(observer_state.get("goal", ""))
    evidence = _joined(observer_state.get("evidence", []))
    questions = _joined(observer_state.get("open_questions", []))
    active = _joined(observer_state.get("active_constraints", []))
    changed = _joined(observer_state.get("changed_constraints", []))
    query = " ".join((goal, evidence, questions, active, changed))
    failed = {"failed", "failure", "rejected"}
    ranked = []
    for item in items:
        content = str(item.get("content", ""))
        condition = str(item.get("failure_condition", ""))
        score = _similarity(query, content)
        if item.get("origin") == "evaluation" and item.get("outcome") == "supported":
            score += 0.55 + 0.15 * _similarity("measured observed evaluation evidence", content)
        is_failure = item.get("origin") == "failure_history" or str(item.get("outcome", "")).lower() in failed
        if is_failure:
            changed_match = _similarity(changed, condition)
            active_match = _similarity(active, condition)
            if changed_match > 0:
                score += 1.25 * changed_match + 0.35
            elif active_match > 0:
                score -= 1.0 + active_match
            else:
                score -= 0.2
        if item.get("outcome") == "superseded":
            score -= 0.25
        ranked.append((score, int(item.get("created_order", 0)), str(item["ref"]), item))
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
    selected = []
    used = 0
    for _score, _order, ref, item in ranked:
        size = len(str(item.get("content", "")))
        if len(selected) >= max_items:
            break
        if used + size > max_chars:
            continue
        selected.append(ref)
        used += size
    return selected
'''


class FakeModelClient:
    def __init__(self):
        self.calls = 0

    def identity(self):
        return ModelIdentity("fake-local-model", "f" * 64, "test")

    def generate_json(self, *, system, prompt, schema, max_output_tokens, seed):
        self.calls += 1
        if "hypothesis" in schema.get("properties", {}):
            payload = {
                "hypothesis": "Using all observer-state fields and conditional failure relevance will improve bounded selection.",
                "observed_evidence": [
                    "The public changed-constraint probe missed a newly feasible failed IP.",
                    "The public evidence probe preferred an untested claim to an evaluation.",
                ],
                "diagnostic_findings": [
                    {
                        "case": "raised_storage_ceiling",
                        "observed_selection": ["DIAG_STORAGE_DISTRACTOR"],
                        "missed_required": ["DIAG_STORAGE_FAILED"],
                        "source_mechanism": "The query uses goal overlap but ignores changed_constraints and failure_condition.",
                        "relation_to_hypothesis": "Conditional failure relevance could recover the missed candidate.",
                    },
                    {
                        "case": "unchanged_offline_constraint",
                        "observed_selection": ["DIAG_OFFLINE_GENERIC"],
                        "missed_required": ["DIAG_OFFLINE_LOCAL"],
                        "source_mechanism": "The goal-only overlap ignores active_constraints and outcome feasibility.",
                        "relation_to_hypothesis": "Active rejection conditions should suppress infeasible failures.",
                    },
                    {
                        "case": "measured_evidence",
                        "observed_selection": ["DIAG_EVIDENCE_IDEA"],
                        "missed_required": ["DIAG_EVIDENCE_EVAL"],
                        "source_mechanism": "The overlap score ignores origin, outcome, and evidence fields.",
                        "relation_to_hypothesis": "Relevant observed evaluations should outrank untested claims.",
                    },
                ],
                "source_diagnosis": "The active source tokenizes only goal and content.",
                "proposed_change": "Score all observer fields and condition failed-IP relevance on active versus changed constraints.",
                "expected_benefit": "More relevant research evidence under the same item and character budgets.",
                "risks": ["Heuristic weights may not generalize."],
            }
        else:
            payload = {"source": IMPROVED_SOURCE, "implementation_note": "Observer-aware deterministic scorer."}
        return payload, {"request": {"seed": seed}, "response": {"done": True}}


class RebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.agent_root = cls.repo_root / "agent"

    def make_supervisor(self, root: Path) -> RebuildSupervisor:
        component = self.agent_root / "owned_components" / "context_selector"
        config = SupervisorConfig(
            repo_root=self.repo_root,
            runtime_dir=root,
            component_dir=component,
            protected_eval_dir=self.agent_root / "protected_evals",
            report_dir=root,
            accepted_version_dir=root,
            rejected_candidate_dir=root,
            model="fake-local-model",
        )
        return RebuildSupervisor(config, model_client=FakeModelClient())

    @contextmanager
    def temporary_root(self, prefix: str):
        parent = self.agent_root
        root = parent / f"{prefix}{uuid.uuid4().hex}"
        root.mkdir()
        try:
            yield str(root)
        finally:
            if root.resolve().parent != parent.resolve():
                raise RuntimeError("refusing to remove test directory outside test parent")
            shutil.rmtree(root, ignore_errors=True)

    def test_static_gate_rejects_authority_escape(self):
        unsafe = "import os\ndef select_context(observer_state, items, max_items, max_chars):\n    return []\n"
        result = validate_candidate_source(unsafe)
        self.assertFalse(result.passed)
        self.assertTrue(any("allowlist" in error or "boundary" in error for error in result.errors))

    def test_static_gate_accepts_bounded_component(self):
        self.assertTrue(validate_candidate_source(IMPROVED_SOURCE).passed)

    def test_real_cycle_with_fake_generator_uses_field_and_activates(self):
        with self.temporary_root("stoe_cycle_test_") as raw:
            supervisor = self.make_supervisor(Path(raw))
            report = supervisor.run_cycle()
            self.assertEqual("ACCEPT", report["decision"])
            self.assertTrue(report["activated"])
            self.assertLess(
                report["evaluation"]["active"]["pass_count"],
                report["evaluation"]["candidate"]["pass_count"],
            )
            self.assertFalse(report["acceptance"]["regressions"])
            self.assertTrue(report["activation"]["health"]["healthy"])
            self.assertGreater(report["activation"]["health"]["persistent_node_count"], 37)
            self.assertTrue(report["investigation"]["observed_failure_refs"])
            self.assertTrue(report["investigation"]["synthesis_navigation_run_id"].startswith("RETRIEVAL_"))
            self.assertTrue(
                any(item["origin"] == "failure_history" for item in report["investigation"]["bounded_prior_context"])
            )
            self.assertEqual(3, report["investigation"]["case_count"])
            self.assertTrue(Path(report["report_path"]).exists())
            active = supervisor.read_active_pointer()
            self.assertTrue(active["version"].startswith("generated_"))

    def test_proposal_gate_rejects_ungrounded_abstraction(self):
        proposal = {
            "hypothesis": "Abstract observer validation may help.",
            "observed_evidence": ["A graph exists."],
            "diagnostic_findings": [],
            "source_diagnosis": "The field is evolving.",
            "proposed_change": "Strengthen validation.",
            "expected_benefit": "Improvement.",
            "risks": ["Complexity."],
        }
        investigation = {
            "diagnostics": [
                {
                    "case": "observed_failure",
                    "selector_passed": False,
                    "selector_selected": ["WRONG"],
                    "missed_refs": ["RIGHT"],
                }
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "diagnostic_findings"):
            RebuildSupervisor._validate_proposal(proposal, investigation)

    def test_deliberate_activation_failure_rolls_back_in_isolation(self):
        with self.temporary_root("stoe_rollback_test_") as raw:
            supervisor = self.make_supervisor(Path(raw))
            result = supervisor.failure_probe()
            self.assertTrue(result["probe_passed"])
            self.assertFalse(result["activated"])
            self.assertTrue(result["rollback_health"]["healthy"])
            self.assertEqual("v1", result["restored_pointer"]["version"])

    def test_active_baseline_is_deterministic_and_budgeted(self):
        selector = load_selector(
            self.agent_root / "owned_components" / "context_selector" / "versions" / "v1.py"
        )
        items = [
            {"ref": "A", "content": "short relevant evidence", "created_order": 1},
            {"ref": "B", "content": "x" * 200, "created_order": 2},
        ]
        observer = {"goal": "relevant evidence"}
        first = selector(observer, items, 1, 80)
        second = selector(observer, items, 1, 80)
        self.assertEqual(["A"], first)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
