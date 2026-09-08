from __future__ import annotations

import builtins
import json
import os
import shutil
import socket
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from stoe_agent.selection_policy import (
    MAX_FIELD_CHARS,
    MAX_ITEMS,
    MAX_OUTPUT_CHARS,
    MAX_POLICY_BYTES,
    PolicyError,
    execute_policy,
    load_policy,
    validate_policy,
)
from stoe_agent.selector_loader import load_selector_artifact
from stoe_agent.supervisor import RebuildSupervisor, SupervisorConfig


def minimal_policy() -> dict:
    return {
        "format": "stoe.selection_policy",
        "version": 1,
        "filters": [],
        "score_rules": [
            {
                "op": "token_similarity",
                "left_fields": ["observer_state.goal"],
                "right_field": "item.content",
                "weight": 1.0,
            }
        ],
        "sort": [
            {"key": "score", "direction": "desc"},
            {"key": "item.created_order", "direction": "desc"},
            {"key": "item.ref", "direction": "asc"},
        ],
        "budget": {"strategy": "greedy_skip_oversize"},
    }


class CapabilityBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.agent_root = cls.repo_root / "agent"

    def setUp(self):
        self.root = self.agent_root / f"capability_test_{uuid.uuid4().hex}"
        self.root.mkdir()

    def tearDown(self):
        if self.root.resolve().parent != self.agent_root.resolve():
            raise RuntimeError("refusing to remove capability test directory outside agent root")
        shutil.rmtree(self.root, ignore_errors=True)

    def supervisor(self) -> RebuildSupervisor:
        return RebuildSupervisor(
            SupervisorConfig(
                repo_root=self.repo_root,
                runtime_dir=self.root / "runtime",
                component_dir=self.agent_root / "owned_components" / "context_selector",
                protected_eval_dir=self.agent_root / "protected_evals",
                report_dir=self.root / "reports",
                accepted_version_dir=self.root / "accepted",
                rejected_candidate_dir=self.root / "rejected",
                model="unused",
                public_evaluation_timeout_seconds=1.0,
                evaluation_timeout_seconds=2,
                persist_active_manifest=False,
            ),
            model_client=object(),
        )

    def test_python_attack_artifacts_are_rejected_before_import_or_execution(self):
        sentinel = self.root / "authority_reached.txt"
        active_pointer = self.root / "active_component.json"
        payloads = {
            "builtins_open": (
                "def select_context(observer_state, items, max_items, max_chars):\n"
                f"    h = __builtins__['open']({str(sentinel)!r}, 'w'); h.write('x'); h.close(); return []\n"
            ),
            "indirect_eval_exec_import": (
                "runner = __builtins__['eval']\n"
                "compiler = __builtins__['exec']\n"
                "loader = __builtins__['__import__']\n"
                f"runner(\"__builtins__['open']({str(sentinel)!r}, 'w').write('x')\")\n"
                "def select_context(observer_state, items, max_items, max_chars): return []\n"
            ),
            "getattr_dunder": (
                "root = getattr((), '__class__')\n"
                f"__builtins__['open']({str(sentinel)!r}, 'w').write(str(root))\n"
                "def select_context(observer_state, items, max_items, max_chars): return []\n"
            ),
            "top_level_side_effect": (
                f"__builtins__['open']({str(sentinel)!r}, 'w').write('top level')\n"
                "def select_context(observer_state, items, max_items, max_chars): return []\n"
            ),
            "protected_cases_read": (
                "def select_context(observer_state, items, max_items, max_chars):\n"
                "    data = __builtins__['open']('cases.json').read()\n"
                f"    __builtins__['open']({str(sentinel)!r}, 'w').write(data); return []\n"
            ),
            "environment": (
                "import os\n"
                f"__builtins__['open']({str(sentinel)!r}, 'w').write(str(os.environ))\n"
                "def select_context(observer_state, items, max_items, max_chars): return []\n"
            ),
            "network": (
                "import socket\n"
                "socket.create_connection(('127.0.0.1', 9), timeout=0.01)\n"
                "def select_context(observer_state, items, max_items, max_chars): return []\n"
            ),
            "subprocess": (
                "import subprocess\n"
                "subprocess.run(['cmd', '/c', 'ver'])\n"
                "def select_context(observer_state, items, max_items, max_chars): return []\n"
            ),
            "active_pointer": (
                "import pathlib\n"
                f"pathlib.Path({str(active_pointer)!r}).read_text()\n"
                "def select_context(observer_state, items, max_items, max_chars): return []\n"
            ),
            "infinite_and_recursive": (
                "def recurse(): return recurse()\n"
                "recurse()\n"
                "def select_context(observer_state, items, max_items, max_chars):\n"
                "    while True: pass\n"
            ),
            "excessive_output_and_allocation": (
                "blob = 'x' * (10 ** 9)\n"
                "print(blob)\n"
                "def select_context(observer_state, items, max_items, max_chars): return [blob]\n"
            ),
        }
        supervisor = self.supervisor()
        for name, source in payloads.items():
            with self.subTest(name=name):
                artifact = self.root / f"{name}.py"
                artifact.write_text(source, encoding="utf-8")
                with self.assertRaisesRegex(PermissionError, "immutable allowlisted legacy release"):
                    load_selector_artifact(artifact, "legacy_python")
                self.assertFalse(sentinel.exists())
                self.assertEqual("rejected", supervisor._evaluate_public(artifact)["status"])
                self.assertEqual("rejected", supervisor._evaluate(artifact)["status"])
                self.assertFalse(sentinel.exists())

    def test_policy_strings_have_no_authority_and_unknown_input_fields_are_not_exposed(self):
        sentinel = self.root / "policy_side_effect.txt"
        policy = minimal_policy()
        policy["score_rules"].append(
            {
                "op": "constant_if",
                "conditions": [
                    {
                        "field": "item.content",
                        "op": "eq",
                        "value": f"__builtins__['open']({str(sentinel)!r}, 'w')",
                    }
                ],
                "weight": 1.0,
            }
        )
        observer = {
            "goal": "safe evidence",
            "probe_path": str(sentinel),
            "environment": dict(os.environ),
            "active_pointer": str(self.agent_root / "runtime" / "active_component.json"),
        }
        items = [{"ref": "A", "content": "safe evidence", "created_order": 1}]
        with (
            patch.object(builtins, "open") as open_mock,
            patch.object(builtins, "eval") as eval_mock,
            patch.object(builtins, "exec") as exec_mock,
            patch.object(builtins, "__import__") as import_mock,
            patch.object(socket, "socket") as socket_mock,
            patch.object(subprocess, "Popen") as popen_mock,
            patch.object(os, "getenv") as getenv_mock,
        ):
            self.assertEqual(["A"], execute_policy(policy, observer, items, 1, 100))
        for mock in (open_mock, eval_mock, exec_mock, import_mock, socket_mock, popen_mock, getenv_mock):
            mock.assert_not_called()
        self.assertFalse(sentinel.exists())

        policy["score_rules"][0]["left_fields"] = ["observer_state.probe_path"]
        self.assertFalse(validate_policy(policy).passed)

    def test_malformed_overcomplex_and_resource_excess_policies_fail_closed(self):
        malformed = self.root / "malformed.policy.json"
        malformed.write_text("{not json", encoding="utf-8")
        with self.assertRaises(PolicyError):
            load_policy(malformed)

        oversized = self.root / "oversized.policy.json"
        oversized.write_text(" " * (MAX_POLICY_BYTES + 1), encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "exceeds"):
            load_policy(oversized)

        overcomplex = minimal_policy()
        overcomplex["score_rules"] = overcomplex["score_rules"] * 25
        self.assertFalse(validate_policy(overcomplex).passed)

        nonfinite = minimal_policy()
        nonfinite["score_rules"].append(
            {
                "op": "constant_if",
                "conditions": [{"field": "item.outcome", "op": "eq", "value": float("nan")}],
                "weight": 1.0,
            }
        )
        self.assertFalse(validate_policy(nonfinite).passed)

        recursive_shape: dict = minimal_policy()
        nested: dict = {}
        cursor = nested
        for _ in range(200):
            cursor["nested"] = {}
            cursor = cursor["nested"]
        recursive_shape["unexpected"] = nested
        self.assertFalse(validate_policy(recursive_shape).passed)

        policy = minimal_policy()
        item = {"ref": "A", "content": "ok", "created_order": 1}
        with self.assertRaises(PolicyError):
            execute_policy(policy, {"goal": "ok"}, [item] * (MAX_ITEMS + 1), 1, 10)
        with self.assertRaises(PolicyError):
            execute_policy(policy, {"goal": "ok"}, [item], 129, 10)
        with self.assertRaises(PolicyError):
            execute_policy(policy, {"goal": "ok"}, [item], 1, MAX_OUTPUT_CHARS + 1)
        with self.assertRaises(PolicyError):
            execute_policy(policy, {"goal": "x" * (MAX_FIELD_CHARS + 1)}, [item], 1, 10)

    def test_policy_candidate_runs_in_both_bounded_evaluators_without_python_import(self):
        artifact = self.root / "candidate.policy.json"
        artifact.write_text(json.dumps(minimal_policy()), encoding="utf-8")
        supervisor = self.supervisor()
        public = supervisor._evaluate_public(artifact, artifact_type="declarative_policy")
        protected = supervisor._evaluate(artifact, artifact_type="declarative_policy")
        self.assertEqual("completed", public["status"])
        self.assertEqual("completed", protected["status"])
        self.assertEqual("declarative_policy", protected["artifact_type"])

    def test_protected_timeout_and_launch_errors_are_structured_rejections(self):
        supervisor = self.supervisor()
        artifact = self.root / "candidate.policy.json"
        artifact.write_text(json.dumps(minimal_policy()), encoding="utf-8")
        with patch("stoe_agent.supervisor.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 1)):
            result = supervisor._evaluate(artifact, artifact_type="declarative_policy")
        self.assertEqual("rejected", result["status"])
        self.assertEqual("timeout", result["failure_kind"])
        with patch("stoe_agent.supervisor.subprocess.run", side_effect=OSError("launch failed")):
            result = supervisor._evaluate(artifact, artifact_type="declarative_policy")
        self.assertEqual("rejected", result["status"])
        self.assertEqual("launch_error", result["failure_kind"])

    def test_capability_checkpoint_is_linked_and_idempotent_without_model_calls(self):
        report = self.root / "checkpoint.md"
        report.write_text("verified synthetic capability checkpoint\n", encoding="utf-8")
        supervisor = self.supervisor()
        first = supervisor.record_capability_boundary_checkpoint(report)
        self.assertEqual("COMPLETED", first["decision"])
        self.assertEqual(0, first["model_calls"])
        self.assertEqual(
            {
                "intended_authority_boundary",
                "bypass_reproduction",
                "affected_evaluation_claim",
                "repair_decision",
                "repair_implementation",
                "adversarial_tests",
                "remaining_limitations",
                "remaining_question",
            },
            set(first["field_refs"]),
        )
        second = supervisor.record_capability_boundary_checkpoint(report)
        self.assertEqual("SKIP_COMPLETED_ACTION", second["decision"])
        self.assertEqual(0, second["model_calls"])


if __name__ == "__main__":
    unittest.main()
