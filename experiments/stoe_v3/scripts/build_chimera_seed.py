"""
build_chimera_seed.py
=====================
Construct seed/stoe_chimera_seed.json: SToE concept content (node names,
categories, expressions) but the *graph structure* of the music-theory seed
(which pairs of indices are connected, in what edge type).

Why this exists
---------------
Paper v4 §7.5 pre-registers a single experiment that distinguishes the
two readings of the K-topology + SToE result:

  (a) STRUCTURAL: the +8 pp lift depends on the framework's graph
      structure (how concepts hang together), not just on the concept names
      being task-adjacent vocabulary.

  (b) PRIMING / KEYWORD-DENSITY: the +8 pp lift is task-relevant priming
      from concept names in the manifest, and any reasonable graph wiring
      over the same names would produce it.

The chimera seed isolates (a) from (b). The K-topology + chimera condition
keeps every SToE concept name available to the manifest, but routes
graph traversal along music-seed edges. If (a) is true, this condition
should regress toward baseline. If (b) is true, it should hold the +8 pp.

Mapping
-------
Both seeds happen to have IDENTICAL category and edge-type distributions
(verified at build time). The mapping is therefore:

  1. Sort SToE nodes by (category, name) deterministically. Index 0..35.
  2. Sort music nodes by (category, name) deterministically. Index 0..35.
  3. SToE node at position i  <->  music node at position i.

Within each category bucket, sort by name. Both seeds have:
  Star 18 | Catalyst 5 | Seed 4 | Mirror 3 | Hidden Diamond 3 | Fertilizer 3

so the buckets line up exactly. A music edge (src_music, tgt_music, type)
becomes a chimera edge (stoe_id_at(pos(src_music)), stoe_id_at(pos(tgt_music)), type).

What the chimera does NOT change
--------------------------------
- node count (36)
- edge count (113)
- category distribution
- edge-type distribution
- the LLM-visible content of every concept

What it DOES change
-------------------
- which pairs of SToE concepts are connected (now music-pattern)
- which SToE concepts cluster locally vs span structural distance
- depth-2 neighborhoods are now music-shaped

That is exactly the manipulation paper v4 §7.5 requires.

USAGE
-----
  python build_chimera_seed.py \\
      --stoe ../../stoe_v3/seed/stoe_seed.json \\
      --music ../../stoe_v3/seed/music_theory_seed.json \\
      --out ../../stoe_v3/seed/stoe_chimera_seed.json
"""

from __future__ import annotations
import argparse, json, hashlib, os, sys
from collections import Counter


def deterministic_order(nodes_dict: dict) -> list[str]:
    """Return node IDs sorted by (category, name, id) for a deterministic mapping."""
    items = list(nodes_dict.values())
    items.sort(key=lambda n: (n.get("category", ""), n.get("name", ""), n["id"]))
    return [n["id"] for n in items]


def by_category(nodes_dict: dict) -> list[tuple[str, list[str]]]:
    """[(category, [ids sorted by name within that category]), ...] in category-sorted order."""
    buckets: dict[str, list[dict]] = {}
    for n in nodes_dict.values():
        buckets.setdefault(n.get("category", ""), []).append(n)
    for cat in buckets:
        buckets[cat].sort(key=lambda n: (n.get("name", ""), n["id"]))
    return [(cat, [n["id"] for n in buckets[cat]]) for cat in sorted(buckets)]


def build_chimera(stoe: dict, music: dict, run_label: str = "STOE_CHIMERA") -> dict:
    # --- 1. structural pre-conditions ---
    s_nodes, s_edges = stoe["nodes"], stoe["edges"]
    m_nodes, m_edges = music["nodes"], music["edges"]
    assert len(s_nodes) == len(m_nodes), f"node count mismatch: {len(s_nodes)} vs {len(m_nodes)}"
    assert len(s_edges) == len(m_edges), f"edge count mismatch: {len(s_edges)} vs {len(m_edges)}"

    s_cat = Counter(n["category"] for n in s_nodes.values())
    m_cat = Counter(n["category"] for n in m_nodes.values())
    assert s_cat == m_cat, f"category histograms differ:\n  stoe:  {s_cat}\n  music: {m_cat}"

    s_etypes = Counter(e["type"] for e in s_edges)
    m_etypes = Counter(e["type"] for e in m_edges)
    assert s_etypes == m_etypes, f"edge-type histograms differ:\n  stoe:  {s_etypes}\n  music: {m_etypes}"

    # --- 2. build category-bucket aligned mapping music_id -> stoe_id ---
    s_buckets = by_category(s_nodes)
    m_buckets = by_category(m_nodes)
    assert [c for c, _ in s_buckets] == [c for c, _ in m_buckets], "category ordering drift"
    for (s_cat_name, s_ids), (m_cat_name, m_ids) in zip(s_buckets, m_buckets):
        assert len(s_ids) == len(m_ids), f"bucket {s_cat_name} size differs"

    music_to_stoe: dict[str, str] = {}
    for (_, s_ids), (_, m_ids) in zip(s_buckets, m_buckets):
        for s_id, m_id in zip(s_ids, m_ids):
            music_to_stoe[m_id] = s_id

    # Sanity: every music ID got mapped, every stoe ID is hit exactly once.
    assert len(music_to_stoe) == len(m_nodes)
    assert len(set(music_to_stoe.values())) == len(s_nodes)

    # --- 3. emit chimera nodes (= SToE nodes verbatim, but stamp session_id) ---
    chimera_nodes: dict[str, dict] = {}
    for stoe_id, n in s_nodes.items():
        clone = dict(n)  # shallow copy
        clone["session_id"] = run_label
        meta = dict(clone.get("metadata") or {})
        meta["chimera"] = True
        meta["chimera_source_seed"] = "stoe_seed.json"
        meta["chimera_structure_seed"] = "music_theory_seed.json"
        clone["metadata"] = meta
        chimera_nodes[stoe_id] = clone

    # --- 4. emit chimera edges: music adjacency, rebound to SToE ids ---
    chimera_edges: list[dict] = []
    for m_edge in m_edges:
        src_m = m_edge["source"]
        tgt_m = m_edge["target"]
        new_src = music_to_stoe[src_m]
        new_tgt = music_to_stoe[tgt_m]
        # Deterministic new edge id: hash of (new_src, new_tgt, type, original music edge id).
        # Makes the build reproducible and easy to audit.
        eid_input = f"{new_src}|{new_tgt}|{m_edge['type']}|{m_edge['id']}"
        new_eid = hashlib.sha1(eid_input.encode("utf-8")).hexdigest()[:16]
        chimera_edges.append({
            "id": new_eid,
            "source": new_src,
            "target": new_tgt,
            "type": m_edge["type"],
            "weight": m_edge.get("weight", 1.0),
            "note": f"chimera: derived from music edge {m_edge['id']}",
            "created_at": m_edge.get("created_at", "")
        })

    return {"nodes": chimera_nodes, "edges": chimera_edges}


def verify(chimera: dict, stoe: dict, music: dict) -> None:
    """Hard assertions over what the chimera must and must not preserve."""
    c_nodes, c_edges = chimera["nodes"], chimera["edges"]
    s_nodes, s_edges = stoe["nodes"], stoe["edges"]
    m_edges = music["edges"]

    # MUST preserve: node identity wholesale
    assert set(c_nodes.keys()) == set(s_nodes.keys()), "chimera nodes != stoe nodes"
    for nid in c_nodes:
        assert c_nodes[nid]["name"] == s_nodes[nid]["name"]
        assert c_nodes[nid]["category"] == s_nodes[nid]["category"]

    # MUST preserve: edge count and edge-type distribution from music
    assert len(c_edges) == len(m_edges)
    assert Counter(e["type"] for e in c_edges) == Counter(e["type"] for e in m_edges)

    # All chimera edge endpoints must be valid stoe node ids
    for e in c_edges:
        assert e["source"] in c_nodes
        assert e["target"] in c_nodes

    # MUST DIFFER: adjacency from stoe (this is the whole point)
    def adj_set(edges):
        return frozenset(
            (frozenset((e["source"], e["target"])), e["type"]) for e in edges
        )

    stoe_adj = adj_set(s_edges)
    chimera_adj = adj_set(c_edges)
    overlap = len(stoe_adj & chimera_adj)
    # We don't require zero overlap (random chance can hit a few), but it must
    # be much less than full identity. Spec: overlap < 25% of edges.
    max_allowed = int(0.25 * len(c_edges))
    assert overlap <= max_allowed, (
        f"chimera adjacency overlaps stoe too much: {overlap}/{len(c_edges)} edges "
        f"(max allowed: {max_allowed}). The chimera is not structurally distinct."
    )

    print("VERIFY OK")
    print(f"  nodes: {len(c_nodes)} (== {len(s_nodes)} stoe)")
    print(f"  edges: {len(c_edges)} (== {len(m_edges)} music)")
    print(f"  edge-type histogram matches music: yes")
    print(f"  adjacency overlap with stoe: {overlap}/{len(c_edges)} "
          f"({overlap/len(c_edges):.1%}; threshold ≤25%)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stoe",  required=True, help="path to stoe_seed.json")
    ap.add_argument("--music", required=True, help="path to music_theory_seed.json")
    ap.add_argument("--out",   required=True, help="path to write chimera seed")
    ap.add_argument("--label", default="STOE_CHIMERA",
                    help="session_id stamp on chimera nodes (default: STOE_CHIMERA)")
    args = ap.parse_args()

    with open(args.stoe,  "r", encoding="utf-8") as f: stoe  = json.load(f)
    with open(args.music, "r", encoding="utf-8") as f: music = json.load(f)

    chimera = build_chimera(stoe, music, run_label=args.label)
    verify(chimera, stoe, music)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    # newline="\n" pins line endings to LF across platforms so the
    # canonical SHA-256 in seed/.chimera.sha256 reproduces bit-identically
    # on Windows (which otherwise translates "\n" to "\r\n" in text mode).
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(chimera, f, indent=2, ensure_ascii=False)
    print(f"WROTE {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
