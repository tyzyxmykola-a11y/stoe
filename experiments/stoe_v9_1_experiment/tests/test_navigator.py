from __future__ import annotations

import unittest
from pathlib import Path

from stoe_v9.graph import reverse_semantic
from stoe_v9.navigator import (
    ObserverAwareNavigator,
    QueryBlindNavigator,
    structural_score,
)
from stoe_v9.tasks import build_task_graph, load_tasks


ROOT = Path(__file__).resolve().parents[1]


class NavigatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = {task.id: task for task in load_tasks(ROOT / "development_tasks/development_v1.json")}

    def test_recent_dead_end_does_not_automatically_beat_reactivated_failure(self):
        task = self.tasks["dev-permit-reopen"]
        graph, state = build_task_graph(task)
        result = ObserverAwareNavigator(graph).select(state, limit=4)
        self.assertEqual(result.refs[0], "IP_00002")
        focal = next(trace for trace in result.traces if trace.candidate_ip == "IP_00002")
        recent = next(trace for trace in result.traces if trace.candidate_ip == "IP_00005")
        self.assertGreater(focal.final_score, recent.final_score)

    def test_recent_information_can_remain_preferred_without_change(self):
        task = self.tasks["dev-recent-correct"]
        graph, state = build_task_graph(task)
        result = ObserverAwareNavigator(graph).select(state, limit=4)
        self.assertEqual(result.refs[0], "IP_00005")

    def test_domain_root_never_consumes_artifact_slot(self):
        task = self.tasks["dev-permit-reopen"]
        graph, state = build_task_graph(task)
        result = ObserverAwareNavigator(graph).select(state, limit=4)
        self.assertEqual(result.realized_artifact_count, 4)
        self.assertNotIn("IP_00000", result.refs)
        self.assertTrue(all(graph.nodes[ref].visible for ref in result.refs))
        root_trace = next(trace for trace in result.traces if trace.candidate_ip == "IP_00000")
        self.assertFalse(root_trace.eligible)
        self.assertFalse(root_trace.selected)

    def test_rejected_by_direction_has_explicit_reverse_meaning(self):
        self.assertEqual(
            reverse_semantic("rejected_by", "incoming"),
            "find_hypotheses_rejected_because_of",
        )
        outgoing = structural_score([{"type": "rejected_by", "direction": "outgoing"}])
        incoming = structural_score([{"type": "rejected_by", "direction": "incoming"}])
        self.assertGreater(incoming, outgoing)

    def test_longer_paths_do_not_win_by_accumulation(self):
        one = structural_score([{"type": "invalidates", "direction": "outgoing"}])
        three = structural_score([
            {"type": "invalidates", "direction": "outgoing"},
            {"type": "invalidates", "direction": "outgoing"},
            {"type": "invalidates", "direction": "outgoing"},
        ])
        self.assertLess(three, one)

    def test_query_blind_reproduces_locality_and_observer_aware_corrects_it(self):
        task = self.tasks["dev-library-compat"]
        graph, state = build_task_graph(task)
        blind = QueryBlindNavigator(graph).select(state, limit=4)
        aware = ObserverAwareNavigator(graph).select(state, limit=4)
        self.assertEqual(blind.refs[0], "IP_00005")
        self.assertEqual(aware.refs[0], "IP_00002")

    def test_randomized_edges_change_navigation_not_nodes(self):
        task = self.tasks["dev-library-compat"]
        graph, state = build_task_graph(task)
        randomized = graph.randomized_transition_endpoints(9)
        self.assertEqual(set(graph.nodes), set(randomized.nodes))
        self.assertEqual(
            sorted(node.content for node in graph.nodes.values()),
            sorted(node.content for node in randomized.nodes.values()),
        )
        original = ObserverAwareNavigator(graph).select(state, limit=4)
        changed = ObserverAwareNavigator(randomized).select(state, limit=4)
        original_paths = [trace.path for trace in original.traces if trace.selected]
        changed_paths = [trace.path for trace in changed.traces if trace.selected]
        self.assertNotEqual(original_paths, changed_paths)


if __name__ == "__main__":
    unittest.main()
