from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from stoe_agent.ollama import OllamaClient
from stoe_agent.qualified_harness import (
    CONDITIONS,
    MIN_REMAINING_TOKENS,
    QUALIFIED_PROPOSAL_SCHEMA,
    exercise_mock_pipelines,
    largest_gate_valid_proposal,
    policy_prompt,
    proposal_prompt,
    qualify_context_budget,
    unevaluated_metrics,
    validate_qualified_proposal,
)
from stoe_agent.selection_policy import EXPECTED_SORT


class MaximumResponseMock:
    def __init__(self, investigation):
        self.budget_manager = OllamaClient(model="never-called").budget_manager
        self.proposal = largest_gate_valid_proposal(investigation)
        self.calls = []

    def generate_json(self, *, system, prompt, schema, max_output_tokens, seed, **_kwargs):
        plan = self.budget_manager.require_plan(
            system=system, prompt=prompt, reserved_generation_tokens=max_output_tokens
        )
        self.calls.append((seed, max_output_tokens, plan["estimated"]["remaining"]))
        if "hypothesis" in schema.get("properties", {}):
            return deepcopy(self.proposal), {"mock": True, "budget": plan}
        policy = {
            "format": "stoe.selection_policy", "version": 1, "filters": [],
            "score_rules": [
                {
                    "op": "token_similarity",
                    "left_fields": ["observer_state.goal", "observer_state.changed_constraints"],
                    "right_field": "item.content", "weight": 1.0,
                }
            ],
            "sort": EXPECTED_SORT,
            "budget": {"strategy": "greedy_skip_oversize"},
        }
        return {"policy": policy, "implementation_note": "bounded mock"}, {"mock": True, "budget": plan}


class QualifiedHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.bundle = json.loads(
            (cls.root / "agent/structural_input_experiment/FROZEN_INPUT_BUNDLE.json").read_text(encoding="utf-8")
        )
        pointer = json.loads(
            (cls.root / "agent/owned_components/context_selector/active_release.json").read_text(encoding="utf-8")
        )
        cls.active_source = (
            cls.root / "agent/owned_components/context_selector/versions" / pointer["source_file"]
        ).read_text(encoding="utf-8")

    def test_all_proposal_strings_and_arrays_have_explicit_bounds(self):
        def visit(schema):
            if schema.get("type") == "string":
                self.assertIn("maxLength", schema)
            if schema.get("type") == "array":
                self.assertIn("maxItems", schema)
                visit(schema["items"])
            for child in schema.get("properties", {}).values():
                visit(child)
        visit(QUALIFIED_PROPOSAL_SCHEMA)

    def test_mechanism_grounding_is_identifier_based_not_prose_based(self):
        proposal = largest_gate_valid_proposal(self.bundle["investigation"])
        proposal["diagnostic_findings"][0]["rationale"] = "no lexical mechanism words are required here"
        validate_qualified_proposal(proposal, self.bundle["investigation"])
        bad = deepcopy(proposal)
        bad["diagnostic_findings"][0]["mechanism_ids"] = ["invented_mechanism"]
        with self.assertRaisesRegex(RuntimeError, "allowed identifier"):
            validate_qualified_proposal(bad, self.bundle["investigation"])

    def test_largest_gate_valid_proposal_qualifies_both_complete_pipelines(self):
        result = qualify_context_budget(OllamaClient(model="never-called"), self.active_source, self.bundle)
        self.assertTrue(result["qualified"])
        self.assertEqual(0, result["model_calls"])
        self.assertGreaterEqual(result["minimum_observed_remaining_tokens"], MIN_REMAINING_TOKENS)
        self.assertEqual(set(CONDITIONS), set(result["conditions"]))

    def test_maximum_mock_response_flows_through_both_arm_prompts(self):
        client = MaximumResponseMock(self.bundle["investigation"])
        result = exercise_mock_pipelines(client, self.active_source, self.bundle)
        self.assertTrue(result["completed"])
        self.assertEqual(4, result["model_calls"])
        self.assertEqual(4, len(client.calls))
        self.assertTrue(all(remaining >= MIN_REMAINING_TOKENS for _, _, remaining in client.calls))

    def test_unevaluated_metrics_are_null_and_explicit(self):
        metrics = unevaluated_metrics(12, 8, 4)
        self.assertFalse(metrics["evaluable"])
        self.assertIsNone(metrics["targeted_pass_count"])
        self.assertIsNone(metrics["control_pass_count"])
        self.assertIsNone(metrics["total_pass_count"])
        self.assertIsNone(metrics["by_family"])

    def test_v2_holdout_is_new_distinct_and_not_a_v1_rename(self):
        v1 = json.loads((self.root / "agent/structural_input_experiment/cases.json").read_text(encoding="utf-8"))
        v2 = json.loads((self.root / "agent/structural_input_experiment_v2/cases.json").read_text(encoding="utf-8"))
        from stoe_agent.structural_experiment import validate_unseen_cases
        self.assertEqual(12, validate_unseen_cases(v2)["independent_case_count"])
        self.assertTrue({c["family"] for c in v1}.isdisjoint({c["family"] for c in v2}))
        v1_content = {i["content"] for c in v1 for i in c["items"]}
        self.assertTrue(v1_content.isdisjoint({i["content"] for c in v2 for i in c["items"]}))


if __name__ == "__main__":
    unittest.main()
    exercise_mock_pipelines,
