"""
Build seed/music_theory_seed.json — control ontology for the v3 ablation.

Mirrors seed/stoe_seed.json's structural shape exactly:
  - 36 nodes
  - Same category distribution: Star(18), Catalyst(5), Seed(4), Mirror(3),
    Hidden Diamond(3), Fertilizer(3)
  - Same edge type vocabulary
  - Same node fields (id, content, category, operator, session_id, etc.)

Different semantic content: music theory instead of information ontology.

Used as the non-SToE control in the K=25 ablation to disambiguate:
"is the boost SToE-specific, or any abstract relational ontology?"
"""

import json
import os
import uuid
from datetime import datetime

SESSION_ID = "MUSIC_SEED"
TIMESTAMP = "2026-05-11T09:00:00.000000"

def make_id(seed_str: str) -> str:
    """Deterministic 16-char hex id from a string."""
    import hashlib
    return hashlib.md5(seed_str.encode()).hexdigest()[:16]

def make_node(name, category, expr="", description=""):
    nid = make_id(name)
    return nid, {
        "id": nid,
        "content": name,
        "category": category,
        "type": "imaginary",
        "score": {},
        "operator": "seed",
        "session_id": SESSION_ID,
        "created_at": TIMESTAMP,
        "connections": 0,  # recalculated after edges
        "metadata": {
            "description": description,
            "is_music_seed": True,
            "expr": expr,
        },
        "name": name,
        "description": description,
        "expression": expr,
    }

# ---------------------------------------------------------------------------
# 36 nodes — paralleling stoe_seed structure
# ---------------------------------------------------------------------------

NODES_RAW = [
    # === STARS (18) — high-impact music theory concepts ===
    ("Music (M)",                              "Star",          "M ∈ M",      "the totality of organized sound"),
    ("Silence",                                "Mirror",        "∅",          "absence of sound — the negative space of music"),
    ("Listener (L)",                           "Catalyst",      "",           "the perceiver who completes the musical act"),
    ("Composer (C)",                           "Star",          "",           "creator of musical structures"),
    ("Law of Tonality",                        "Star",          "",           "tonal centers organize pitch relationships"),
    ("Law of Harmony",                         "Star",          "",           "simultaneous pitches form connected vertical structures"),
    ("Law of Resolution",                      "Star",          "",           "dissonance seeks consonance; tension seeks release"),
    ("Sonata Form",                            "Star",          "S = E·D·R",  "exposition-development-recapitulation: form contains itself"),
    ("Tonal Function",                         "Catalyst",      "",           "relation of a pitch or chord to a tonal center"),
    ("Note (n)",                               "Seed",          "n ∈ Scale",  "atomic unit of pitched sound"),
    ("Soul (∞)",                               "Hidden Diamond","",           "the ineffable source of musical meaning"),
    ("Musician (Mus)",                         "Star",          "",           "interpreter who realizes notation as sound"),
    ("AI Music Generation (AIM)",              "Seed",          "",           "algorithmic composition from learned patterns"),
    ("J.S. Bach (Bach)",                       "Star",          "",           "master who formalized counterpoint and tonal practice"),
    ("Common Practice Theory (CPT)",           "Star",          "",           "the unified theory of tonal music c. 1650-1900"),
    ("Sound Field",                            "Star",          "",           "the medium in which all musical events occur"),
    ("Operator + Counterpoint",                "Fertilizer",    "",           "two melodic lines coexisting in relation"),
    ("Operator × Harmonization",               "Star",          "n × n = chord","creating vertical sonority from melodic material"),
    ("Operator − Subtraction",                 "Fertilizer",    "",           "removing voices to reveal essential motion"),
    ("Operator ↻ Repetition",                  "Catalyst",      "",           "iterative restatement that builds form"),
    ("Operator ^ Amplification",               "Fertilizer",    "",           "intensifying dynamics, register, or texture"),
    ("Operator ∑ Cadence",                     "Catalyst",      "",           "harmonic conclusion collapsing phrase into resolution"),
    ("Operator S Notation",                    "Seed",          "",           "encoding sound as written symbol for transmission"),
    ("Tonic=Resolution theorem",               "Star",          "T = R",      "the tonic is where dissonance resolves; both are the same"),
    ("Tension-Release duality",                "Mirror",        "",           "dissonance and consonance as complementary phases"),
    ("Circle of Fifths",                       "Star",          "",           "cyclic structure of all 12 keys via fifth relations"),
    ("Modulation",                             "Catalyst",      "",           "transformation from one tonal center to another"),
    ("Listener creates meaning",               "Mirror",        "",           "sound becomes music only when heard"),
    ("Music self-reference",                   "Hidden Diamond","",           "music about music; quotation, variation, parody"),
    ("Persistent Score",                       "Seed",          "",           "notation that conserves musical structure across time"),
    ("Music=Everything theorem",               "Hidden Diamond","M = ∞",     "for the truly engaged listener music encompasses all"),
    ("Rameau Treatise 1722",                   "Star",          "",           "Traité de l'harmonie réduite à ses principes naturels"),
    ("Functional Harmony: 4 Categories",       "Star",          "",           "Tonic, Subdominant, Dominant, and Predominant functions"),
    ("Music Theory as Cognitive Architecture", "Star",          "",           "tonal expectation as a model of structured prediction"),
    ("Composition Practice Gap",               "Star",          "",           "the discontinuity between theory and lived composition"),
    ("Three Laws of Tonality",                 "Star",          "",           "Tonality, Harmony, Resolution as foundational principles"),
]

assert len(NODES_RAW) == 36, f"need exactly 36 nodes, got {len(NODES_RAW)}"

# Verify category distribution matches stoe_seed exactly
from collections import Counter
cat_counts = Counter(c for _, c, *_ in NODES_RAW)
expected = {"Star": 18, "Catalyst": 5, "Seed": 4, "Mirror": 3, "Hidden Diamond": 3, "Fertilizer": 3}
assert dict(cat_counts) == expected, f"category mismatch: {dict(cat_counts)} vs {expected}"

# Build node dict
nodes = {}
node_id_by_name = {}
for name, cat, expr, desc in NODES_RAW:
    nid, node = make_node(name, cat, expr, desc)
    nodes[nid] = node
    node_id_by_name[name] = nid

# ---------------------------------------------------------------------------
# Edges (~113 — matching stoe_seed.json's density and type distribution)
#
# Target distribution from stoe_seed.json:
#   generated_by: 41   evaluates: 23   connected_to: 20
#   evolved_from: 18   synergy_with: 8   contradicts: 3
# ---------------------------------------------------------------------------

EDGES_RAW = [
    # generated_by: theory generates its parts (41 edges)
    ("Music (M)",                       "Common Practice Theory (CPT)", "generated_by"),
    ("Note (n)",                        "Common Practice Theory (CPT)", "generated_by"),
    ("Law of Tonality",                 "Common Practice Theory (CPT)", "generated_by"),
    ("Law of Harmony",                  "Common Practice Theory (CPT)", "generated_by"),
    ("Law of Resolution",               "Common Practice Theory (CPT)", "generated_by"),
    ("Sonata Form",                     "Common Practice Theory (CPT)", "generated_by"),
    ("Tonal Function",                  "Common Practice Theory (CPT)", "generated_by"),
    ("Circle of Fifths",                "Common Practice Theory (CPT)", "generated_by"),
    ("Functional Harmony: 4 Categories","Common Practice Theory (CPT)", "generated_by"),
    ("Three Laws of Tonality",          "Common Practice Theory (CPT)", "generated_by"),
    ("Operator + Counterpoint",         "Composer (C)",                  "generated_by"),
    ("Operator × Harmonization",        "Composer (C)",                  "generated_by"),
    ("Operator − Subtraction",          "Composer (C)",                  "generated_by"),
    ("Operator ↻ Repetition",           "Composer (C)",                  "generated_by"),
    ("Operator ^ Amplification",        "Composer (C)",                  "generated_by"),
    ("Operator ∑ Cadence",              "Composer (C)",                  "generated_by"),
    ("Operator S Notation",             "Composer (C)",                  "generated_by"),
    ("AI Music Generation (AIM)",       "Composer (C)",                  "generated_by"),
    ("Persistent Score",                "Composer (C)",                  "generated_by"),
    ("Modulation",                      "Tonal Function",                "generated_by"),
    ("Tension-Release duality",         "Law of Resolution",             "generated_by"),
    ("Tonic=Resolution theorem",        "Law of Resolution",             "generated_by"),
    ("Music=Everything theorem",        "Soul (∞)",                      "generated_by"),
    ("Music self-reference",            "Sonata Form",                   "generated_by"),
    ("Listener creates meaning",        "Listener (L)",                  "generated_by"),
    ("Composition Practice Gap",        "Music Theory as Cognitive Architecture", "generated_by"),
    ("Rameau Treatise 1722",            "J.S. Bach (Bach)",              "generated_by"),
    ("Functional Harmony: 4 Categories","Rameau Treatise 1722",          "generated_by"),
    ("Three Laws of Tonality",          "Rameau Treatise 1722",          "generated_by"),
    ("Sound Field",                     "Music (M)",                     "generated_by"),
    ("Musician (Mus)",                  "Music (M)",                     "generated_by"),
    ("Listener (L)",                    "Music (M)",                     "generated_by"),
    ("Composer (C)",                    "Music (M)",                     "generated_by"),
    ("Silence",                         "Music (M)",                     "generated_by"),
    ("J.S. Bach (Bach)",                "Musician (Mus)",                "generated_by"),
    ("AI Music Generation (AIM)",       "Music Theory as Cognitive Architecture","generated_by"),
    ("Music Theory as Cognitive Architecture","Common Practice Theory (CPT)", "generated_by"),
    ("Operator + Counterpoint",         "J.S. Bach (Bach)",              "generated_by"),
    ("Sonata Form",                     "Rameau Treatise 1722",          "generated_by"),
    ("Tonal Function",                  "Rameau Treatise 1722",          "generated_by"),
    ("Soul (∞)",                        "Music (M)",                     "generated_by"),

    # connected_to: side-by-side conceptual pairings (20 edges)
    ("Note (n)",                        "Sound Field",                   "connected_to"),
    ("Listener (L)",                    "Composer (C)",                  "connected_to"),
    ("Musician (Mus)",                  "Composer (C)",                  "connected_to"),
    ("Operator + Counterpoint",         "Operator × Harmonization",      "connected_to"),
    ("Operator ↻ Repetition",           "Operator ∑ Cadence",            "connected_to"),
    ("Tension-Release duality",         "Operator ∑ Cadence",            "connected_to"),
    ("Circle of Fifths",                "Modulation",                    "connected_to"),
    ("Tonal Function",                  "Functional Harmony: 4 Categories","connected_to"),
    ("Law of Tonality",                 "Law of Harmony",                "connected_to"),
    ("Law of Harmony",                  "Law of Resolution",             "connected_to"),
    ("Three Laws of Tonality",          "Common Practice Theory (CPT)",  "connected_to"),
    ("Note (n)",                        "Operator S Notation",           "connected_to"),
    ("Persistent Score",                "Operator S Notation",           "connected_to"),
    ("Sonata Form",                     "Music self-reference",          "connected_to"),
    ("Soul (∞)",                        "Listener creates meaning",      "connected_to"),
    ("Music=Everything theorem",        "Soul (∞)",                      "connected_to"),
    ("Composition Practice Gap",        "AI Music Generation (AIM)",     "connected_to"),
    ("Musician (Mus)",                  "Persistent Score",              "connected_to"),
    ("Tonic=Resolution theorem",        "Functional Harmony: 4 Categories","connected_to"),
    ("Modulation",                      "Tonal Function",                "connected_to"),

    # evolved_from: historical / conceptual succession (18 edges)
    ("Common Practice Theory (CPT)",    "Rameau Treatise 1722",          "evolved_from"),
    ("AI Music Generation (AIM)",       "Persistent Score",              "evolved_from"),
    ("AI Music Generation (AIM)",       "Operator S Notation",           "evolved_from"),
    ("Music Theory as Cognitive Architecture","Functional Harmony: 4 Categories","evolved_from"),
    ("Sonata Form",                     "Operator ↻ Repetition",         "evolved_from"),
    ("Modulation",                      "Circle of Fifths",              "evolved_from"),
    ("Functional Harmony: 4 Categories","Tonal Function",                "evolved_from"),
    ("Three Laws of Tonality",          "Law of Tonality",               "evolved_from"),
    ("Three Laws of Tonality",          "Law of Harmony",                "evolved_from"),
    ("Three Laws of Tonality",          "Law of Resolution",             "evolved_from"),
    ("Operator ∑ Cadence",              "Operator × Harmonization",      "evolved_from"),
    ("Music self-reference",            "Operator ↻ Repetition",         "evolved_from"),
    ("Composition Practice Gap",        "Common Practice Theory (CPT)",  "evolved_from"),
    ("Tonic=Resolution theorem",        "Law of Resolution",             "evolved_from"),
    ("Listener creates meaning",        "Law of Resolution",             "evolved_from"),
    ("Music=Everything theorem",        "Music (M)",                     "evolved_from"),
    ("Tension-Release duality",         "Operator + Counterpoint",       "evolved_from"),
    ("Rameau Treatise 1722",            "J.S. Bach (Bach)",              "evolved_from"),

    # synergy_with: emergent properties from interaction (8 edges)
    ("Operator × Harmonization",        "Operator + Counterpoint",       "synergy_with"),
    ("Operator ↻ Repetition",           "Operator ^ Amplification",      "synergy_with"),
    ("Modulation",                      "Circle of Fifths",              "synergy_with"),
    ("Listener (L)",                    "Composer (C)",                  "synergy_with"),
    ("Musician (Mus)",                  "Persistent Score",              "synergy_with"),
    ("Soul (∞)",                        "Listener (L)",                  "synergy_with"),
    ("AI Music Generation (AIM)",       "Common Practice Theory (CPT)",  "synergy_with"),
    ("J.S. Bach (Bach)",                "Composer (C)",                  "synergy_with"),

    # contradicts: tensions in the field (3 edges)
    ("Silence",                         "Music (M)",                     "contradicts"),
    ("Operator − Subtraction",          "Operator + Counterpoint",       "contradicts"),
    ("Tension-Release duality",         "Law of Resolution",             "contradicts"),

    # evaluates: meta-judgments (23 edges)
    ("Music Theory as Cognitive Architecture","Sonata Form",            "evaluates"),
    ("Music Theory as Cognitive Architecture","Operator ↻ Repetition",  "evaluates"),
    ("Music Theory as Cognitive Architecture","Tonal Function",         "evaluates"),
    ("Music Theory as Cognitive Architecture","Modulation",             "evaluates"),
    ("Composition Practice Gap",        "AI Music Generation (AIM)",     "evaluates"),
    ("Composition Practice Gap",        "Common Practice Theory (CPT)",  "evaluates"),
    ("Three Laws of Tonality",          "Law of Tonality",               "evaluates"),
    ("Three Laws of Tonality",          "Law of Harmony",                "evaluates"),
    ("Three Laws of Tonality",          "Law of Resolution",             "evaluates"),
    ("Tonic=Resolution theorem",        "Tonal Function",                "evaluates"),
    ("Music=Everything theorem",        "Listener (L)",                  "evaluates"),
    ("Music self-reference",            "Common Practice Theory (CPT)",  "evaluates"),
    ("Rameau Treatise 1722",            "Functional Harmony: 4 Categories","evaluates"),
    ("Rameau Treatise 1722",            "Three Laws of Tonality",        "evaluates"),
    ("J.S. Bach (Bach)",                "Operator + Counterpoint",       "evaluates"),
    ("J.S. Bach (Bach)",                "Sonata Form",                   "evaluates"),
    ("Listener creates meaning",        "Listener (L)",                  "evaluates"),
    ("Soul (∞)",                        "Music (M)",                     "evaluates"),
    ("Tension-Release duality",         "Operator ∑ Cadence",            "evaluates"),
    ("Operator × Harmonization",        "Note (n)",                      "evaluates"),
    ("Operator + Counterpoint",         "Note (n)",                      "evaluates"),
    ("Functional Harmony: 4 Categories","Common Practice Theory (CPT)",  "evaluates"),
    ("Sound Field",                     "Note (n)",                      "evaluates"),
]

# Resolve to edges with stable ids
edges = []
for src_name, tgt_name, etype in EDGES_RAW:
    assert src_name in node_id_by_name, f"unknown src: {src_name}"
    assert tgt_name in node_id_by_name, f"unknown tgt: {tgt_name}"
    eid = make_id(f"{src_name}->{tgt_name}:{etype}")
    edges.append({
        "id": eid,
        "source": node_id_by_name[src_name],
        "target": node_id_by_name[tgt_name],
        "type": etype,
        "weight": 1.0,
        "note": "music seed",
        "created_at": TIMESTAMP,
    })

# Compute connection counts
conn = {}
for e in edges:
    conn[e["source"]] = conn.get(e["source"], 0) + 1
    conn[e["target"]] = conn.get(e["target"], 0) + 1
for nid in nodes:
    nodes[nid]["connections"] = conn.get(nid, 0)

# Verify edge type distribution roughly matches stoe_seed
from collections import Counter
et_counts = Counter(e["type"] for e in edges)
print("Edge type counts:", dict(et_counts))
print(f"Total nodes: {len(nodes)}")
print(f"Total edges: {len(edges)}")

# Write
here = os.path.dirname(__file__)
out_path = os.path.join(here, "music_theory_seed.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"nodes": nodes, "edges": edges}, f, indent=2, ensure_ascii=False)

print(f"Wrote {out_path}")
