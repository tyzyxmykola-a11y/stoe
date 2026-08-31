from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from core import CANONICAL_SEED_SHA256, FieldStore, structural_score


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP_ROOT = PLUGIN_ROOT.parents[1] / "tmp" / "stoe_plugin_tests"


class FieldStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = TEST_TEMP_ROOT / f"core_{uuid.uuid4().hex}.sqlite3"
        self.store = FieldStore(
            self.db_path,
            PLUGIN_ROOT / "assets" / "stoe_seed.json",
        )
        self.store.initialize()

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            (Path(str(self.db_path) + suffix)).unlink(missing_ok=True)

    def _failure_scenario(self):
        constraint = self.store.add_ip(
            content="The maintenance hatch is sealed during normal operation.",
            kind="constraint",
            session_id="case",
        )
        failed = self.store.add_ip(
            content="Route the cable through the maintenance hatch.",
            kind="hypothesis",
            origin="failure_history",
            outcome="failure",
            failure_condition="maintenance hatch sealed",
            session_id="case",
        )
        self.store.add_relation(
            source_ref=failed["ref"],
            target_ref=constraint["ref"],
            relation="rejected_by",
        )
        state = self.store.set_observer_state(
            goal="Route the cable after the hatch was opened",
            question="Which previously rejected route is now viable?",
            changed_constraints=["The maintenance hatch is now open."],
            invalidates_refs=[constraint["ref"]],
            session_id="case",
        )
        return constraint, failed, state

    def test_seed_identity_and_lossless_fold_unfold(self) -> None:
        status = self.store.status()
        self.assertEqual(status["canonical_seed"]["sha256"], CANONICAL_SEED_SHA256)
        self.assertEqual(status["canonical_seed"]["core_ips"], 36)
        self.assertEqual(status["canonical_seed"]["typed_relations"], 113)
        self.assertEqual(status["nodes_by_origin"]["canonical_seed"], 37)
        self.assertTrue(status["fold_unfold_lossless"])

    def test_directional_failure_reactivation(self) -> None:
        _, failed, state = self._failure_scenario()
        result = self.store.navigate(
            observer_state_ref=state["observer_state_ref"], include_seed=False, limit=2
        )
        self.assertIn(failed["ref"], result["selected_refs"])
        trace = self.store.get_retrieval_trace(run_id=result["run_id"], limit=20)
        focal = next(item for item in trace["candidate_page"] if item["candidate_ip"] == failed["ref"])
        self.assertEqual(focal["edge_types"], ["contains_change", "invalidates", "rejected_by"])
        self.assertEqual(focal["edge_directions"], ["outgoing", "outgoing", "incoming"])
        self.assertEqual(focal["state_change_score"], 1.0)
        self.assertEqual(focal["failure_relevance_score"], 1.0)

    def test_long_paths_do_not_accumulate_priority(self) -> None:
        strong = {"type": "invalidates", "direction": "outgoing"}
        self.assertGreater(structural_score([strong]), structural_score([strong, strong]))
        self.assertGreater(structural_score([strong]), structural_score([strong, strong, strong]))

    def test_unreachable_seed_is_not_dumped(self) -> None:
        state = self.store.set_observer_state(goal="Solve an unrelated local task", session_id="isolated")
        result = self.store.navigate(observer_state_ref=state["observer_state_ref"], include_seed=True)
        self.assertEqual(result["selected_refs"], [])

    def test_seed_and_runtime_share_reachable_field_without_origin_bonus(self) -> None:
        runtime = self.store.add_ip(
            content="Retain the rejected cable route for later reconsideration.",
            kind="hypothesis",
            session_id="bridge",
        )
        seed_ref = "SEED_8be9448ca5ee4525"
        self.store.add_relation(
            source_ref=runtime["ref"], target_ref=seed_ref, relation="applies_core"
        )
        state = self.store.set_observer_state(
            goal="Inspect why rejected reasoning was retained",
            recent_refs=[runtime["ref"]],
            session_id="bridge",
        )
        result = self.store.navigate(
            observer_state_ref=state["observer_state_ref"], include_seed=True, max_depth=3, limit=4
        )
        self.assertIn(runtime["ref"], result["selected_refs"])
        self.assertIn(seed_ref, result["selected_refs"])
        seed_item = next(item for item in result["selected_items"] if item["ref"] == seed_ref)
        self.assertEqual(seed_item["origin"], "canonical_seed")

    def test_serialization_caps_and_selection_integrity(self) -> None:
        long_ip = self.store.add_ip(
            content="constraint change " * 500,
            kind="observation",
            session_id="caps",
        )
        state = self.store.set_observer_state(
            goal="Use the changed constraint", recent_refs=[long_ip["ref"]], session_id="caps"
        )
        result = self.store.navigate(
            observer_state_ref=state["observer_state_ref"],
            include_seed=False,
            limit=1,
            per_item_chars=300,
            total_chars=500,
        )
        audit = result["serialization"]
        self.assertLessEqual(audit["actual_content_chars"], 500)
        self.assertTrue(audit["selection_serialization_match"])
        self.assertEqual(audit["visible_count"], 1)

    def test_evaluation_is_reachable_for_later_reasoning(self) -> None:
        result_ip = self.store.add_ip(
            content="The cable route succeeded after opening the hatch.",
            kind="result",
            outcome="success",
            session_id="evaluation",
        )
        evaluation = self.store.record_evaluation(
            evaluates_ref=result_ip["ref"],
            content="Evaluation confirms the opened-hatch route succeeds.",
            outcome="success",
            session_id="evaluation",
        )
        evaluation_ref = evaluation["evaluation"]["ref"]
        state = self.store.set_observer_state(
            goal="Use the confirmed route",
            recent_refs=[evaluation_ref],
            session_id="evaluation",
        )
        navigation = self.store.navigate(
            observer_state_ref=state["observer_state_ref"], include_seed=False, limit=2
        )
        self.assertIn(evaluation_ref, navigation["selected_refs"])

    def test_counterfactual_context_removes_only_focal_ip(self) -> None:
        _, failed, state = self._failure_scenario()
        replay = self.store.prepare_counterfactual_contexts(
            observer_state_ref=state["observer_state_ref"],
            focal_ip_ref=failed["ref"],
            include_seed=False,
            limit=2,
        )
        self.assertIn(failed["ref"], replay["with_ip"]["selected_refs"])
        self.assertNotIn(failed["ref"], replay["without_ip"]["selected_refs"])
        self.assertEqual(replay["retrieval_effect"], "RETRIEVAL_CONTEXT_CHANGED")
        self.assertEqual(replay["causal_status"], "REPLAY_REQUIRED")


if __name__ == "__main__":
    unittest.main()
