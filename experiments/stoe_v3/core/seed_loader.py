"""
Seed Loader
===========
Loads `seed/stoe_seed.json` into an empty InformationField. Idempotent —
once the field has any nodes, the loader is a no-op. The seed represents
the permanent SToE ontology and is never wiped (per PLAN.md invariant 5).

Why a separate loader (not a method on InformationField)
--------------------------------------------------------
The field class is the data substrate. The loader is policy: "what counts
as the starting state of a fresh field." Keeping them apart means we can
evolve seed semantics (e.g., re-seeding from a different ontology in a
future experiment) without modifying the field invariants.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .field import InformationField


def load_seed_if_empty(
    field: InformationField,
    seed_path: Optional[str] = None,
) -> dict:
    """
    Load the seed into `field` iff the field is empty. Returns a dict
    summarizing what happened.

    Behaviour:
      - If `field.nodes` is non-empty: no-op. Returns {'loaded': False,
        'reason': 'field_not_empty', ...}.
      - If `seed_path` is missing or the file does not exist: no-op.
        Returns {'loaded': False, 'reason': 'no_seed_file', ...}.
      - Otherwise: copies seed nodes and edges into the field, preserving
        their original IDs so that subsequent sessions can reference seed
        points stably across runs.
    """
    if seed_path is None:
        # Default: ../seed/stoe_seed.json relative to this module
        here = os.path.dirname(__file__)
        seed_path = os.path.normpath(os.path.join(here, "..", "seed", "stoe_seed.json"))

    if field.nodes:
        return {
            "loaded": False,
            "reason": "field_not_empty",
            "existing_nodes": len(field.nodes),
            "existing_edges": len(field.edges),
        }

    if not os.path.exists(seed_path):
        return {
            "loaded": False,
            "reason": "no_seed_file",
            "expected_at": seed_path,
        }

    with open(seed_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    seed_nodes = data.get("nodes", {})
    seed_edges = data.get("edges", [])

    # Insert nodes verbatim (preserve seed IDs).
    for nid, node in seed_nodes.items():
        # Defensive copy + ensure id field matches the dict key.
        n = dict(node)
        n["id"] = nid
        field.nodes[nid] = n

    # Insert edges verbatim, but only when both endpoints exist.
    skipped_edges = 0
    for e in seed_edges:
        if e.get("source") in field.nodes and e.get("target") in field.nodes:
            field.edges.append(dict(e))
        else:
            skipped_edges += 1

    field._save()  # noqa — internal save is the seed's persistence event

    return {
        "loaded": True,
        "reason": "seed_applied",
        "nodes_added": len(seed_nodes),
        "edges_added": len(seed_edges) - skipped_edges,
        "edges_skipped": skipped_edges,
        "seed_path": seed_path,
    }
