"""
SToE v3 — Graph-aware Operators
================================
Each operator declares:
  • a graph PRECONDITION it requires before it can fire
  • a graph EFFECT it produces when it fires (new nodes, new edges, severance)

This breaks the v1/v82 inheritance where every operator was a prompt-template
(`+` meant "Combine ideas:", `!` meant "Challenge:") and an LLM responded to
all of them with rephrasings of the same training-data attractor.

In v3, the operator's *content* lives in:
  (1) what graph state it consumes (which nodes, which neighborhoods)
  (2) what graph state it produces (new node + which edge types)

The LLM call is tail logic. The prompt is built from the graph context the
operator pulls. If the precondition isn't met, the operator returns
`fired=False` without calling the LLM. That's the slice-2 checkpoint:
"operators sometimes can't fire and that's correct behavior."

Operator table
--------------
  +  ConnectionOp   arity 2     two existing nodes -> new node + connected_to edges
  ×  SynergyOp      arity 2     same + neighborhoods of both -> synergy_with edges
  ↻  RecursionOp    arity 1     refuses if produced output is near-duplicate
  !  DisruptionOp   arity 1     pulls failed_from + contradicts neighbours into prompt
  −  RemovalOp      arity 1     severs lowest-weight outgoing edge; no LLM call
  ∑  SummarizeOp    arity ≥3    autoinjective collapse over a node set
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field as dc_field
from typing import Optional

from .field import InformationField
from .llm import LLMClient, OllamaError


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class OperatorResult:
    operator: str
    fired: bool
    reason: str
    produced_node_id: Optional[str] = None
    produced_edge_ids: list[str] = dc_field(default_factory=list)
    severed_edge_id: Optional[str] = None
    llm_prompt: Optional[str] = None
    llm_response: Optional[str] = None
    inputs: list[str] = dc_field(default_factory=list)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

# Default similarity threshold for deduplication checks (RecursionOp).
# 0.85 was chosen as a reasonable cutoff for "essentially the same paragraph"
# using difflib's SequenceMatcher. Tunable by passing dedupe_threshold to the op.
DEFAULT_DEDUPE_THRESHOLD = 0.85


class Operator:
    """
    Subclass and override `_fire`. The base class:
      • validates arity
      • validates that all input node IDs exist in the field
      • routes to `_fire` only if validation passes
      • returns a structured OperatorResult either way

    By design, `_fire` is responsible for further preconditions (e.g.
    DisruptionOp may require that the input has at least one contradicts
    or failed_from neighbor — that's a *firing* check, not a *call* check).
    """

    symbol: str = ""
    name: str = ""
    arity: Optional[int] = 1   # None = variadic
    min_arity: int = 1         # used when arity is None

    def fire(
        self,
        field: InformationField,
        args: list[str],
        llm: Optional[LLMClient] = None,
        session_id: str = "",
    ) -> OperatorResult:
        # Arity check
        if self.arity is None:
            if len(args) < self.min_arity:
                return self._refuse(args, f"need >= {self.min_arity} args, got {len(args)}")
        elif len(args) != self.arity:
            return self._refuse(args, f"expected {self.arity} arg(s), got {len(args)}")

        # Existence check
        for a in args:
            if a not in field.nodes:
                return self._refuse(args, f"node {a!r} not in field")

        # Subclass-specific
        return self._fire(field, args, llm, session_id)

    def _refuse(self, args: list[str], reason: str) -> OperatorResult:
        return OperatorResult(
            operator=self.symbol, fired=False, reason=reason, inputs=list(args),
        )

    # Subclass override
    def _fire(
        self,
        field: InformationField,
        args: list[str],
        llm: Optional[LLMClient],
        session_id: str,
    ) -> OperatorResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content(field: InformationField, nid: str) -> str:
    return field.nodes[nid]["content"]


def _format_neighborhood(field: InformationField, nid: str, depth: int = 1) -> str:
    """
    Render a node's depth-`depth` neighborhood as text for inclusion in
    an operator's prompt. Edge types are preserved so the LLM sees the
    structural context, not just adjacent content.
    """
    sub = field.navigate_from(nid, depth=depth, include_failed=True)
    if not sub:
        return ""
    lines = []
    for node_id, info in sub.items():
        if node_id == nid:
            continue
        c = info["ip"]["content"]
        # Trim verbose content
        c_short = c[:160] + ("..." if len(c) > 160 else "")
        edge_summary = ",".join(sorted({e["type"] for e in info["edges"]})) or "?"
        lines.append(f"  - [{edge_summary}] {c_short}")
    return "\n".join(lines)


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _safe_call(llm: Optional[LLMClient], prompt: str) -> tuple[Optional[str], Optional[str]]:
    """
    Call the LLM; return (response, error). Either response or error is None.
    Operators can decide whether to conserve the failure as a Ghost (most do).
    """
    if llm is None:
        return None, "no LLM client provided"
    try:
        return llm.call(prompt), None
    except OllamaError as e:
        return None, str(e)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# +  Connection
# ---------------------------------------------------------------------------

class ConnectionOp(Operator):
    """Join two existing IPs in co-presence; produce a new IP linking them."""
    symbol = "+"
    name = "Connection"
    arity = 2

    def _fire(self, field, args, llm, session_id):
        a, b = args
        a_content = _content(field, a)
        b_content = _content(field, b)

        prompt = (
            "You are reasoning within an SToE Information Field.\n"
            "Two information points are given. State the structural connection\n"
            "between them in one sharp sentence. No preamble.\n\n"
            f"IP A: {a_content}\n"
            f"IP B: {b_content}\n\n"
            "Connection:"
        )
        response, err = _safe_call(llm, prompt)
        if response is None:
            ghost = field.add_failed(
                from_id=a, reason=f"ConnectionOp LLM failed: {err}",
                operator=self.symbol, session_id=session_id,
            )
            return OperatorResult(
                operator=self.symbol, fired=False,
                reason=f"LLM call failed: {err}",
                produced_node_id=ghost,
                inputs=list(args), llm_prompt=prompt,
            )

        new_id = field.add_point(
            content=response.strip(),
            category="Connection",
            operator=self.symbol,
            session_id=session_id,
            metadata={"connects": [a, b]},
        )
        e1 = field.connect(new_id, a, edge_type="connected_to",
                           note=f"{self.symbol} connection to A")
        e2 = field.connect(new_id, b, edge_type="connected_to",
                           note=f"{self.symbol} connection to B")
        return OperatorResult(
            operator=self.symbol, fired=True, reason="ok",
            produced_node_id=new_id,
            produced_edge_ids=[e1, e2],
            llm_prompt=prompt, llm_response=response,
            inputs=list(args),
        )


# ---------------------------------------------------------------------------
# ×  Synergy
# ---------------------------------------------------------------------------

class SynergyOp(Operator):
    """
    Like Connection, but the prompt also includes each input's depth-1
    neighborhood. The semantic claim is that synergy emerges from
    structural context, not just from the two endpoints.
    """
    symbol = "×"
    name = "Synergy"
    arity = 2

    def _fire(self, field, args, llm, session_id):
        a, b = args
        a_content = _content(field, a)
        b_content = _content(field, b)
        a_ctx = _format_neighborhood(field, a) or "  (no neighbors)"
        b_ctx = _format_neighborhood(field, b) or "  (no neighbors)"

        prompt = (
            "You are reasoning within an SToE Information Field.\n"
            "Two information points and their existing neighborhoods are given.\n"
            "Identify the emergent property (synergy) — something present in\n"
            "the combination that is in NEITHER point alone. One sentence.\n\n"
            f"IP A: {a_content}\nA's neighborhood:\n{a_ctx}\n\n"
            f"IP B: {b_content}\nB's neighborhood:\n{b_ctx}\n\n"
            "Emergent property:"
        )
        response, err = _safe_call(llm, prompt)
        if response is None:
            ghost = field.add_failed(
                from_id=a, reason=f"SynergyOp LLM failed: {err}",
                operator=self.symbol, session_id=session_id,
            )
            return OperatorResult(
                operator=self.symbol, fired=False,
                reason=f"LLM call failed: {err}",
                produced_node_id=ghost,
                inputs=list(args), llm_prompt=prompt,
            )

        new_id = field.add_point(
            content=response.strip(),
            category="Synergy",
            operator=self.symbol,
            session_id=session_id,
            metadata={"synergy_of": [a, b]},
        )
        e1 = field.connect(new_id, a, edge_type="synergy_with",
                           note=f"{self.symbol} synergy from A")
        e2 = field.connect(new_id, b, edge_type="synergy_with",
                           note=f"{self.symbol} synergy from B")
        return OperatorResult(
            operator=self.symbol, fired=True, reason="ok",
            produced_node_id=new_id,
            produced_edge_ids=[e1, e2],
            llm_prompt=prompt, llm_response=response,
            inputs=list(args),
        )


# ---------------------------------------------------------------------------
# ↻  Recursion
# ---------------------------------------------------------------------------

class RecursionOp(Operator):
    """
    Self-apply: ask the LLM to evolve the input. After response, check
    whether the response is near-duplicate to either:
      • the input node's own content, or
      • any existing `evolved_from` descendant of the input node.
    If yes, refuse — the chain is degenerating into restatement (the
    v1/v82 failure mode where each `↻` step inflates words without
    adding information).
    """
    symbol = "↻"
    name = "Recursion"
    arity = 1

    def __init__(self, dedupe_threshold: float = DEFAULT_DEDUPE_THRESHOLD):
        self.dedupe_threshold = dedupe_threshold

    def _existing_evolutions(self, field, nid: str) -> list[str]:
        """
        Content of all nodes that have evolved FROM `nid` (transitively).

        Edge semantics: when `child` evolves from `parent`, the edge is
        added as `connect(child, parent, "evolved_from")`. So from `nid`'s
        perspective, the children of evolution are nodes with INCOMING
        `evolved_from` edges (they point at nid claiming to evolve from it).

        We then recurse: each child's evolutions are its own incoming
        evolved_from edges.
        """
        results = []
        seen = {nid}
        frontier = [nid]
        while frontier:
            next_frontier = []
            for cur in frontier:
                for adj in field.get_adjacent(cur):
                    if adj["edge"]["type"] != "evolved_from":
                        continue
                    # incoming = the other endpoint declared evolved_from -> cur
                    if adj["direction"] != "incoming":
                        continue
                    tid = adj["ip"]["id"]
                    if tid in seen:
                        continue
                    seen.add(tid)
                    results.append(adj["ip"]["content"])
                    next_frontier.append(tid)
            frontier = next_frontier
        return results

    def _fire(self, field, args, llm, session_id):
        nid = args[0]
        original = _content(field, nid)
        prompt = (
            "You are reasoning within an SToE Information Field.\n"
            "Evolve this information point ONE step further. Add what is\n"
            "missing, NOT what is already implicit. Do not restate.\n\n"
            f"IP: {original}\n\n"
            "Evolved:"
        )
        response, err = _safe_call(llm, prompt)
        if response is None:
            ghost = field.add_failed(
                from_id=nid, reason=f"RecursionOp LLM failed: {err}",
                operator=self.symbol, session_id=session_id,
            )
            return OperatorResult(
                operator=self.symbol, fired=False,
                reason=f"LLM call failed: {err}",
                produced_node_id=ghost,
                inputs=list(args), llm_prompt=prompt,
            )

        # Dedup check: response vs input + existing chain
        candidates = [original] + self._existing_evolutions(field, nid)
        for cand in candidates:
            sim = _similar(response, cand)
            if sim >= self.dedupe_threshold:
                # The result IS conserved as a Ghost — nothing is lost.
                ghost = field.add_failed(
                    from_id=nid,
                    reason=f"RecursionOp produced near-duplicate (sim={sim:.2f})",
                    operator=self.symbol, session_id=session_id,
                )
                return OperatorResult(
                    operator=self.symbol, fired=False,
                    reason=f"output is near-duplicate of existing chain (sim={sim:.2f})",
                    produced_node_id=ghost,
                    inputs=list(args),
                    llm_prompt=prompt, llm_response=response,
                )

        new_id = field.add_point(
            content=response.strip(),
            category="Evolution",
            operator=self.symbol,
            session_id=session_id,
            metadata={"evolved_from": nid},
        )
        e1 = field.connect(new_id, nid, edge_type="evolved_from",
                           note=f"{self.symbol} recursion of input")
        return OperatorResult(
            operator=self.symbol, fired=True, reason="ok",
            produced_node_id=new_id,
            produced_edge_ids=[e1],
            llm_prompt=prompt, llm_response=response,
            inputs=list(args),
        )


# ---------------------------------------------------------------------------
# !  Disruption
# ---------------------------------------------------------------------------

class DisruptionOp(Operator):
    """
    Challenge the input. Pre-fire check: there must be at least one
    `contradicts` or `failed_from` neighbor of the input (otherwise there
    is nothing structural to disrupt against — the field has no record of
    a previous attempt failing). Without that check, this operator
    collapses to a generic "challenge this" prompt, which is the v1/v82
    failure mode.
    """
    symbol = "!"
    name = "Disruption"
    arity = 1

    def _fire(self, field, args, llm, session_id):
        nid = args[0]
        dead_ends = field.dead_end_query(nid)
        if not dead_ends:
            return OperatorResult(
                operator=self.symbol, fired=False,
                reason="no contradicts/failed_from neighbours — nothing to disrupt against",
                inputs=list(args),
            )

        ctx_lines = []
        for de in dead_ends[:5]:
            ip = de["ip"]
            t = de["edge_type"]
            note = de.get("note") or ""
            content = ip["content"][:200] + ("..." if len(ip["content"]) > 200 else "")
            ctx_lines.append(f"  - [{t}] {content}" + (f"  ({note})" if note else ""))

        prompt = (
            "You are reasoning within an SToE Information Field.\n"
            "An information point and its conserved failed/contradicted neighbours\n"
            "are given. Identify the assumption shared by the input and its failures\n"
            "that, if dropped, opens a different path. One sentence.\n\n"
            f"IP: {_content(field, nid)}\n"
            f"Failed/contradicted neighbours:\n" + "\n".join(ctx_lines) + "\n\n"
            "Hidden assumption:"
        )
        response, err = _safe_call(llm, prompt)
        if response is None:
            ghost = field.add_failed(
                from_id=nid, reason=f"DisruptionOp LLM failed: {err}",
                operator=self.symbol, session_id=session_id,
            )
            return OperatorResult(
                operator=self.symbol, fired=False,
                reason=f"LLM call failed: {err}",
                produced_node_id=ghost,
                inputs=list(args), llm_prompt=prompt,
            )

        new_id = field.add_point(
            content=response.strip(),
            category="Disruption",
            operator=self.symbol,
            session_id=session_id,
            metadata={"disrupts": nid, "via_failures": [de["ip"]["id"] for de in dead_ends]},
        )
        e1 = field.connect(new_id, nid, edge_type="generated_by",
                           note=f"{self.symbol} disruption of input")
        return OperatorResult(
            operator=self.symbol, fired=True, reason="ok",
            produced_node_id=new_id,
            produced_edge_ids=[e1],
            llm_prompt=prompt, llm_response=response,
            inputs=list(args),
        )


# ---------------------------------------------------------------------------
# −  Removal
# ---------------------------------------------------------------------------

class RemovalOp(Operator):
    """
    Remove the weakest connection from the input node. Severs (does NOT
    delete) the lowest-weight active outgoing edge. Refuses if there are
    no active outgoing edges. No LLM call. No new node.
    """
    symbol = "−"
    name = "Removal"
    arity = 1

    def _fire(self, field, args, llm, session_id):
        nid = args[0]
        candidates = []
        for e in field.edges:
            if e["source"] != nid:
                continue
            if e.get("severed"):
                continue
            candidates.append(e)
        if not candidates:
            return OperatorResult(
                operator=self.symbol, fired=False,
                reason="no active outgoing edges to sever",
                inputs=list(args),
            )
        weakest = min(candidates, key=lambda e: float(e.get("weight", 1.0)))
        ok = field.sever(weakest["id"])
        if not ok:
            return OperatorResult(
                operator=self.symbol, fired=False,
                reason=f"sever returned False on edge {weakest['id']}",
                inputs=list(args),
            )
        return OperatorResult(
            operator=self.symbol, fired=True,
            reason=f"severed edge {weakest['id']} (type={weakest['type']}, w={weakest.get('weight', 1.0)})",
            severed_edge_id=weakest["id"],
            inputs=list(args),
        )


# ---------------------------------------------------------------------------
# ∑  Summarize (autoinjective collapse)
# ---------------------------------------------------------------------------

class SummarizeOp(Operator):
    """
    Autoinjective collapse. Takes ≥3 node IDs (typically the current
    session's nodes) and produces a single new node that maps them to one
    "core information point." The new node is connected to each input
    via an `evaluates` edge — the summary IS a structural verdict about
    its inputs, not just text about them.

    Refuses if fewer than 3 inputs are given. The threshold isn't sacred
    — it's there so that "summarize one node" or "summarize two" devolve
    to weaker operators (Recursion or Connection).
    """
    symbol = "∑"
    name = "Summarize"
    arity = None
    min_arity = 3

    def _fire(self, field, args, llm, session_id):
        contents = [_content(field, a) for a in args]
        listing = "\n".join(f"  {i+1}. {c[:200]}" + ("..." if len(c) > 200 else "")
                            for i, c in enumerate(contents))

        prompt = (
            "You are reasoning within an SToE Information Field.\n"
            "Apply autoinjective collapse: distill the following information points\n"
            "to the single essential information point that contains them all.\n"
            "ONE sentence. No preamble.\n\n"
            f"Information points:\n{listing}\n\n"
            "Core IP:"
        )
        response, err = _safe_call(llm, prompt)
        if response is None:
            ghost = field.add_failed(
                from_id=args[0], reason=f"SummarizeOp LLM failed: {err}",
                operator=self.symbol, session_id=session_id,
            )
            return OperatorResult(
                operator=self.symbol, fired=False,
                reason=f"LLM call failed: {err}",
                produced_node_id=ghost,
                inputs=list(args), llm_prompt=prompt,
            )

        new_id = field.add_point(
            content=response.strip(),
            category="Star",
            operator=self.symbol,
            session_id=session_id,
            metadata={"collapses": list(args), "is_summary": True},
        )
        edges = []
        for a in args:
            eid = field.connect(new_id, a, edge_type="evaluates",
                                note=f"{self.symbol} autoinjective collapse")
            if eid:
                edges.append(eid)
        return OperatorResult(
            operator=self.symbol, fired=True, reason="ok",
            produced_node_id=new_id,
            produced_edge_ids=edges,
            llm_prompt=prompt, llm_response=response,
            inputs=list(args),
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def default_registry() -> dict[str, Operator]:
    return {
        "+":      ConnectionOp(),
        "×": SynergyOp(),
        "↻": RecursionOp(),
        "!":      DisruptionOp(),
        "−": RemovalOp(),
        "∑": SummarizeOp(),
    }
