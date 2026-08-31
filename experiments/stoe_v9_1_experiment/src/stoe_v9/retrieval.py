from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Protocol

from .graph import InformationGraph
from .models import ObserverState, RetrievalResult


_TOKENS = re.compile(r"[a-z0-9]+")
_MEMORY_REF = re.compile(r"\[MEMORY_REF ([^\]]+)\]")
_TRUNCATION_MARKER = "[CONTENT_TRUNCATED]"


@dataclass(slots=True)
class SerializedArtifact:
    ref: str
    origin: str
    relation_context: str
    original_content_chars: int
    serialized_content_chars: int
    serialized_block_chars: int
    truncated: bool
    serialized_block: str


@dataclass(slots=True)
class SerializedMemory:
    text: str
    selected_artifact_count: int
    selected_artifact_refs: list[str]
    model_visible_artifact_count: int
    model_visible_memory_refs: list[str]
    serialized_memory_char_count: int
    artifacts: list[SerializedArtifact]

    def to_dict(self) -> dict:
        return asdict(self)


def tokens(text: str) -> list[str]:
    return _TOKENS.findall(text.lower())


class EmbeddingBackend(Protocol):
    name: str

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicHashEmbedder:
    name = "deterministic-hash-development-only"

    def __init__(self, dimensions: int = 256):
        self.dimensions = dimensions

    def encode(self, texts: list[str]) -> list[list[float]]:
        output = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in tokens(text):
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                vector[index] += 1.0 if digest[4] % 2 else -1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            output.append([value / norm for value in vector])
        return output


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def dense_retrieve(
    graph: InformationGraph,
    state: ObserverState,
    embedder: EmbeddingBackend,
    *,
    limit: int,
    include_failures: bool = True,
) -> RetrievalResult:
    refs = graph.eligible_refs(include_failures=include_failures)
    query = state.relevance_text()
    vectors = embedder.encode([query] + [graph.nodes[ref].content for ref in refs])
    scored = sorted(
        ((cosine(vectors[0], vector), ref) for ref, vector in zip(refs, vectors[1:])),
        key=lambda item: (-item[0], item[1]),
    )[:limit]
    return RetrievalResult(
        refs=[ref for _, ref in scored], method="dense_semantic",
        scores=[score for score, _ in scored], realized_artifact_count=len(scored),
    )


def bm25_retrieve(
    graph: InformationGraph,
    state: ObserverState,
    *,
    limit: int,
    include_failures: bool = True,
) -> RetrievalResult:
    refs = graph.eligible_refs(include_failures=include_failures)
    docs = [tokens(graph.nodes[ref].content) for ref in refs]
    query = tokens(state.relevance_text())
    if not docs:
        return RetrievalResult([], "bm25", [], realized_artifact_count=0)
    average = sum(map(len, docs)) / len(docs)
    df = Counter()
    for doc in docs:
        df.update(set(doc))
    scored = []
    for ref, doc in zip(refs, docs):
        counts = Counter(doc)
        value = 0.0
        for token in query:
            frequency = counts.get(token, 0)
            if not frequency:
                continue
            inverse = math.log(1 + (len(docs) - df[token] + 0.5) / (df[token] + 0.5))
            denominator = frequency + 1.5 * (0.25 + 0.75 * len(doc) / average)
            value += inverse * frequency * 2.5 / denominator
        scored.append((value, ref))
    chosen = sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    return RetrievalResult(
        refs=[ref for _, ref in chosen], method="bm25",
        scores=[score for score, _ in chosen], realized_artifact_count=len(chosen),
    )


def success_retrieve(graph: InformationGraph, *, limit: int) -> RetrievalResult:
    nodes = [
        node for node in graph.nodes.values()
        if node.visible and node.outcome == "success"
        and node.kind not in {"current_state", "domain_root", "bookkeeping"}
    ]
    nodes.sort(key=lambda node: (-node.created_order, node.ref))
    chosen = nodes[:limit]
    return RetrievalResult(
        refs=[node.ref for node in chosen], method="success_recency",
        scores=[float(node.created_order) for node in chosen],
        realized_artifact_count=len(chosen),
    )


def format_context(
    graph: InformationGraph,
    result: RetrievalResult,
    *,
    typed: bool,
    max_chars: int,
) -> str:
    """Compatibility wrapper around the v9.1 lossless-selection serializer."""
    return serialize_memory(graph, result, typed=typed, max_chars=max_chars).text


def extract_memory_refs(text: str) -> list[str]:
    return _MEMORY_REF.findall(text)


def serialize_memory(
    graph: InformationGraph,
    result: RetrievalResult,
    *,
    typed: bool,
    max_chars: int,
) -> SerializedMemory:
    """Serialize every selected artifact within one fixed total character budget.

    Selection is immutable here. Each artifact receives an independent,
    deterministic content allowance, so an early oversized artifact cannot
    suppress a later selected artifact.
    """
    selected_refs = list(result.refs)
    if not selected_refs:
        return SerializedMemory("", 0, [], 0, [], 0, [])
    if len(set(selected_refs)) != len(selected_refs):
        raise AssertionError(f"selected memory refs are not unique: {selected_refs!r}")

    trace_by_ref = {trace.candidate_ip: trace for trace in result.traces}
    headers: list[tuple[str, str, str, str]] = []
    for ref in selected_refs:
        if ref not in graph.nodes:
            raise AssertionError(f"selected memory ref is absent from graph: {ref}")
        node = graph.nodes[ref]
        origin = str(node.metadata.get("origin", "runtime_reasoning"))
        relation = str(node.metadata.get("relation_context", "connected_to")) if typed else "untyped"
        trace = trace_by_ref.get(ref)
        if typed and trace and trace.edge_types:
            relation = ">".join(
                f"{relation_type}:{direction}"
                for relation_type, direction in zip(trace.edge_types, trace.edge_directions)
            )
        header = (
            f"[MEMORY_REF {ref}] KIND={node.kind}; ORIGIN={origin}; "
            f"OUTCOME={node.outcome}; RELATION_CONTEXT={relation}; SEMANTIC_CONTENT="
        )
        headers.append((ref, origin, relation, header))

    separator_chars = len(selected_refs) - 1
    fixed_chars = sum(len(header) for _, _, _, header in headers) + separator_chars
    if fixed_chars > max_chars:
        raise AssertionError(
            f"memory metadata alone exceeds budget: {fixed_chars} > {max_chars}"
        )
    available = max_chars - fixed_chars
    base, remainder = divmod(available, len(selected_refs))

    artifacts: list[SerializedArtifact] = []
    blocks: list[str] = []
    for index, (ref, origin, relation, header) in enumerate(headers):
        content = graph.nodes[ref].content
        allowance = base + (1 if index < remainder else 0)
        if len(content) <= allowance:
            payload = content
            truncated = False
        else:
            if allowance < len(_TRUNCATION_MARKER):
                raise AssertionError(
                    f"budget cannot preserve truncation marker for selected artifact {ref}"
                )
            payload = content[: allowance - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER
            truncated = True
        block = header + payload
        blocks.append(block)
        artifacts.append(SerializedArtifact(
            ref=ref,
            origin=origin,
            relation_context=relation,
            original_content_chars=len(content),
            serialized_content_chars=len(payload),
            serialized_block_chars=len(block),
            truncated=truncated,
            serialized_block=block,
        ))

    text = "\n".join(blocks)
    visible_refs = extract_memory_refs(text)
    if visible_refs != selected_refs:
        raise AssertionError(
            f"selected/visible memory mismatch: selected={selected_refs!r}, visible={visible_refs!r}"
        )
    if len(set(visible_refs)) != len(visible_refs):
        raise AssertionError(f"visible memory refs are not unique: {visible_refs!r}")
    if len(text) > max_chars:
        raise AssertionError(f"serialized memory exceeds budget: {len(text)} > {max_chars}")
    return SerializedMemory(
        text=text,
        selected_artifact_count=len(selected_refs),
        selected_artifact_refs=selected_refs,
        model_visible_artifact_count=len(visible_refs),
        model_visible_memory_refs=visible_refs,
        serialized_memory_char_count=len(text),
        artifacts=artifacts,
    )


def assert_serialized_memory(text: str, selected_refs: list[str], *, max_chars: int) -> list[str]:
    """Fatal final-input invariant, called immediately before generation."""
    visible_refs = extract_memory_refs(text)
    if visible_refs != selected_refs:
        raise AssertionError(
            f"fatal selected/visible memory mismatch: selected={selected_refs!r}, visible={visible_refs!r}"
        )
    if len(set(visible_refs)) != len(visible_refs):
        raise AssertionError(f"fatal duplicate visible memory refs: {visible_refs!r}")
    if len(text) > max_chars:
        raise AssertionError(f"fatal memory budget violation: {len(text)} > {max_chars}")
    return visible_refs
