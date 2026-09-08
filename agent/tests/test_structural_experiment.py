from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from stoe_agent.investigation import public_diagnostics
from stoe_agent.structural_experiment import (
    CONDITIONS,
    POLICY_MAX_TOKENS,
    POLICY_SEED,
    PROPOSAL_MAX_TOKENS,
    PROPOSAL_SEED,
    STRUCTURAL_CONTEXT_CHAR_CAP,
    assert_no_hidden_identifiers,
    bounded_field_contexts,
    observable_diagnostics,
    select_unique_winner,
    validate_unseen_cases,
)
from stoe_agent.supervisor import RebuildSupervisor


class StructuralExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.experiment = cls.root / "agent" / "structural_input_experiment"

    @staticmethod
    def investigation():
        case = public_diagnostics()[0]
        return {
            "pass_count": 0,
            "known_structure": "typed paths are observed",
            "unknown_structure": "generalization is unknown",
            "synthesis_navigation_run_id": "RUN-S",
            "bounded_prior_context": [
                {
                    "ref": "FIELD-1",
                    "origin": "failure_history",
                    "kind": "hypothesis",
                    "outcome": "failed",
                    "content": "A rejected branch may become feasible after a capacity change.",
                    "path": [
                        {"type": "invalidates", "direction": "outgoing", "from": "CHANGE", "to": "FIELD-1"}
                    ],
                    "reason": "navigator score",
                }
            ],
            "diagnostics": [
                {
                    "case": case.name,
                    "observer": case.observer,
                    "required_refs": list(case.required_refs),
                    "forbidden_refs": list(case.forbidden_refs),
                    "selector_selected": ["DIAG_STORAGE_DISTRACTOR"],
                    "selector_passed": False,
                    "missed_refs": ["DIAG_STORAGE_FAILED"],
                    "navigator_run_id": "RUN-D",
                    "navigator_candidate_trace": [
                        {
                            "external_ref": "DIAG_STORAGE_FAILED",
                            "selected": True,
                            "path": [
                                {"type": "rejected_by", "direction": "incoming", "from": "FAIL", "to": "ITEM"}
                            ],
                            "scores": {"final": 0.7},
                        }
                    ],
                }
            ],
        }

    def test_frozen_cases_are_distinct_and_hash_locked(self):
        cases_path = self.experiment / "cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        self.assertEqual(12, validate_unseen_cases(cases)["independent_case_count"])
        self.assertEqual(36, len({item["ref"] for case in cases for item in case["items"]}))
        self.assertEqual(
            "10c9e3685bc3634715d65418fb694203309698dfc5d9ec73b257aa9857e9186b",
            hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        )

    def test_common_content_is_identical_and_overlay_contains_only_structure(self):
        memory, overlay = bounded_field_contexts(self.investigation())
        self.assertEqual(
            [item["record_id"] for item in memory["records"]],
            [item["record_id"] for item in overlay["records"]],
        )
        overlay_text = json.dumps(overlay, sort_keys=True)
        self.assertNotIn("A rejected branch may become feasible", overlay_text)
        self.assertIn("invalidates", overlay_text)
        self.assertIn("outgoing", overlay_text)
        self.assertLessEqual(
            len(json.dumps(memory, sort_keys=True, separators=(",", ":")).encode())
            + len(json.dumps(overlay, sort_keys=True, separators=(",", ":")).encode()),
            STRUCTURAL_CONTEXT_CHAR_CAP,
        )

    def test_structural_prompt_is_ordinary_prompt_plus_only_the_overlay(self):
        investigation = self.investigation()
        observable = observable_diagnostics(investigation)
        memory, overlay = bounded_field_contexts(investigation)
        supervisor = object.__new__(RebuildSupervisor)
        ordinary = supervisor._proposal_prompt(
            "ACTIVE", investigation, observable_diagnostics=observable, unstructured_memory=memory
        )
        structural = supervisor._proposal_prompt(
            "ACTIVE", investigation, observable_diagnostics=observable,
            unstructured_memory=memory, structural_context=overlay,
        )
        self.assertTrue(structural.startswith(ordinary))
        self.assertIn("BOUNDED TYPED STRUCTURAL EVIDENCE", structural[len(ordinary):])

    def test_hidden_identifiers_are_rejected_before_evaluation(self):
        cases = json.loads((self.experiment / "cases.json").read_text(encoding="utf-8"))
        safe = {name: {"proposal_trace": {"request": {"prompt": "public only"}}} for name in CONDITIONS}
        assert_no_hidden_identifiers(safe, cases)
        safe[CONDITIONS[0]]["proposal_trace"]["request"]["prompt"] = cases[0]["name"]
        with self.assertRaisesRegex(RuntimeError, "leaked"):
            assert_no_hidden_identifiers(safe, cases)

    def test_frozen_generation_budget_and_symmetric_winner_rule(self):
        spec = json.loads((self.experiment / "experiment_spec.json").read_text(encoding="utf-8"))
        generation = spec["generation"]
        self.assertEqual((PROPOSAL_SEED, POLICY_SEED), (generation["proposal_seed"], generation["policy_seed"]))
        self.assertEqual((PROPOSAL_MAX_TOKENS, POLICY_MAX_TOKENS), (generation["proposal_max_output_tokens"], generation["policy_max_output_tokens"]))
        conditions = {
            name: {
                "public_gate": {"decision": "PROCEED"},
                "acceptance": {"decision": "ACCEPT"},
                "metrics": {"targeted_pass_count": 5, "total_pass_count": 8},
            }
            for name in CONDITIONS
        }
        self.assertIsNone(select_unique_winner(conditions)[1])
        conditions["ORDINARY_OBSERVABLE"]["metrics"]["targeted_pass_count"] = 6
        self.assertEqual("ORDINARY_OBSERVABLE", select_unique_winner(conditions)[1])


if __name__ == "__main__":
    unittest.main()
