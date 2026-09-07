from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from stoe_agent.ollama import ModelIdentity, OllamaClient
from stoe_agent.continuity import ContinuityDivergenceError
from stoe_agent.selector_loader import load_selector, sha256_file
from stoe_agent.selection_policy import execute_policy, validate_policy
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

IMPROVED_POLICY = {
    "format": "stoe.selection_policy",
    "version": 1,
    "filters": [],
    "score_rules": [
        {
            "op": "token_similarity",
            "left_fields": [
                "observer_state.goal",
                "observer_state.active_constraints",
                "observer_state.changed_constraints",
                "observer_state.evidence",
                "observer_state.open_questions",
            ],
            "right_field": "item.content",
            "weight": 1.0,
        },
        {
            "op": "conditional_similarity",
            "conditions": [{"field": "item.origin", "op": "eq", "value": "failure_history"}],
            "left_fields": ["observer_state.changed_constraints"],
            "right_field": "item.failure_condition",
            "weight": 1.25,
            "bias": 0.35,
        },
        {
            "op": "conditional_similarity",
            "conditions": [{"field": "item.outcome", "op": "in", "values": ["failed", "failure", "rejected"]}],
            "left_fields": ["observer_state.changed_constraints"],
            "right_field": "item.failure_condition",
            "weight": 1.25,
            "bias": 0.35,
        },
        {
            "op": "constant_if",
            "conditions": [
                {"field": "item.origin", "op": "eq", "value": "evaluation"},
                {"field": "item.outcome", "op": "eq", "value": "supported"},
            ],
            "weight": 0.7,
        },
        {
            "op": "constant_if",
            "conditions": [{"field": "item.outcome", "op": "eq", "value": "superseded"}],
            "weight": -0.25,
        },
    ],
    "sort": [
        {"key": "score", "direction": "desc"},
        {"key": "item.created_order", "direction": "desc"},
        {"key": "item.ref", "direction": "asc"},
    ],
    "budget": {"strategy": "greedy_skip_oversize"},
}


class FakeModelClient:
    def __init__(self, policy=IMPROVED_POLICY):
        self.calls = 0
        self.policy = policy

    def identity(self):
        return ModelIdentity("fake-local-model", "f" * 64, "test")

    def generate_json(
        self, *, system, prompt, schema, max_output_tokens, seed, context_sections=None, truncation_events=None
    ):
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
                "implementation_inputs": [
                    "observer_state.goal",
                    "observer_state.active_constraints",
                    "observer_state.changed_constraints",
                    "observer_state.evidence",
                    "observer_state.open_questions",
                    "item.ref",
                    "item.content",
                    "item.origin",
                    "item.kind",
                    "item.outcome",
                    "item.failure_condition",
                    "item.created_order",
                    "max_items",
                    "max_chars",
                ],
                "input_feasibility": "Every score uses a field supplied by the public selector contract.",
                "expected_benefit": "More relevant research evidence under the same item and character budgets.",
                "risks": ["Heuristic weights may not generalize."],
            }
        else:
            payload = {"policy": self.policy, "implementation_note": "Observer-aware deterministic scorer."}
        return payload, {"request": {"seed": seed}, "response": {"done": True}}


class RaisingModelClient:
    def identity(self):
        return ModelIdentity("broken-local-model", "e" * 64, "test")

    def generate_json(self, **kwargs):
        raise RuntimeError("deliberate provider failure")


class RebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.agent_root = cls.repo_root / "agent"

    def make_supervisor(
        self, root: Path, model_client=None, *, public_timeout: float = 5.0
    ) -> RebuildSupervisor:
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
            public_evaluation_timeout_seconds=public_timeout,
            persist_active_manifest=False,
        )
        return RebuildSupervisor(config, model_client=model_client or FakeModelClient())

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
        self.assertTrue(any("unsupported" in error for error in result.errors))

    def test_executable_candidate_source_is_never_accepted(self):
        self.assertFalse(validate_candidate_source(IMPROVED_SOURCE).passed)
        self.assertTrue(validate_policy(IMPROVED_POLICY).passed)

    def test_ollama_uses_structured_thinking_when_response_is_empty(self):
        client = OllamaClient(model="test-model")
        client._json_request = lambda path, payload=None: {
            "response": "",
            "thinking": '{"ok": true}',
            "context": [1, 2, 3],
            "prompt_eval_count": 17,
            "eval_count": 4,
            "done": True,
        }
        parsed, trace = client.generate_json(
            system="test",
            prompt="test",
            schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            max_output_tokens=32,
            seed=1,
        )
        self.assertEqual({"ok": True}, parsed)
        self.assertEqual("thinking", trace["parsed_response_channel"])
        self.assertNotIn("context", trace["response"])
        self.assertEqual(17, trace["provider_token_usage"]["prompt_tokens"])
        self.assertEqual(21, trace["provider_token_usage"]["total_tokens"])
        self.assertTrue(trace["token_budget"]["fits"])

    def test_provider_failure_is_conserved_as_safe_rejection(self):
        with self.temporary_root("stoe_provider_failure_") as raw:
            supervisor = self.make_supervisor(Path(raw), RaisingModelClient())
            report = supervisor.run_cycle()
            self.assertEqual("ERROR_REJECT", report["decision"])
            self.assertFalse(report["activated"])
            self.assertEqual("v1", report["active_after"]["version"])
            self.assertTrue(report["failure_field_ref"].startswith("REBUILD_"))

    def test_cycle_stable_action_id_prevents_duplicate_model_calls(self):
        with self.temporary_root("stoe_duplicate_cycle_") as raw:
            client = FakeModelClient()
            supervisor = self.make_supervisor(Path(raw), client)
            supervisor.research_state.begin_action(
                action_id="model-cycle:already-done",
                description="Synthetic prior model cycle.",
            )
            supervisor.research_state.set_action_status(
                action_id="model-cycle:already-done",
                status="completed",
                result_refs=["prior-report"],
            )
            result = supervisor.run_cycle(action_id="model-cycle:already-done")
            self.assertEqual("SKIP_COMPLETED_ACTION", result["decision"])
            self.assertEqual(0, client.calls)

    def test_real_cycle_with_fake_generator_uses_field_and_activates(self):
        with self.temporary_root("stoe_cycle_test_") as raw:
            supervisor = self.make_supervisor(Path(raw))
            baseline_eval = {
                "status": "completed",
                "pass_count": 1,
                "case_count": 2,
                "passed_cases": ["baseline_pass"],
                "critical_failures": [],
                "results": [],
            }
            candidate_eval = {
                "status": "completed",
                "pass_count": 2,
                "case_count": 2,
                "passed_cases": ["baseline_pass", "new_pass"],
                "critical_failures": [],
                "results": [],
            }
            with patch.object(supervisor, "_evaluate", side_effect=[baseline_eval, candidate_eval]):
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
            "implementation_inputs": ["item.content"],
            "input_feasibility": "Uses the public content field.",
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

    def test_proposal_gate_rejects_unavailable_runtime_inputs(self):
        client = FakeModelClient()
        proposal, _trace = client.generate_json(
            system="test",
            prompt="test",
            schema={"properties": {"hypothesis": {}}},
            max_output_tokens=1,
            seed=1,
        )
        proposal["implementation_inputs"] = ["navigator.edge_types"]
        investigation = {
            "diagnostics": [
                {
                    "case": finding["case"],
                    "selector_passed": False,
                    "selector_selected": finding["observed_selection"],
                    "missed_refs": finding["missed_required"],
                }
                for finding in proposal["diagnostic_findings"]
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "unavailable selector inputs"):
            RebuildSupervisor._validate_proposal(proposal, investigation)

    def test_public_behavioral_gate_rejects_noop_before_protected_eval(self):
        with self.temporary_root("stoe_public_noop_") as raw:
            noop_policy = dict(IMPROVED_POLICY)
            noop_policy["score_rules"] = [
                {
                    "op": "token_similarity",
                    "left_fields": ["observer_state.goal"],
                    "right_field": "item.content",
                    "weight": 1.0,
                }
            ]
            supervisor = self.make_supervisor(Path(raw), FakeModelClient(policy=noop_policy))
            report = supervisor.run_cycle()
            self.assertEqual("REJECT_PUBLIC_MECHANISM", report["decision"])
            self.assertFalse(report["activated"])
            self.assertEqual(0, report["public_behavioral_improvement"]["candidate_pass_count"])
            self.assertNotIn("evaluation", report)

    def test_public_diagnostic_nontermination_is_bounded(self):
        with self.temporary_root("stoe_public_timeout_") as raw:
            root = Path(raw)
            source = root / "candidate.policy.json"
            source.write_text(json.dumps(IMPROVED_POLICY), encoding="utf-8")
            supervisor = self.make_supervisor(root, public_timeout=0.2)
            with patch(
                "stoe_agent.supervisor.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="worker", timeout=0.2),
            ):
                result = supervisor._evaluate_public(source, artifact_type="declarative_policy")
            self.assertEqual("rejected", result["status"])
            self.assertEqual("timeout", result["failure_kind"])
            self.assertEqual("v1", supervisor.read_active_pointer()["version"])

    def test_public_diagnostic_child_crash_is_a_recordable_rejection(self):
        with self.temporary_root("stoe_public_crash_") as raw:
            root = Path(raw)
            source = root / "crash.py"
            source.write_text(
                "def select_context(observer_state, items, max_items, max_chars):\n"
                "    raise SystemExit(9)\n",
                encoding="utf-8",
            )
            supervisor = self.make_supervisor(root)
            result = supervisor._evaluate_public(source)
            self.assertEqual("rejected", result["status"])
            self.assertEqual("crash", result["failure_kind"])
            self.assertEqual("v1", supervisor.read_active_pointer()["version"])

    def test_public_diagnostic_malformed_child_output_is_rejected(self):
        with self.temporary_root("stoe_public_malformed_") as raw:
            supervisor = self.make_supervisor(Path(raw))
            completed = subprocess.CompletedProcess([], 0, stdout="not-json", stderr="")
            with patch("stoe_agent.supervisor.subprocess.run", return_value=completed):
                result = supervisor._evaluate_public(supervisor.baseline_path)
            self.assertEqual("rejected", result["status"])
            self.assertEqual("malformed_output", result["failure_kind"])

    def test_public_diagnostic_malformed_policy_is_recorded_not_raised(self):
        with self.temporary_root("stoe_public_invalid_") as raw:
            root = Path(raw)
            source = root / "invalid.policy.json"
            source.write_text('{"format": "wrong"}', encoding="utf-8")
            supervisor = self.make_supervisor(root)
            result = supervisor._evaluate_public(source, artifact_type="declarative_policy")
            self.assertEqual("rejected", result["status"])
            self.assertEqual(0, result["pass_count"])
            self.assertIn(result["failure_kind"], {"crash", "worker_exception"})

    def _assert_exception_safe_activation(self, exc: Exception, expected_kind: str):
        with self.temporary_root(f"stoe_activation_{expected_kind}_") as raw:
            root = Path(raw)
            supervisor = self.make_supervisor(root)
            candidate = root / "candidate.py"
            candidate.write_text(IMPROVED_SOURCE, encoding="utf-8")
            candidate_ip = supervisor.journal.add_ip(
                cycle_id=f"activation_{expected_kind}",
                label="candidate",
                content="Synthetic activation-recovery fixture.",
                kind="implementation",
            )
            with patch.object(
                supervisor,
                "_fresh_process_health",
                side_effect=[exc, {"healthy": True, "active_version": "v1"}],
            ):
                result = supervisor._activate(
                    version="candidate",
                    source_path=candidate,
                    cycle_id=f"activation_{expected_kind}",
                    candidate_ref=candidate_ip["ref"],
                )
            self.assertFalse(result["activated"])
            self.assertTrue(result["restoration_succeeded"])
            self.assertTrue(result["recovery_succeeded"])
            self.assertEqual(expected_kind, result["health"]["failure_kind"])
            self.assertEqual("v1", supervisor.read_active_pointer()["version"])
            self.assertEqual(
                {"attempt", "failure", "restoration", "recovery_evaluation"},
                set(result["field_refs"]),
            )
            with sqlite3.connect(supervisor.journal.db_path) as connection:
                connected = connection.execute(
                    "SELECT COUNT(*) FROM edges WHERE source IN (?, ?, ?, ?)",
                    tuple(result["field_refs"].values()),
                ).fetchone()[0]
            self.assertGreaterEqual(connected, 3)

    def test_activation_timeout_restores_and_verifies_previous_version(self):
        self._assert_exception_safe_activation(
            subprocess.TimeoutExpired(cmd="worker", timeout=0.1), "timeout"
        )

    def test_activation_launch_error_restores_and_verifies_previous_version(self):
        self._assert_exception_safe_activation(OSError("synthetic launch failure"), "launch_error")

    def test_activation_reports_failed_recovery_explicitly(self):
        with self.temporary_root("stoe_activation_recovery_failure_") as raw:
            root = Path(raw)
            supervisor = self.make_supervisor(root)
            candidate = root / "candidate.py"
            candidate.write_text(IMPROVED_SOURCE, encoding="utf-8")
            candidate_ip = supervisor.journal.add_ip(
                cycle_id="recovery_failure",
                label="candidate",
                content="Synthetic recovery-failure fixture.",
                kind="implementation",
            )
            with patch.object(
                supervisor,
                "_fresh_process_health",
                side_effect=[
                    subprocess.TimeoutExpired(cmd="worker", timeout=0.1),
                    {"healthy": False, "error": "synthetic restored worker failure"},
                ],
            ):
                result = supervisor._activate(
                    version="candidate",
                    source_path=candidate,
                    cycle_id="recovery_failure",
                    candidate_ref=candidate_ip["ref"],
                )
            self.assertFalse(result["recovery_succeeded"])
            self.assertIn("RECOVERY FAILED", result["error"])
            self.assertEqual("v1", supervisor.read_active_pointer()["version"])

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

    def test_tracked_release_bootstraps_a_fresh_runtime(self):
        with self.temporary_root("stoe_release_bootstrap_") as raw:
            config = SupervisorConfig(
                repo_root=self.repo_root,
                runtime_dir=Path(raw),
                component_dir=self.agent_root / "owned_components" / "context_selector",
                protected_eval_dir=self.agent_root / "protected_evals",
                report_dir=Path(raw),
                model="fake-local-model",
                persist_active_manifest=True,
            )
            supervisor = RebuildSupervisor(config, model_client=FakeModelClient())
            release = json.loads(
                (config.component_dir / "active_release.json").read_text(encoding="utf-8")
            )
            pointer = supervisor.read_active_pointer()
            self.assertEqual(release["version"], pointer["version"])
            self.assertEqual(release["sha256"], pointer["sha256"])
            self.assertEqual("legacy_python", pointer["artifact_type"])

    def test_stale_runtime_active_pointer_fast_forwards_to_tracked_release(self):
        with self.temporary_root("stoe_release_stale_") as raw:
            runtime = Path(raw)
            v1 = self.agent_root / "owned_components" / "context_selector" / "versions" / "v1.py"
            (runtime / "active_component.json").write_text(
                json.dumps(
                    {
                        "version": "v1",
                        "source_path": str(v1.resolve()),
                        "sha256": sha256_file(v1),
                        "artifact_type": "legacy_python",
                        "activated_at": "2026-01-01T00:00:00+00:00",
                        "previous_version": None,
                    }
                ),
                encoding="utf-8",
            )
            config = SupervisorConfig(
                repo_root=self.repo_root,
                runtime_dir=runtime,
                component_dir=self.agent_root / "owned_components" / "context_selector",
                protected_eval_dir=self.agent_root / "protected_evals",
                report_dir=runtime,
                persist_active_manifest=True,
                continuity_branch="feature/self-rebuild-cycle-v1",
            )
            supervisor = RebuildSupervisor(config, model_client=FakeModelClient())
            release = json.loads(supervisor.active_release_manifest.read_text(encoding="utf-8"))
            self.assertEqual(release["version"], supervisor.read_active_pointer()["version"])

    def _isolated_release_supervisor(self, root: Path) -> tuple[RebuildSupervisor, SupervisorConfig]:
        component = root / "component"
        shutil.copytree(self.agent_root / "owned_components" / "context_selector", component)
        config = SupervisorConfig(
            repo_root=self.repo_root,
            runtime_dir=root / "runtime",
            component_dir=component,
            protected_eval_dir=self.agent_root / "protected_evals",
            report_dir=root / "reports",
            persist_active_manifest=True,
            continuity_branch="branch-a",
        )
        return RebuildSupervisor(config, model_client=FakeModelClient()), config

    def test_provably_ahead_runtime_active_pointer_is_preserved(self):
        with self.temporary_root("stoe_release_ahead_") as raw:
            supervisor, config = self._isolated_release_supervisor(Path(raw))
            prior = supervisor.read_active_pointer()
            policy = config.component_dir / "versions" / "future.policy.json"
            policy.write_text(json.dumps(IMPROVED_POLICY), encoding="utf-8")
            future = supervisor._successor_pointer(
                pointer={
                    "version": "future",
                    "source_path": str(policy.resolve()),
                    "sha256": sha256_file(policy),
                    "artifact_type": "selection_policy",
                    "activated_at": "2026-09-08T00:00:00+00:00",
                    "previous_version": prior["version"],
                },
                predecessor=prior,
            )
            supervisor._atomic_write_json(supervisor.active_pointer, future)

            resumed = RebuildSupervisor(config, model_client=FakeModelClient())
            self.assertEqual("future", resumed.read_active_pointer()["version"])

    def test_divergent_runtime_active_pointer_fails_explicitly(self):
        with self.temporary_root("stoe_release_divergent_") as raw:
            supervisor, config = self._isolated_release_supervisor(Path(raw))
            policy = config.component_dir / "versions" / "unrelated.policy.json"
            policy.write_text(json.dumps(IMPROVED_POLICY), encoding="utf-8")
            pointer = {
                "version": "unrelated",
                "source_path": str(policy.resolve()),
                "sha256": sha256_file(policy),
                "artifact_type": "selection_policy",
                "activated_at": "2026-09-08T00:00:00+00:00",
                "previous_version": None,
            }
            pointer["_lineage"] = {
                "schema_version": 1,
                "kind": "active_release",
                "stream_id": "unrelated-stream",
                "branch_id": "branch-a",
                "release_id": supervisor._release_id(pointer),
                "parent_release_id": None,
                "ancestor_release_ids": [],
            }
            supervisor._atomic_write_json(supervisor.active_pointer, pointer)

            with self.assertRaisesRegex(ContinuityDivergenceError, "cannot reconcile"):
                RebuildSupervisor(config, model_client=FakeModelClient())


if __name__ == "__main__":
    unittest.main()
