"""
Slice 1 self-test: verifies the invariants from PLAN.md.

Run from project root:
    python -m tests.test_slice1

Slice 1 checkpoint per PLAN.md:
    "graph persists across runs, no endpoint can delete a node."

This test exercises:
    I1. Monotonic growth (no public deletion method exists)
    I2. Severance, not deletion (severed edges remain in self.edges)
    I3. Failure conservation (Ghost nodes + failed_from edges)
    I4. Topology-first retrieval (navigate_from / dead_end_query work
        independently of content matching)
    Persistence: nodes survive an InformationField restart
    Seed loader: loads stoe_seed.json into empty field, idempotent
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

# Make the parent package importable when running as a script
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from core.field import (
    InformationField,
    EDGE_TYPES,
    assert_no_deletion_methods,
)
from core.seed_loader import load_seed_if_empty


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

PASS = "[ok]"
FAIL = "[FAIL]"

results: list[tuple[bool, str]] = []

def check(cond: bool, label: str) -> None:
    results.append((bool(cond), label))
    print(f"  {PASS if cond else FAIL} {label}")

def section(title: str) -> None:
    # ASCII-only separator since some Windows consoles use cp1251
    print(f"\n=== {title} ===".encode("ascii", errors="replace").decode("ascii"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def run_tests() -> int:
    workdir = tempfile.mkdtemp(prefix="stoev3_slice1_")
    try:
        storage = os.path.join(workdir, "field_data.json")

        # I1: Static guard against deletion methods
        section("I1 - no public deletion methods exist")
        try:
            assert_no_deletion_methods()
            check(True, "InformationField has no public method matching delete/wipe/drop/purge")
        except AssertionError as e:
            check(False, f"deletion-method guard tripped: {e}")

        # I2: Severance preserves edges in self.edges
        section("I2 - severance, not deletion")
        f = InformationField(storage_path=storage)
        a = f.add_point("alpha")
        b = f.add_point("beta")
        eid = f.connect(a, b, edge_type="evolved_from")
        check(eid is not None, "connect returns an edge id")
        check(len(f.edges) == 1, "edge present after connect")

        sev_ok = f.sever(eid)
        check(sev_ok, "sever returns True")
        check(len(f.edges) == 1, "edge STILL present after sever (not removed)")
        check(f.edges[0].get("severed") is True, "edge marked severed=True")

        # Severed edge is excluded from default adjacency
        adj = f.get_adjacent(a)
        check(len(adj) == 0, "severed edge excluded from get_adjacent default")
        adj_inc = f.get_adjacent(a, include_severed=True)
        check(len(adj_inc) == 1, "severed edge included when include_severed=True")

        # I3: Failure conservation
        section("I3 - failure conservation")
        c = f.add_point("gamma")
        ghost_id = f.add_failed(c, reason="LLM API timeout", operator="^")
        check(ghost_id in f.nodes, "ghost node added")
        check(f.nodes[ghost_id]["category"] == "Ghost", "ghost categorized as Ghost")
        check(f.nodes[ghost_id]["metadata"].get("failed") is True,
              "ghost metadata.failed = True")
        failed_edges = [e for e in f.edges if e["type"] == "failed_from" and not e.get("severed")]
        check(len(failed_edges) == 1, "exactly one active failed_from edge after add_failed")
        de = f.dead_end_query(c)
        check(len(de) == 1 and de[0]["edge_type"] == "failed_from",
              "dead_end_query returns the failed_from neighbour")

        # I4: Topology-first retrieval works without content matching
        section("I4 - topology-first retrieval")
        # Build a small graph: root → m1 → m2, root → m3 (with failed_from m4)
        root = f.add_point("zeta-root")
        m1 = f.add_point("zeta-m1")
        m2 = f.add_point("zeta-m2")
        m3 = f.add_point("zeta-m3")
        f.connect(root, m1, edge_type="evolved_from")
        f.connect(m1, m2, edge_type="evolved_from")
        f.connect(root, m3, edge_type="connected_to")
        m4 = f.add_failed(root, "tried branch m4, contradicts m1")

        sub = f.navigate_from(root, depth=2, include_failed=True)
        node_ids = set(sub.keys())
        check(root in node_ids, "navigate depth=2: root in subgraph")
        check(m1 in node_ids and m3 in node_ids, "navigate depth=2: depth-1 children present")
        check(m2 in node_ids, "navigate depth=2: depth-2 grandchild present")
        check(m4 in node_ids, "navigate depth=2: failed_from neighbour included")

        # Without failed: m4 excluded
        sub_nf = f.navigate_from(root, depth=2, include_failed=False)
        check(m4 not in sub_nf, "navigate depth=2 include_failed=False: ghost excluded")

        # Path query
        path = f.path_query(root, m2)
        check(path["found"], "path_query finds root → m2 path")
        check(path["length"] == 2, "path length is 2 hops")

        # Persistence: data survives a restart
        section("Persistence across restart")
        node_count_before = len(f.nodes)
        edge_count_before = len(f.edges)
        del f
        f2 = InformationField(storage_path=storage)
        check(len(f2.nodes) == node_count_before,
              f"nodes preserved across restart ({node_count_before})")
        check(len(f2.edges) == edge_count_before,
              f"edges preserved across restart ({edge_count_before})")
        check(any(e.get("severed") for e in f2.edges),
              "severed edges preserved across restart")
        check(any(n.get("category") == "Ghost" for n in f2.nodes.values()),
              "ghost nodes preserved across restart")

        # Cold-start lookup is available but private-flagged
        section("Cold-start retrieval discipline")
        check(hasattr(f2, "cold_start_lookup"), "cold_start_lookup is the public name")
        check(not hasattr(f2, "search"),
              "no public 'search' method (similarity is intentionally not exposed)")

        # Seed loader: loads into empty field, idempotent on non-empty field
        section("Seed loader")
        seed_storage = os.path.join(workdir, "seed_field.json")
        empty_field = InformationField(storage_path=seed_storage)
        result = load_seed_if_empty(empty_field)
        if result["reason"] == "no_seed_file":
            check(False,
                  f"seed file not found at {result.get('expected_at')!r} — "
                  f"this test must run from project root")
        else:
            check(result["loaded"], "seed loaded into empty field")
            check(result["nodes_added"] >= 30,
                  f"≥30 seed nodes loaded (got {result['nodes_added']})")
            check(len(empty_field.nodes) == result["nodes_added"],
                  "field node count matches seed node count")
            check(result["edges_added"] >= 100,
                  f"≥100 seed edges loaded (got {result['edges_added']})")

            # Idempotency
            result2 = load_seed_if_empty(empty_field)
            check(not result2["loaded"], "second seed load is no-op")
            check(result2["reason"] == "field_not_empty",
                  "no-op reason is field_not_empty")

        # Edge type vocabulary check
        section("Edge type vocabulary (paper 4 5.1)")
        for required in ("failed_from", "contradicts", "evaluates",
                         "extends", "adjacent_to"):
            check(required in EDGE_TYPES,
                  f"required edge type {required!r} present in EDGE_TYPES")

        # ---- summary ----
        section("Summary")
        passed = sum(1 for ok, _ in results if ok)
        total = len(results)
        print(f"  {passed}/{total} checks passed")
        return 0 if passed == total else 1

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_tests())
