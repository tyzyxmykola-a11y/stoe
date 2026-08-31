from __future__ import annotations

import hashlib
import unittest
from collections import Counter
from pathlib import Path

from stoe_v9.navigator import ObserverAwareNavigator
from stoe_v9.providers import DeterministicMockProvider, GenerationParams
from stoe_v9.retrieval import DeterministicHashEmbedder, format_context
from stoe_v9.runner import Condition, ExperimentRunner, parse_response
from stoe_v9.seed import (
    CANONICAL_SEED_SHA256,
    SEED_PATH,
    canonical_ref,
    fold_seed,
    load_canonical_seed,
    seed_id_by_name,
    seed_relation_counts,
    seed_report,
    unfold_seed,
)
from stoe_v9.tasks import build_task_graph, load_tasks


ROOT = Path(__file__).resolve().parents[1]


class CanonicalSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = load_canonical_seed()
        cls.task = load_tasks(ROOT / "development_tasks/development_v1.json")[0]

    def test_canonical_seed_hash_and_counts_are_frozen(self):
        self.assertEqual(hashlib.sha256(SEED_PATH.read_bytes()).hexdigest(), CANONICAL_SEED_SHA256)
        report = seed_report(self.raw)
        self.assertEqual(report["core_ips"], 36)
        self.assertEqual(report["typed_relations"], 113)
        self.assertEqual(report["expressions"], 36)
        self.assertEqual(report["nonempty_descriptions"], 32)
        self.assertEqual(
            report["categories"],
            {"Catalyst": 5, "Fertilizer": 3, "Hidden Diamond": 3, "Mirror": 3, "Seed": 4, "Star": 18},
        )

    def test_fold_unfold_is_lossless(self):
        folded = fold_seed(self.raw)
        reconstructed = unfold_seed(folded)
        self.assertEqual(reconstructed, self.raw)
        self.assertEqual(len(reconstructed["nodes"]), 36)
        self.assertEqual(len(reconstructed["edges"]), 113)

    def test_seed_and_runtime_share_one_traversable_field(self):
        graph, state = build_task_graph(self.task, seed_mode="native")
        law = canonical_ref(seed_id_by_name(self.raw, "Law of Conservation"))
        paths = graph.reachable_paths(state.ref, max_depth=4)
        self.assertIn(law, paths)
        self.assertTrue(any(
            [step["type"] for step in path]
            == ["contains_change", "invalidates", "rejected_by", "instantiates"]
            for path in paths[law]
        ))
        reverse = graph.reachable_paths(law, max_depth=1)
        self.assertIn("IP_00002", reverse)
        self.assertEqual(reverse["IP_00002"][0][0]["direction"], "incoming")

    def test_unreachable_seed_nodes_are_not_dumped_into_context(self):
        graph, state = build_task_graph(self.task, seed_mode="native")
        nothing = canonical_ref(seed_id_by_name(self.raw, "Nothing (∅)"))
        self.assertNotIn(nothing, graph.reachable_paths(state.ref, max_depth=4))
        result = ObserverAwareNavigator(graph).select(state, limit=4)
        context = format_context(graph, result, typed=True, max_chars=5000)
        self.assertNotIn(nothing, result.refs)
        self.assertNotIn(nothing, context)
        self.assertEqual(len(result.refs), 4)
        self.assertLessEqual(sum(ref.startswith("SEED_") for ref in result.refs), 4)

    def test_without_seed_preserves_unrelated_budget(self):
        answers = {self.task.id: self.task.expected_answer}
        runner = ExperimentRunner(
            provider=DeterministicMockProvider(answers),
            params=GenerationParams(model="mock"),
            embedder=DeterministicHashEmbedder(),
        )
        native_graph, _, native, native_context = runner._retrieve(self.task, Condition.OBSERVER_AWARE_STOE_TOPOLOGY)
        absent_graph, _, absent, absent_context = runner._retrieve(self.task, Condition.OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED)
        self.assertEqual(native.realized_artifact_count, 4)
        self.assertEqual(absent.realized_artifact_count, 4)
        self.assertTrue(any(ref.startswith("SEED_") for ref in native_graph.nodes))
        self.assertFalse(any(ref.startswith("SEED_") for ref in absent_graph.nodes))
        native_runtime = {ref: node.content for ref, node in native_graph.nodes.items() if ref.startswith("IP_")}
        absent_runtime = {ref: node.content for ref, node in absent_graph.nodes.items() if ref.startswith("IP_")}
        self.assertEqual(native_runtime, absent_runtime)
        self.assertLessEqual(len(native_context), runner.max_memory_chars)
        self.assertLessEqual(len(absent_context), runner.max_memory_chars)

    def test_chimera_preserves_content_and_relation_type_counts(self):
        native_graph, native_state = build_task_graph(self.task, seed_mode="native")
        chimera_graph, chimera_state = build_task_graph(self.task, seed_mode="chimera")
        native_nodes = {ref: node.content for ref, node in native_graph.nodes.items() if ref.startswith("SEED_")}
        chimera_nodes = {ref: node.content for ref, node in chimera_graph.nodes.items() if ref.startswith("SEED_")}
        self.assertEqual(native_nodes, chimera_nodes)
        self.assertEqual(len(native_graph.eligible_refs()), len(chimera_graph.eligible_refs()))
        self.assertEqual(seed_relation_counts(native_graph), seed_relation_counts(chimera_graph))
        native_pairs = {(edge.source, edge.target, edge.relation) for edge in native_graph.edges if edge.source.startswith("SEED_") and edge.target.startswith("SEED_")}
        chimera_pairs = {(edge.source, edge.target, edge.relation) for edge in chimera_graph.edges if edge.source.startswith("SEED_") and edge.target.startswith("SEED_")}
        self.assertNotEqual(native_pairs, chimera_pairs)
        native = ObserverAwareNavigator(native_graph).select(native_state, limit=4)
        chimera = ObserverAwareNavigator(chimera_graph).select(chimera_state, limit=4)
        self.assertEqual(native.realized_artifact_count, chimera.realized_artifact_count)
        self.assertEqual(native.realized_artifact_count, 4)

    def test_trace_records_required_origins(self):
        graph, state = build_task_graph(self.task, seed_mode="native")
        result = ObserverAwareNavigator(graph).select(state, limit=4)
        allowed = {
            "canonical_seed", "runtime_reasoning", "failure_history",
            "evaluation", "state_change", "current_observer_state",
        }
        self.assertTrue(result.traces)
        self.assertTrue(all(trace.origin in allowed for trace in result.traces))
        self.assertEqual(
            next(trace.origin for trace in result.traces if trace.candidate_ip == "IP_00002"),
            "failure_history",
        )

    def test_seed_refs_are_separate_from_answers_but_allowed_as_citations(self):
        seed_ref = canonical_ref(next(iter(self.raw["nodes"])))
        parsed, error = parse_response(
            '{"answer":"DOMAIN_TOKEN","used_memory_refs":["' + seed_ref + '"],"confidence":0.8}',
            [seed_ref],
        )
        self.assertIsNone(error)
        self.assertEqual(parsed["answer"], "DOMAIN_TOKEN")
        self.assertEqual(parsed["used_memory_refs"], [seed_ref])


if __name__ == "__main__":
    unittest.main()
