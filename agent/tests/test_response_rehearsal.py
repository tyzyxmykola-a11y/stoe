from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from stoe_agent.ollama import OllamaClient
from stoe_agent.response_rehearsal import (
    MIN_REMAINING_TOKENS,
    POLICY_TABLE_SCHEMA,
    POLICY_MAX_TOKENS,
    PROPOSAL_MAX_TOKENS,
    compile_policy_tables,
    exercise_mock_pipelines,
    largest_valid_policy_response,
    largest_valid_proposal,
    proposal_schema,
    qualify_context,
    validate_proposal,
    validate_schema,
)


class ResponseMock:
    def __init__(self, investigation, *, proposal_mutator=None, policy_mutator=None):
        self.budget_manager = OllamaClient(model="never-called").budget_manager
        self.proposal = largest_valid_proposal(investigation)
        self.policy = largest_valid_policy_response()
        self.proposal_mutator = proposal_mutator
        self.policy_mutator = policy_mutator
        self.calls = 0

    def generate_json(self, *, system, prompt, schema, max_output_tokens, seed, **_kwargs):
        self.calls += 1
        plan = self.budget_manager.require_plan(
            system=system, prompt=prompt, reserved_generation_tokens=max_output_tokens
        )
        if "hypothesis" in schema.get("properties", {}):
            value = deepcopy(self.proposal)
            if self.proposal_mutator:
                self.proposal_mutator(value)
        else:
            value = deepcopy(self.policy)
            if self.policy_mutator:
                self.policy_mutator(value)
        return value, {"mock": True, "remaining": plan["estimated"]["remaining"]}


class ResponseRehearsalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.bundle_path = cls.root / "agent/structural_input_experiment/FROZEN_INPUT_BUNDLE.json"
        cls.bundle = json.loads(cls.bundle_path.read_text(encoding="utf-8"))
        pointer = json.loads(
            (cls.root / "agent/owned_components/context_selector/active_release.json").read_text(encoding="utf-8")
        )
        cls.active_source = (
            cls.root / "agent/owned_components/context_selector/versions" / pointer["source_file"]
        ).read_text(encoding="utf-8")

    def test_dynamic_proposal_schema_requires_each_exposed_failed_case_as_an_exact_key(self):
        schema = proposal_schema(self.bundle["investigation"])
        expected = {
            d["case"] for d in self.bundle["investigation"]["diagnostics"] if not d["selector_passed"]
        }
        findings = schema["properties"]["diagnostic_findings"]
        self.assertEqual(expected, set(findings["properties"]))
        self.assertEqual(expected, set(findings["required"]))
        self.assertFalse(findings["additionalProperties"])

        missing = largest_valid_proposal(self.bundle["investigation"])
        missing["diagnostic_findings"].pop(next(iter(expected)))
        with self.assertRaisesRegex(RuntimeError, "missing required"):
            validate_proposal(missing, self.bundle["investigation"])
        extra = largest_valid_proposal(self.bundle["investigation"])
        extra["diagnostic_findings"]["duplicate_or_unknown"] = deepcopy(next(iter(extra["diagnostic_findings"].values())))
        with self.assertRaisesRegex(RuntimeError, "additional fields"):
            validate_proposal(extra, self.bundle["investigation"])

    def test_every_string_array_and_numeric_field_is_bounded(self):
        def visit(schema):
            if schema.get("type") == "string":
                self.assertIn("maxLength", schema)
            if schema.get("type") == "array":
                self.assertIn("maxItems", schema)
                visit(schema["items"])
            if schema.get("type") in {"number", "integer"}:
                self.assertIn("minimum", schema)
                self.assertIn("maximum", schema)
            for child in schema.get("properties", {}).values():
                visit(child)
        visit(proposal_schema(self.bundle["investigation"]))
        visit(POLICY_TABLE_SCHEMA)

    def test_fixed_tables_compile_to_the_inert_trusted_policy_grammar(self):
        response = largest_valid_policy_response()
        policy = compile_policy_tables(response)
        self.assertEqual("stoe.selection_policy", policy["format"])
        self.assertEqual(9, len(policy["score_rules"]))
        self.assertEqual("greedy_skip_oversize", policy["budget"]["strategy"])
        self.assertNotIn("implementation_note", policy)

    def test_largest_schema_valid_outputs_fit_output_and_context_reserves(self):
        client = OllamaClient(model="never-called")
        result = qualify_context(client, self.active_source, self.bundle)
        self.assertLessEqual(result["largest_output_estimated_tokens"]["proposal"], PROPOSAL_MAX_TOKENS)
        self.assertLessEqual(result["largest_output_estimated_tokens"]["policy"], POLICY_MAX_TOKENS)
        self.assertGreaterEqual(result["minimum_observed_remaining_tokens"], MIN_REMAINING_TOKENS)

    def test_maximum_valid_mock_responses_complete_both_public_only_arms(self):
        client = ResponseMock(self.bundle["investigation"])
        result = exercise_mock_pipelines(client, self.active_source, self.bundle)
        self.assertTrue(result["completed"])
        self.assertEqual(4, result["model_calls"])
        self.assertEqual(4, client.calls)
        self.assertFalse(result["hidden_evaluation_performed"])

    def test_malformed_mock_proposals_fail_closed(self):
        mutators = [
            lambda value: value["diagnostic_findings"].pop(next(iter(value["diagnostic_findings"]))),
            lambda value: value["diagnostic_findings"].update({"unknown": deepcopy(next(iter(value["diagnostic_findings"].values())))}),
            lambda value: value["implementation_inputs"].append("invented_operation"),
            lambda value: value.update({"extra": "top-level side channel"}),
            lambda value: value.update({"hypothesis": "x" * 181}),
        ]
        for mutate in mutators:
            with self.subTest(mutate=mutate):
                with self.assertRaises(RuntimeError):
                    exercise_mock_pipelines(
                        ResponseMock(self.bundle["investigation"], proposal_mutator=mutate),
                        self.active_source, self.bundle,
                    )

    def test_malformed_mock_policy_tables_fail_closed(self):
        mutators = [
            lambda value: value.pop("filters"),
            lambda value: value.update({"policy": {"implementation": "open('cases.json').read()"}}),
            lambda value: value["filters"].append({"conditions": []}),
            lambda value: value["constant_if_rules"][0]["conditions"][0].update({"op": "exec"}),
            lambda value: value["constant_if_rules"][0]["conditions"][0].update({"value": "x" * 129}),
            lambda value: value["token_similarity_rules"].clear() or value["constant_if_rules"].clear() or value["conditional_similarity_rules"].clear(),
        ]
        for mutate in mutators:
            with self.subTest(mutate=mutate):
                with self.assertRaises(RuntimeError):
                    exercise_mock_pipelines(
                        ResponseMock(self.bundle["investigation"], policy_mutator=mutate),
                        self.active_source, self.bundle,
                    )

    def test_condition_operator_reads_only_its_fixed_table_column(self):
        response = largest_valid_policy_response()
        row = response["constant_if_rules"][0]["conditions"][0]
        row.update({"op": "in", "value": "ignored bounded cell", "values": ["supported"]})
        policy = compile_policy_tables(response)
        compiled = policy["score_rules"][3]["conditions"][0]
        self.assertEqual({"field": "item.failure_condition", "op": "in", "values": ["supported"]}, compiled)

    def test_schema_validator_rejects_nonfinite_or_wrong_numbers(self):
        response = largest_valid_policy_response()
        response["version"] = True
        with self.assertRaisesRegex(RuntimeError, "integer"):
            validate_schema(response, POLICY_TABLE_SCHEMA)


if __name__ == "__main__":
    unittest.main()
