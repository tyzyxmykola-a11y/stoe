from __future__ import annotations

import re
import unittest
from pathlib import Path

from stoe_v9.providers import DeterministicMockProvider, GenerationParams
from stoe_v9.retrieval import DeterministicHashEmbedder
from stoe_v9.runner import Condition, ExperimentRunner, UUID_RE
from stoe_v9.tasks import load_tasks


ROOT = Path(__file__).resolve().parents[1]


class AblationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_tasks(ROOT / "development_tasks/development_v1.json")[0]
        cls.runner = ExperimentRunner(
            provider=DeterministicMockProvider({cls.task.id: cls.task.expected_answer}),
            params=GenerationParams(model="mock"),
            embedder=DeterministicHashEmbedder(),
        )

    def test_typed_untyped_have_identical_plan_count_and_content(self):
        graph, state, typed, typed_context = self.runner._retrieve(
            self.task, Condition.OBSERVER_AWARE_STOE_TOPOLOGY
        )
        _, _, untyped, untyped_context = self.runner._retrieve(
            self.task, Condition.OBSERVER_AWARE_TOPOLOGY_UNTYPED, typed
        )
        self.assertEqual(typed.refs, untyped.refs)
        self.assertEqual(typed.realized_artifact_count, 4)
        self.assertEqual(untyped.realized_artifact_count, 4)
        scrub = lambda text: re.sub(r"RELATION_CONTEXT=[^;]+", "RELATION_CONTEXT=MASKED", text)
        self.assertEqual(scrub(typed_context), scrub(untyped_context))
        self.assertNotEqual(typed_context, untyped_context)

    def test_every_claimed_four_item_memory_exposes_four_eligible_artifacts(self):
        typed_plan = None
        for condition in Condition:
            if condition == Condition.NO_MEMORY:
                continue
            graph, _, result, _ = self.runner._retrieve(self.task, condition, typed_plan)
            if condition == Condition.OBSERVER_AWARE_STOE_TOPOLOGY:
                typed_plan = result
            self.assertEqual(result.realized_artifact_count, 4, condition.value)
            self.assertTrue(all(graph.nodes[ref].visible for ref in result.refs))

    def test_uuid_like_storage_ids_cannot_be_exact_answers(self):
        value = "608581ea-7009-5012-b015-14ffa023c95a"
        self.assertTrue(UUID_RE.fullmatch(value))
        self.assertNotEqual(value.upper(), self.task.expected_answer.upper())


if __name__ == "__main__":
    unittest.main()
