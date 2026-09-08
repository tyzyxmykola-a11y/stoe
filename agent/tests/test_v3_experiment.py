from __future__ import annotations

import json
import unittest
from pathlib import Path

from stoe_agent.response_rehearsal import (
    CONDITIONS,
    POLICY_MAX_TOKENS,
    POLICY_SEEDS,
    PROPOSAL_MAX_TOKENS,
    PROPOSAL_SEEDS,
)
from stoe_agent.selector_loader import sha256_file
from stoe_agent.structural_experiment import validate_unseen_cases


class V3FreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.v3_root = cls.root / "agent/structural_input_experiment_v3"

    def test_v3_cases_are_independent_and_not_prior_holdout_renames(self):
        v1 = json.loads((self.root / "agent/structural_input_experiment/cases.json").read_text(encoding="utf-8"))
        v2 = json.loads((self.root / "agent/structural_input_experiment_v2/cases.json").read_text(encoding="utf-8"))
        v3 = json.loads((self.v3_root / "cases.json").read_text(encoding="utf-8"))
        structure = validate_unseen_cases(v3)
        self.assertEqual(12, structure["independent_case_count"])
        old_names = {c["name"] for c in v1 + v2}
        old_families = {c["family"] for c in v1 + v2}
        old_content = {i["content"] for c in v1 + v2 for i in c["items"]}
        self.assertTrue(old_names.isdisjoint({c["name"] for c in v3}))
        self.assertTrue(old_families.isdisjoint({c["family"] for c in v3}))
        self.assertTrue(old_content.isdisjoint({i["content"] for c in v3 for i in c["items"]}))

    def test_frozen_v3_settings_match_qualified_response_contract(self):
        spec = json.loads((self.v3_root / "experiment_spec.json").read_text(encoding="utf-8"))
        generation = spec["generation"]
        self.assertEqual(list(CONDITIONS), spec["condition_order"])
        self.assertEqual(PROPOSAL_SEEDS[0], generation["proposal_seed"])
        self.assertEqual(POLICY_SEEDS[0], generation["policy_seed"])
        self.assertEqual(PROPOSAL_MAX_TOKENS, generation["proposal_max_output_tokens"])
        self.assertEqual(POLICY_MAX_TOKENS, generation["policy_max_output_tokens"])
        self.assertEqual(0, generation["retry_count"])

    def test_all_frozen_v3_hashes_match(self):
        spec = json.loads((self.v3_root / "experiment_spec.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["benchmark"]["sha256"], sha256_file(self.v3_root / "cases.json"))
        harness = self.root / spec["qualified_harness"]["manifest"]
        self.assertEqual(spec["qualified_harness"]["sha256"], sha256_file(harness))
        manifest = json.loads((self.v3_root / spec["freeze_manifest"]).read_text(encoding="utf-8"))
        for relative, expected in manifest["critical_file_sha256"].items():
            self.assertEqual(expected, sha256_file(self.root / relative), relative)


if __name__ == "__main__":
    unittest.main()
