from __future__ import annotations

import json
import unittest
from pathlib import Path

from stoe_v9.providers import DeterministicMockProvider, GenerationParams
from stoe_v9.retrieval import DeterministicHashEmbedder
from stoe_v9.runner import ALL_CONDITIONS, ExperimentRunner, parse_response
from stoe_v9.tasks import load_tasks


ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def test_response_separates_answer_and_internal_refs(self):
        raw = json.dumps({
            "answer": "DOMAIN_TOKEN",
            "used_memory_refs": ["IP_00002", "bad", "IP_99999"],
            "confidence": 0.8,
        })
        parsed, error = parse_response(raw, ["IP_00002"])
        self.assertIsNone(error)
        self.assertEqual(parsed["answer"], "DOMAIN_TOKEN")
        self.assertEqual(parsed["used_memory_refs"], ["IP_00002"])

    def test_mock_integration_captures_all_conditions_and_traces(self):
        tasks = load_tasks(ROOT / "development_tasks/development_v1.json")[:1]
        provider = DeterministicMockProvider({tasks[0].id: tasks[0].expected_answer})
        result = ExperimentRunner(
            provider=provider,
            params=GenerationParams(model="mock"),
            embedder=DeterministicHashEmbedder(),
        ).run(tasks, ALL_CONDITIONS, counterfactuals=False)
        self.assertEqual(len(result["results"]), len(ALL_CONDITIONS))
        self.assertTrue(all(row["exact_success"] for row in result["results"]))
        aware = next(row for row in result["results"] if row["condition"] == "OBSERVER_AWARE_STOE_TOPOLOGY")
        self.assertTrue(aware["navigation_trace"])
        self.assertEqual(aware["focal_ip_rank"], 1)
        self.assertTrue(all("canonical_tie_key" in trace for trace in aware["navigation_trace"]))

    def test_counterfactuals_capture_all_preregistered_interventions(self):
        tasks = load_tasks(ROOT / "development_tasks/development_v1.json")[:1]
        result = ExperimentRunner(
            provider=DeterministicMockProvider({tasks[0].id: tasks[0].expected_answer}),
            params=GenerationParams(model="mock"),
            embedder=DeterministicHashEmbedder(),
        ).run(tasks, ALL_CONDITIONS, counterfactuals=True)
        replay = result["counterfactual_replays"][0]
        self.assertEqual(
            {item["intervention"] for item in replay["interventions"]},
            {
                "REMOVE_FOCAL_FAILED_IP", "REMOVE_STATE_CHANGE_IP",
                "REMOVE_CRITICAL_TYPED_RELATION", "RANDOMIZE_CRITICAL_EDGES",
                "REMOVE_QUERY_RANKING",
            },
        )
        self.assertTrue(all(item["navigation_trace"] for item in replay["interventions"]))
        self.assertTrue(all("model_response_raw" in item for item in replay["interventions"]))


if __name__ == "__main__":
    unittest.main()
