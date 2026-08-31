from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from stoe_v9.graph import InformationGraph
from stoe_v9.models import InformationPoint, RetrievalResult
from stoe_v9.providers import DeterministicMockProvider, GenerationParams, compose_user_content
from stoe_v9.retrieval import (
    DeterministicHashEmbedder,
    extract_memory_refs,
    serialize_memory,
)
from stoe_v9.runner import ALL_CONDITIONS, Condition, ExperimentRunner
from stoe_v9.seed import canonical_ref, load_canonical_seed, load_seed_into_graph, seed_id_by_name
from stoe_v9.tasks import load_tasks


ROOT = Path(__file__).resolve().parents[1]
LIMIT = 5000
HUGE = "oversized semantic evidence " * 600


class V91SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_tasks(ROOT / "development_tasks/development_v1.json")[0]
        cls.runner = ExperimentRunner(
            provider=DeterministicMockProvider({cls.task.id: cls.task.expected_answer}),
            params=GenerationParams(model="mock"),
            embedder=DeterministicHashEmbedder(),
        )

    def graph_for(self, contents: list[str]) -> tuple[InformationGraph, RetrievalResult]:
        graph = InformationGraph()
        refs = []
        for index, content in enumerate(contents, start=1):
            ref = f"IP_{index:05d}"
            refs.append(ref)
            graph.add_node(InformationPoint(
                ref=ref,
                content=content,
                kind="reasoning",
                metadata={"origin": "runtime_reasoning", "relation_context": "supports"},
            ))
        return graph, RetrievalResult(refs, "test_frozen_selection", [1.0] * len(refs),
                                      realized_artifact_count=len(refs))

    def serialize(self, contents: list[str]):
        graph, selected = self.graph_for(contents)
        value = serialize_memory(graph, selected, typed=True, max_chars=LIMIT)
        exact_user = compose_user_content("FROZEN_PROMPT", value.text)
        exact_memory = exact_user.split("MEMORY_CONTEXT:\n", 1)[1]
        self.assertEqual(extract_memory_refs(exact_memory), selected.refs)
        return value

    def assert_four(self, value):
        self.assertEqual(value.selected_artifact_count, 4)
        self.assertEqual(value.model_visible_artifact_count, 4)
        self.assertEqual(len(set(value.model_visible_memory_refs)), 4)
        self.assertLessEqual(value.serialized_memory_char_count, LIMIT)

    # TEST 1
    def test_01_four_normal_runtime_artifacts_reach_exact_final_prompt(self):
        value = self.serialize(["normal evidence"] * 4)
        self.assert_four(value)

    # TESTS 2-5
    def test_02_oversized_artifact_position_1_keeps_later_artifacts(self):
        value = self.serialize([HUGE, "two", "three", "four"])
        self.assert_four(value)
        self.assertTrue(value.artifacts[0].truncated)

    def test_03_oversized_artifact_position_2_keeps_later_artifacts(self):
        value = self.serialize(["one", HUGE, "three", "four"])
        self.assert_four(value)
        self.assertTrue(value.artifacts[1].truncated)

    def test_04_oversized_artifact_position_3_keeps_later_artifacts(self):
        value = self.serialize(["one", "two", HUGE, "four"])
        self.assert_four(value)
        self.assertTrue(value.artifacts[2].truncated)

    def test_05_oversized_artifact_position_4_is_visible(self):
        value = self.serialize(["one", "two", "three", HUGE])
        self.assert_four(value)
        self.assertTrue(value.artifacts[3].truncated)

    # TEST 6
    def test_06_all_four_oversized_are_bounded_and_visible(self):
        value = self.serialize([HUGE] * 4)
        self.assert_four(value)
        self.assertTrue(all(item.truncated for item in value.artifacts))
        self.assertEqual(value.text.count("[CONTENT_TRUNCATED]"), 4)

    def assert_actual_seed_node(self, name: str):
        raw = load_canonical_seed()
        graph = InformationGraph()
        load_seed_into_graph(graph, mode="native")
        seed_ref = canonical_ref(seed_id_by_name(raw, name))
        later = []
        for index in range(1, 4):
            ref = f"IP_{index:05d}"
            later.append(ref)
            graph.add_node(InformationPoint(
                ref=ref, content=f"later runtime artifact {index}", kind="reasoning",
                metadata={"origin": "runtime_reasoning", "relation_context": "supports"},
            ))
        result = RetrievalResult([seed_ref, *later], "frozen", [1.0] * 4,
                                 realized_artifact_count=4)
        value = serialize_memory(graph, result, typed=True, max_chars=LIMIT)
        self.assert_four(value)
        self.assertEqual(value.model_visible_memory_refs, [seed_ref, *later])
        self.assertTrue(value.artifacts[0].truncated)

    # TESTS 7-11
    def test_07_actual_seed_three_foundational_laws(self):
        self.assert_actual_seed_node("SToE: Three Foundational Laws")

    def test_08_actual_seed_algorithms_ideas_ai(self):
        self.assert_actual_seed_node("SToE 2021: Algorithms, Ideas & AI")

    def test_09_actual_seed_ai_architectural_gap(self):
        self.assert_actual_seed_node("AI Architectural Gap (Derivation)")

    def test_10_actual_seed_autoinjection_mapping_class(self):
        self.assert_actual_seed_node("Autoinjection: 4th Mapping Class")

    def test_11_actual_seed_cognitive_architecture(self):
        self.assert_actual_seed_node("SToE as Cognitive Architecture")

    # TEST 12
    def test_12_total_memory_never_exceeds_5000(self):
        cases = [["x"] * 4, [HUGE, "x", "y", "z"], [HUGE] * 4]
        self.assertTrue(all(self.serialize(case).serialized_memory_char_count <= LIMIT for case in cases))

    # TEST 13
    def test_13_selected_and_visible_counts_are_independent_records(self):
        row, _ = self.runner._run_task(self.task, Condition.BM25_MEMORY, typed_plan=None)
        self.assertIn("selected_artifact_count", row)
        self.assertIn("model_visible_artifact_count", row)
        self.assertIn("selected_artifact_refs", row)
        self.assertIn("model_visible_memory_refs", row)
        self.assertEqual(row["model_visible_memory_refs"], extract_memory_refs(row["exact_serialized_memory"]))

    # TEST 14
    def test_14_uuid_internal_id_cannot_satisfy_exact_answer(self):
        bad = "608581ea-7009-5012-b015-14ffa023c95a"
        runner = ExperimentRunner(
            provider=DeterministicMockProvider({self.task.id: bad}),
            params=GenerationParams(model="mock"), embedder=DeterministicHashEmbedder(),
        )
        row, _ = runner._run_task(self.task, Condition.NO_MEMORY, typed_plan=None)
        self.assertFalse(row["exact_success"])
        self.assertTrue(row["internal_id_contamination"])

    def condition_value(self, condition: Condition, typed_plan=None):
        _, _, result, context = self.runner._retrieve(self.task, condition, typed_plan)
        final_memory = compose_user_content("FROZEN_PROMPT", context).split("MEMORY_CONTEXT:\n", 1)[1]
        if condition != Condition.NO_MEMORY:
            self.assertEqual(extract_memory_refs(final_memory), result.refs)
            self.assertEqual(len(result.refs), 4)
            self.assertLessEqual(len(context), LIMIT)
        return result, context

    # TESTS 15-16
    def test_15_native_and_no_seed_have_identical_total_limit(self):
        for condition in (Condition.OBSERVER_AWARE_STOE_TOPOLOGY,
                          Condition.OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED):
            _, context = self.condition_value(condition)
            self.assertLessEqual(len(context), self.runner.max_memory_chars)
        self.assertEqual(self.runner.max_memory_chars, LIMIT)

    def test_16_native_and_chimera_have_identical_total_limit(self):
        for condition in (Condition.OBSERVER_AWARE_STOE_TOPOLOGY,
                          Condition.OBSERVER_AWARE_STOE_CHIMERA_SEED):
            _, context = self.condition_value(condition)
            self.assertLessEqual(len(context), self.runner.max_memory_chars)
        self.assertEqual(self.runner.max_memory_chars, LIMIT)

    # TESTS 17-20
    def test_17_dense_semantic_has_four_visible_artifacts(self):
        self.condition_value(Condition.DENSE_SEMANTIC_MEMORY)

    def test_18_bm25_has_four_visible_artifacts(self):
        self.condition_value(Condition.BM25_MEMORY)

    def test_19_query_blind_has_four_visible_artifacts(self):
        self.condition_value(Condition.QUERY_BLIND_TOPOLOGY)

    def test_20_observer_aware_has_four_visible_artifacts(self):
        self.condition_value(Condition.OBSERVER_AWARE_STOE_TOPOLOGY)

    # TEST 21
    def test_21_all_preregistered_ablations_have_four_visible_artifacts(self):
        typed_plan = None
        for condition in ALL_CONDITIONS:
            if condition == Condition.NO_MEMORY:
                continue
            result, _ = self.condition_value(condition, typed_plan)
            if condition == Condition.OBSERVER_AWARE_STOE_TOPOLOGY:
                typed_plan = result

    # TEST 22
    def test_22_serializer_has_no_condition_specific_branch(self):
        source = inspect.getsource(serialize_memory)
        self.assertNotIn("Condition", source)
        self.assertNotIn("STOE", source.upper())
        self.assertNotIn("condition", inspect.signature(serialize_memory).parameters)

    # TEST 23: selected refs copied from the corresponding frozen v9 trace row.
    def test_23_representative_frozen_v9_selected_refs_match_before_serialization(self):
        task = load_tasks(ROOT / "benchmarks/frozen_primary_v1.json")[0]
        expected = {
            Condition.BM25_MEMORY: ["IP_00004", "IP_00006", "SEED_104b70c3e43ee10d", "SEED_57a01496da4fd547"],
            Condition.QUERY_BLIND_TOPOLOGY: ["IP_00005", "IP_00004", "IP_00003", "SEED_8ef484b35d78455f"],
            Condition.OBSERVER_AWARE_STOE_TOPOLOGY: ["IP_00002", "IP_00010", "SEED_8be9448ca5ee4525", "IP_00004"],
        }
        for condition, frozen_refs in expected.items():
            _, _, result, _ = self.runner._retrieve(task, condition)
            self.assertEqual(result.refs, frozen_refs, condition.value)

    # TESTS 24-25
    def test_24_oversized_truncation_is_deterministic(self):
        self.assertEqual(self.serialize([HUGE, "b", "c", "d"]).text,
                         self.serialize([HUGE, "b", "c", "d"]).text)

    def test_25_repeated_four_artifact_serialization_is_byte_identical(self):
        first = self.serialize([HUGE, "beta", HUGE, "delta"]).text.encode("utf-8")
        second = self.serialize([HUGE, "beta", HUGE, "delta"]).text.encode("utf-8")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
