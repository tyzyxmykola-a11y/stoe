from __future__ import annotations

import unittest
import re
from pathlib import Path

from stoe_v9.tasks import build_task_graph, load_tasks


ROOT = Path(__file__).resolve().parents[1]


class TaskTests(unittest.TestCase):
    def test_development_and_pilot_are_disjoint_and_structurally_complete(self):
        development = load_tasks(ROOT / "development_tasks/development_v1.json")
        pilot = load_tasks(ROOT / "pilot_tasks/pilot_v1.json")
        self.assertFalse({task.id for task in development} & {task.id for task in pilot})
        for task in development + pilot:
            graph, state = build_task_graph(task)
            self.assertIn("IP_00001", graph.nodes)
            self.assertEqual(state.ref, "IP_00001")
            self.assertIn("IP_00006", graph.nodes)
            self.assertEqual(graph.nodes["IP_00006"].kind, "evaluation")
            self.assertGreaterEqual(len(graph.eligible_refs()), 4)

    def test_task_answer_tokens_are_not_internal_refs(self):
        paths = [
            ROOT / "development_tasks/development_v1.json",
            ROOT / "pilot_tasks/pilot_v1.json",
            ROOT / "benchmarks/frozen_primary_v1.json",
        ]
        for path in paths:
            for task in load_tasks(path):
                self.assertFalse(task.expected_answer.startswith("IP_"))
                self.assertNotIn("identifier", task.question.lower())

    def test_primary_is_disjoint_balanced_and_not_renamed_templates(self):
        development = load_tasks(ROOT / "development_tasks/development_v1.json")
        pilot = load_tasks(ROOT / "pilot_tasks/pilot_v1.json")
        primary = load_tasks(ROOT / "benchmarks/frozen_primary_v1.json")
        prior_ids = {task.id for task in development + pilot}
        self.assertEqual(len(primary), 18)
        self.assertFalse(prior_ids & {task.id for task in primary})
        families = {}
        normalized_questions = set()
        normalized_focals = set()
        for task in primary:
            families.setdefault(task.family, []).append(task)
            normalize = lambda value: re.sub(r"[^a-z]+", " ", value.lower()).strip()
            self.assertNotIn(normalize(task.question), normalized_questions)
            self.assertNotIn(normalize(task.focal["content"]), normalized_focals)
            normalized_questions.add(normalize(task.question))
            normalized_focals.add(normalize(task.focal["content"]))
        self.assertEqual(len(families), 9)
        self.assertTrue(all(len(tasks) == 2 for tasks in families.values()))
        self.assertTrue(all({task.subset for task in tasks} == {"topology_targeted", "negative_control"} for tasks in families.values()))

    def test_current_state_ip_contains_position_change_and_recent_evidence(self):
        task = load_tasks(ROOT / "development_tasks/development_v1.json")[0]
        graph, state = build_task_graph(task)
        content = graph.nodes[state.ref].content
        self.assertIn("CURRENT_REASONING_REF: IP_00005", content)
        self.assertIn("RECENT_EVIDENCE:", content)
        self.assertIn(task.state_change["content"], content)
        self.assertEqual(state.traversal_history, ["IP_00005", "IP_00006"])


if __name__ == "__main__":
    unittest.main()
