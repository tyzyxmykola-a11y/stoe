"""
SToE v3 — Structural Evaluator
================================
Replaces v82's `score_step` (the LLM-self-scoring meta-prompt that produced
saturated 7–9 noise across every output regardless of quality).

This evaluator is **LLM-free by design.** The verdict on a candidate node `n`
is computed by reading the graph state. Paper 4 §3.3:

    "Self-evaluation is implemented through prompting: the system is asked
    to evaluate its prior output, and it produces a fresh response. This
    approach ... does not satisfy the architectural requirement."

Four metrics, each derived from properties of the graph:

  1. Novelty
       Count of edges incident to `n` whose other endpoint lies OUTSIDE
       the session seed's depth-2 neighbourhood. A node that only links
       back into the seed's known territory is novelty=0; a node that
       reaches into previously-unexplored regions is novelty>0.

  2. Coherence (penalty)
       Count of `contradicts` edges incident to `n`, in either direction.
       Higher means more recorded tension. The verdict reports the raw
       count; the comparator subtracts it.

  3. Bridging (boolean)
       True iff at least two of `n`'s neighbours were in different weakly
       connected components of (G − n). Adding `n` merged components.
       This is a structural fingerprint of "this node closed a gap that
       previously existed."

  4. Attractor distance
       Of the candidate's content tokens, what fraction is NOT in the
       union of the same-session nodes' tokens?
            1 − |cand_tokens ∩ centroid| / |cand_tokens|
       Higher = candidate uses more vocabulary novel to this session.
       Lower = candidate is recycling the session's existing words.

       This is the asymmetric form (candidate-side normalized). Symmetric
       Jaccard is dominated by centroid size and barely differentiates
       between candidates of different "freshness"; the asymmetric form
       directly answers the question we care about — the v1/v82 failure
       mode where every output collapsed to the same training-data
       attractor.

The verdict is itself a node, connected to `n` via an `evaluates` edge.
The verdict's content is the structured fact list, NOT a 1–5 number.
The verdict participates in the field like any other node — subsequent
reasoning can query, contradict, or reference it.

No external dependencies. Pure stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Iterable, Optional

from .field import InformationField


# ---------------------------------------------------------------------------
# Tokenization for attractor-distance computation
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z][a-z0-9]+", re.IGNORECASE)

# Small, deliberately-conservative stopword list. The point is to remove
# closed-class function words that drift across all LLM outputs (and so
# would make every text look similar to every other), not to do real NLP.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "these", "those",
    "are", "was", "were", "have", "has", "had", "but", "not", "can", "will",
    "would", "could", "should", "may", "might", "must", "shall", "into",
    "onto", "out", "over", "under", "between", "through", "during", "while",
    "than", "then", "when", "where", "what", "which", "who", "whom", "whose",
    "how", "why", "any", "all", "some", "each", "every", "such", "more",
    "most", "less", "few", "many", "much", "very", "also", "just", "only",
    "even", "still", "yet", "way", "ways", "thing", "things", "one", "two",
    "three", "four", "five", "you", "your", "they", "their", "them", "his",
    "her", "him", "she", "its", "our", "ours", "ourselves", "themselves",
})

def _tokens(text: str) -> set[str]:
    """Lowercased content-word tokens, length >= 3, stopwords removed."""
    out = set()
    for m in _TOKEN_RE.finditer(text.lower()):
        t = m.group(0)
        if len(t) < 3 or t in _STOPWORDS:
            continue
        out.add(t)
    return out


def _candidate_side_overlap(cand: set, ref: set) -> float:
    """
    Fraction of `cand` that is also in `ref`. Asymmetric: normalized by
    candidate size, not by union. Returns 0.0 if cand is empty.

    Why asymmetric: the question is "how much of the candidate is
    centroid-vocabulary?", not "how similar are these two sets?".
    Symmetric Jaccard is dominated by ref size when ref is a union of
    many session nodes — every candidate ends up looking equally
    distant. The candidate-side measure correctly differentiates a
    candidate of N tokens with K overlaps regardless of how large ref is.
    """
    if not cand:
        return 0.0
    return len(cand & ref) / len(cand)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

@dataclass
class Verdict:
    """
    Structural assessment of a node, derived purely from graph properties.
    No LLM judgment is involved.
    """
    node_id: str
    seed_id: str
    novelty: int
    coherence_penalty: int
    bridging: bool
    attractor_distance: float
    # Filled in after the verdict is added to the field
    verdict_node_id: Optional[str] = None
    verdict_edge_id: Optional[str] = None

    def to_content(self) -> str:
        return (
            f"[verdict] novelty={self.novelty} "
            f"coherence_penalty={self.coherence_penalty} "
            f"bridging={'yes' if self.bridging else 'no'} "
            f"attractor_distance={self.attractor_distance:.3f}"
        )

    def to_metadata(self) -> dict:
        return {
            "is_verdict": True,
            "evaluates": self.node_id,
            "novelty": self.novelty,
            "coherence_penalty": self.coherence_penalty,
            "bridging": self.bridging,
            "attractor_distance": self.attractor_distance,
        }

    def composite_score(self) -> float:
        """
        Default ranking score: a deliberately simple weighted sum.

            score = novelty + 2*bridging - coherence_penalty + attractor_distance

        This is one ranking out of many. Callers that want a different
        objective (e.g. pure novelty, or coherence-first) should read the
        individual fields directly. The composite exists so 'pick the
        best of these N' has a default that doesn't require an LLM.
        """
        return (
            float(self.novelty)
            + (2.0 if self.bridging else 0.0)
            - float(self.coherence_penalty)
            + float(self.attractor_distance)
        )


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class StructuralEvaluator:
    """
    Compute a Verdict for a node in a field, then optionally write the
    verdict back into the field as a new node connected via `evaluates`.
    """

    def __init__(self, attractor_seed_depth: int = 2):
        # `attractor_seed_depth` controls how big the "seed neighbourhood"
        # is for novelty. Default 2 matches paper 4 §5.3's traversal depth.
        self.seed_depth = attractor_seed_depth

    # ---- public API ----

    def evaluate(
        self,
        field: InformationField,
        node_id: str,
        seed_id: str,
        session_id: str = "",
        write_verdict: bool = True,
    ) -> Verdict:
        """
        Build a Verdict for `node_id` against the session seeded at
        `seed_id`. If `write_verdict` is True, the verdict is added to
        the field as a node and connected via an `evaluates` edge.

        Raises ValueError if `node_id` or `seed_id` is missing from the
        field.
        """
        if node_id not in field.nodes:
            raise ValueError(f"node_id {node_id!r} not in field")
        if seed_id not in field.nodes:
            raise ValueError(f"seed_id {seed_id!r} not in field")

        novelty = self._compute_novelty(field, node_id, seed_id)
        coherence_penalty = self._compute_coherence_penalty(field, node_id)
        bridging = self._compute_bridging(field, node_id)
        attractor_distance = self._compute_attractor_distance(
            field, node_id, session_id
        )

        v = Verdict(
            node_id=node_id,
            seed_id=seed_id,
            novelty=novelty,
            coherence_penalty=coherence_penalty,
            bridging=bridging,
            attractor_distance=attractor_distance,
        )

        if write_verdict:
            verdict_node_id = field.add_point(
                content=v.to_content(),
                category="Evaluation",
                operator="@evaluator",
                session_id=session_id,
                metadata=v.to_metadata(),
            )
            edge_id = field.connect(
                verdict_node_id, node_id,
                edge_type="evaluates",
                weight=v.composite_score(),
                note="structural verdict",
            )
            v.verdict_node_id = verdict_node_id
            v.verdict_edge_id = edge_id

        return v

    @staticmethod
    def rank(verdicts: Iterable[Verdict]) -> list[Verdict]:
        """Sort by composite_score, descending. Stable on ties."""
        return sorted(verdicts, key=lambda v: -v.composite_score())

    # ---- metrics ----

    def _compute_novelty(
        self,
        field: InformationField,
        node_id: str,
        seed_id: str,
    ) -> int:
        """
        Count edges incident to `node_id` whose other endpoint is NOT in
        the seed's depth-`self.seed_depth` neighbourhood.

        Excludes severed edges. Excludes the candidate itself from its
        own seed-nbhd membership check (a node is always "in" its own
        neighbourhood; novelty asks where its OUTGOING/INCOMING edges
        reach).
        """
        seed_nbhd = set(field.navigate_from(
            seed_id, depth=self.seed_depth, include_failed=True,
        ).keys())
        # The candidate is allowed to be inside seed_nbhd; we still ask
        # about its edges.
        novelty = 0
        for e in field.edges:
            if e.get("severed"):
                continue
            other = None
            if e["source"] == node_id:
                other = e["target"]
            elif e["target"] == node_id:
                other = e["source"]
            if other is None:
                continue
            if other == seed_id:
                # Edge directly to the seed itself — not novelty.
                continue
            if other not in seed_nbhd:
                novelty += 1
        return novelty

    def _compute_coherence_penalty(
        self,
        field: InformationField,
        node_id: str,
    ) -> int:
        """Count of active `contradicts` edges incident to node_id."""
        count = 0
        for e in field.edges:
            if e.get("severed"):
                continue
            if e["type"] != "contradicts":
                continue
            if e["source"] == node_id or e["target"] == node_id:
                count += 1
        return count

    def _compute_bridging(
        self,
        field: InformationField,
        node_id: str,
    ) -> bool:
        """
        True iff at least two of node_id's neighbours were in different
        weakly-connected components of (G − node_id). Computed on the
        active (non-severed) subgraph.
        """
        # node_id's active neighbours (treating edges as undirected)
        neighbours = set()
        for e in field.edges:
            if e.get("severed"):
                continue
            if e["source"] == node_id:
                neighbours.add(e["target"])
            elif e["target"] == node_id:
                neighbours.add(e["source"])
        if len(neighbours) < 2:
            return False

        # Build undirected adjacency of the field minus node_id
        adj: dict[str, set[str]] = {nid: set() for nid in field.nodes if nid != node_id}
        for e in field.edges:
            if e.get("severed"):
                continue
            s, t = e["source"], e["target"]
            if s == node_id or t == node_id:
                continue
            if s in adj and t in adj:
                adj[s].add(t)
                adj[t].add(s)

        # BFS from each neighbour to find the component containing it.
        # If two neighbours are in different components, node_id bridges.
        component_of: dict[str, int] = {}
        next_id = 0
        for n in neighbours:
            if n not in component_of and n in adj:
                # BFS
                stack = [n]
                while stack:
                    cur = stack.pop()
                    if cur in component_of:
                        continue
                    component_of[cur] = next_id
                    stack.extend(adj.get(cur, ()) - set(component_of))
                next_id += 1
        # Set of distinct component IDs assigned to node_id's neighbours
        comps = {component_of[n] for n in neighbours if n in component_of}
        return len(comps) >= 2

    def _compute_attractor_distance(
        self,
        field: InformationField,
        node_id: str,
        session_id: str,
    ) -> float:
        """
        Of node_id's content tokens, what fraction is NOT in the union
        of same-session nodes' tokens (the centroid)?

            distance = 1 − |node_tokens ∩ centroid| / |node_tokens|

        Edge cases:
          • If node has no tokens (very short content): returns 0.0.
          • If centroid is empty (no other session nodes): returns 1.0.
        """
        node_tokens = _tokens(field.nodes[node_id]["content"])
        if not node_tokens:
            return 0.0

        centroid: set[str] = set()
        for nid, n in field.nodes.items():
            if nid == node_id:
                continue
            if session_id and n.get("session_id") != session_id:
                continue
            if n.get("metadata", {}).get("is_verdict"):
                continue
            if n.get("category") == "Evaluation":
                continue
            centroid |= _tokens(n["content"])

        if not centroid:
            return 1.0
        return 1.0 - _candidate_side_overlap(node_tokens, centroid)
