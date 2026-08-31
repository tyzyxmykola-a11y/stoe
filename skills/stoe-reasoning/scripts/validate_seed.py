#!/usr/bin/env python3
"""Verify the bundled canonical SToE seed without third-party dependencies."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


EXPECTED_SHA256 = "b327db6dbce9981ed21561b9d1a857e2e3786f1391d41edc0381fead79e59868"
EXPECTED_NODES = 36
EXPECTED_EDGES = 113
EXPECTED_CATEGORIES = {
    "Catalyst": 5,
    "Fertilizer": 3,
    "Hidden Diamond": 3,
    "Mirror": 3,
    "Seed": 4,
    "Star": 18,
}
EXPECTED_EXPRESSIONS = 36
EXPECTED_DESCRIPTIONS = 32


def main() -> int:
    seed_path = Path(__file__).resolve().parents[1] / "assets" / "stoe_seed.json"
    raw = seed_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw.decode("utf-8"))

    nodes = data.get("nodes", {})
    edges = data.get("edges", [])
    categories = Counter(node.get("category") for node in nodes.values())
    expressions = sum(bool(node.get("expression")) for node in nodes.values())
    descriptions = sum(bool(node.get("description")) for node in nodes.values())

    actual = {
        "sha256": digest,
        "core_ips": len(nodes),
        "typed_relations": len(edges),
        "categories": dict(sorted(categories.items())),
        "nonempty_expressions": expressions,
        "nonempty_descriptions": descriptions,
    }
    expected = {
        "sha256": EXPECTED_SHA256,
        "core_ips": EXPECTED_NODES,
        "typed_relations": EXPECTED_EDGES,
        "categories": EXPECTED_CATEGORIES,
        "nonempty_expressions": EXPECTED_EXPRESSIONS,
        "nonempty_descriptions": EXPECTED_DESCRIPTIONS,
    }

    print(json.dumps(actual, indent=2, ensure_ascii=False))
    if actual != expected:
        print("Canonical seed validation: FAILED")
        print(json.dumps({"expected": expected}, indent=2, ensure_ascii=False))
        return 1

    print("Canonical seed validation: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
