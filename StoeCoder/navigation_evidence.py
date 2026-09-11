"""Generic typed evidence graph for StoeCoder repository navigation.

Trusted inspect/search results are conserved as typed evidence. Novel evidence is
not automatically progress: the anti-loop stagnation counter is reset only when
new evidence extends a relation that was established by an objective-directed
search or by evidence already observed on that path.

Connectivity is causal rather than lexical. Merely inventing a symbol whose words
resemble the objective does not create a new connected path. Search establishes
candidate paths; later inspection may extend those paths only from terms grounded
in trusted search excerpts or already-grounded bounded inspection evidence.

Evidence records provenance (implementation, test, config, docs, runtime, other),
polarity (positive/negative), path/span, stable identity, and query family. A
repository mutation or failed execution advances the evidence epoch, making old
observations legitimately discoverable again in the changed state.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import MethodType
from typing import Any

from repository_navigation import (
    _CONFIG_EXTENSIONS,
    _DOC_EXTENSIONS,
    _LOW_VALUE_PARTS,
    _QUERY_STOPWORDS,
    _SOURCE_EXTENSIONS,
)

_READ_ONLY = {"inspect", "search"}
_MUTATIONS = {"write", "delete", "move"}
_TEST_PARTS = {"test", "tests", "testing", "__tests__"}
_SOURCE_KINDS = ("implementation", "test", "config", "docs", "runtime", "other")
_MAX_SEMANTIC_TERMS = 64
_ANCHOR_SYNTAX_TERMS = {"def", "class", "function", "const", "let", "var", "async", "await"}


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _semantic_terms(value: Any) -> set[str]:
    """Extract cheap task-agnostic semantic terms, including code identifiers."""

    text = str(value or "")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"[_\-./\\]+", " ", text).lower()
    terms: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", text):
        if len(token) < 3 or token in _QUERY_STOPWORDS:
            continue
        terms.add(token)
        if len(terms) >= _MAX_SEMANTIC_TERMS:
            break
    return terms


def _anchor_terms(value: Any) -> set[str]:
    return _semantic_terms(value) - _ANCHOR_SYNTAX_TERMS


def _query_family(value: Any) -> str:
    terms = _semantic_terms(value)
    if terms:
        return "|".join(sorted(terms))
    return _normalized_text(value)


def _source_kind(path: Any) -> str:
    candidate = Path(str(path or "").replace("\\", "/"))
    parts = {part.lower() for part in candidate.parts}
    name = candidate.name.lower()
    suffix = candidate.suffix.lower()
    if (
        parts & _TEST_PARTS
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    ):
        return "test"
    if parts & _LOW_VALUE_PARTS:
        return "runtime"
    if suffix in _CONFIG_EXTENSIONS:
        return "config"
    if suffix in _DOC_EXTENSIONS:
        return "docs"
    if suffix in _SOURCE_EXTENSIONS:
        return "implementation"
    return "other"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _evidence_id(*, observation: str, source_kind: str, path: str, polarity: str, digest: str) -> str:
    payload = json.dumps(
        {
            "observation": observation,
            "source_kind": source_kind,
            "path": path,
            "polarity": polarity,
            "digest": digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha(payload)


def _span_from_feedback(feedback: dict[str, Any]) -> list[int] | None:
    values = feedback.get("match_lines")
    if not isinstance(values, list):
        return None
    lines = [int(value) for value in values if isinstance(value, int) and value > 0]
    return [min(lines), max(lines)] if lines else None


def _inspect_evidence(request: dict[str, Any], feedback: dict[str, Any]) -> list[dict[str, Any]]:
    path = str(feedback.get("path") or request.get("path") or "")
    source_kind = _source_kind(path)
    query_family = _query_family(feedback.get("query") or request.get("query"))
    content = feedback.get("content")
    if feedback.get("ok") is not False and isinstance(content, str) and content:
        digest = _sha(content)
        item = {
            "observation": "inspect",
            "source_kind": source_kind,
            "path": path,
            "query_family": query_family,
            "polarity": "positive",
            "digest": digest,
            "span": _span_from_feedback(feedback),
        }
        item["id"] = _evidence_id(
            observation="inspect", source_kind=source_kind, path=path,
            polarity="positive", digest=digest,
        )
        return [item]
    if feedback.get("executed", True) is False:
        return []
    reason = _normalized_text(feedback.get("error") or "no matching evidence")
    digest = _sha(f"{query_family}|{reason}")
    item = {
        "observation": "inspect",
        "source_kind": source_kind,
        "path": path,
        "query_family": query_family,
        "polarity": "negative",
        "digest": digest,
        "span": None,
    }
    item["id"] = _evidence_id(
        observation="inspect", source_kind=source_kind, path=path,
        polarity="negative", digest=digest,
    )
    return [item]


def _search_evidence(request: dict[str, Any], feedback: dict[str, Any]) -> list[dict[str, Any]]:
    query_family = _query_family(feedback.get("query") or request.get("query"))
    base = str(feedback.get("base") or request.get("path") or ".")
    files = feedback.get("matched_files")
    files = [str(path) for path in files] if isinstance(files, list) else []
    matches = feedback.get("matches")
    matches = [item for item in matches if isinstance(item, dict)] if isinstance(matches, list) else []
    if not files:
        if feedback.get("executed", True) is False:
            return []
        digest = _sha(f"{base.lower()}|{query_family}|no-files")
        item = {
            "observation": "search",
            "source_kind": "other",
            "path": base,
            "query_family": query_family,
            "polarity": "negative",
            "digest": digest,
            "span": None,
        }
        item["id"] = _evidence_id(
            observation="search", source_kind="other", path=base,
            polarity="negative", digest=digest,
        )
        return [item]

    by_path: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        path = str(match.get("path") or "")
        if path:
            by_path.setdefault(path, []).append(match)

    evidence: list[dict[str, Any]] = []
    for path in files:
        excerpts = by_path.get(path, [])
        excerpt_material = "\n".join(
            f"{item.get('line', '')}:{_normalized_text(item.get('text'))}" for item in excerpts
        )
        digest = _sha(excerpt_material or path.lower())
        source_kind = _source_kind(path)
        span_values = [int(item["line"]) for item in excerpts if isinstance(item.get("line"), int)]
        item = {
            "observation": "search",
            "source_kind": source_kind,
            "path": path,
            "query_family": query_family,
            "polarity": "positive",
            "digest": digest,
            "span": [min(span_values), max(span_values)] if span_values else None,
        }
        item["id"] = _evidence_id(
            observation="search", source_kind=source_kind, path=path,
            polarity="positive", digest=digest,
        )
        evidence.append(item)
    return evidence


def _normalize_evidence(request: dict[str, Any], feedback: dict[str, Any]) -> list[dict[str, Any]]:
    kind = str(request.get("kind") or "")
    if kind == "inspect":
        return _inspect_evidence(request, feedback)
    if kind == "search":
        return _search_evidence(request, feedback)
    return []


def _evidence_summary(items: list[dict[str, Any]]) -> str:
    counts = {kind: 0 for kind in _SOURCE_KINDS}
    positive = negative = 0
    for item in items:
        kind = str(item.get("source_kind") or "other")
        counts[kind] = counts.get(kind, 0) + 1
        if item.get("polarity") == "negative":
            negative += 1
        else:
            positive += 1
    kinds = ", ".join(f"{kind}={counts.get(kind, 0)}" for kind in _SOURCE_KINDS)
    return f"typed evidence: {len(items)}; source kinds: {kinds}; polarity: positive={positive}, negative={negative}"


def _task_id_from_generate(kwargs: dict[str, Any]) -> str | None:
    action_id = str(kwargs.get("action_id") or "")
    if not action_id:
        return None
    return action_id.split(":", 1)[0] or None


def _objective_directed_query(query: Any, objective_terms: set[str]) -> bool:
    """Require the whole search idea to be grounded in the operator objective."""

    terms = _anchor_terms(query)
    return bool(terms) and terms.issubset(objective_terms)


def _match_terms_by_path(feedback: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    matches = feedback.get("matches")
    if not isinstance(matches, list):
        return result
    for item in matches:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path:
            continue
        result.setdefault(path, set()).update(_semantic_terms(item.get("text")))
    return result


def _rank_connected_search_feedback(
    feedback: dict[str, Any], query_terms: set[str], objective_terms: set[str]
) -> dict[str, Any]:
    """Rank candidate paths by trusted excerpt relation, never by guessed semantics."""

    files = feedback.get("matched_files")
    matches = feedback.get("matches")
    if not isinstance(files, list) or not files:
        return feedback
    matches = [item for item in matches if isinstance(item, dict)] if isinstance(matches, list) else []
    by_path: dict[str, list[dict[str, Any]]] = {}
    for item in matches:
        path = str(item.get("path") or "")
        if path:
            by_path.setdefault(path, []).append(item)

    original_index = {str(path): index for index, path in enumerate(files)}

    def score(raw_path: Any) -> tuple[int, int, int, int]:
        path = str(raw_path)
        excerpts = by_path.get(path, [])
        excerpt_terms: set[str] = set()
        for item in excerpts:
            excerpt_terms.update(_semantic_terms(item.get("text")))
        return (
            len(excerpt_terms & query_terms),
            len(excerpt_terms & objective_terms),
            1 if excerpts else 0,
            -original_index.get(path, 10_000),
        )

    ranked_files = sorted([str(path) for path in files], key=score, reverse=True)
    rank = {path: index for index, path in enumerate(ranked_files)}
    ranked_matches = sorted(
        matches,
        key=lambda item: (rank.get(str(item.get("path") or ""), len(ranked_files)), int(item.get("line") or 0)),
    )
    enriched = dict(feedback)
    enriched["matched_files"] = ranked_files
    enriched["matches"] = ranked_matches
    return enriched


def install_navigation_evidence(coder: Any) -> None:
    """Conserve all evidence while letting only evidence-grounded novelty progress."""

    if getattr(coder, "_stoe_navigation_evidence_installed", False):
        return

    original_execute_tool = coder._execute_tool
    original_generate = coder._generate_role
    seen_by_task: dict[str, set[str]] = {}
    epoch_by_task: dict[str, int] = {}
    objective_terms_by_task: dict[str, set[str]] = {}
    connected_paths_by_task: dict[str, set[str]] = {}
    path_terms_by_task: dict[str, dict[str, set[str]]] = {}
    expanded_paths_by_task: dict[str, set[str]] = {}
    frontier_order_by_task: dict[str, list[str]] = {}

    def reset_graph(task_id: str) -> int:
        seen_by_task.setdefault(task_id, set()).clear()
        connected_paths_by_task.setdefault(task_id, set()).clear()
        path_terms_by_task.setdefault(task_id, {}).clear()
        expanded_paths_by_task.setdefault(task_id, set()).clear()
        frontier_order_by_task.setdefault(task_id, []).clear()
        epoch_by_task[task_id] = int(epoch_by_task.get(task_id, 0)) + 1
        return epoch_by_task[task_id]

    def current_frontier(task_id: str) -> list[str]:
        connected = connected_paths_by_task.setdefault(task_id, set())
        expanded = expanded_paths_by_task.setdefault(task_id, set())
        order = frontier_order_by_task.setdefault(task_id, [])
        return [path for path in order if path in connected and path not in expanded]

    def connection_for(
        task_id: str, request: dict[str, Any], items: list[dict[str, Any]]
    ) -> tuple[bool, str]:
        objective_terms = objective_terms_by_task.get(task_id, set())
        if not objective_terms:
            return bool(items), "no_objective_context"

        kind = str(request.get("kind") or "")
        path = str(request.get("path") or "").replace("\\", "/")
        connected_paths = connected_paths_by_task.setdefault(task_id, set())
        expanded_paths = expanded_paths_by_task.setdefault(task_id, set())
        path_terms = path_terms_by_task.setdefault(task_id, {})

        if kind == "search":
            if _objective_directed_query(request.get("query"), objective_terms):
                return True, "objective_search"
            return False, "ungrounded_search"

        if kind == "inspect" and path in connected_paths:
            query_terms = _anchor_terms(request.get("query"))
            grounded_terms = path_terms.setdefault(path, set())
            if path not in expanded_paths:
                if not query_terms or query_terms.issubset(grounded_terms):
                    return True, "connected_path_first_inspect"
                return False, "ungrounded_anchor"
            if query_terms and query_terms.issubset(grounded_terms):
                return True, "grounded_path_extension"
            return False, "ungrounded_anchor" if query_terms else "already_expanded_path"

        return False, "unconnected_path"

    def evidence_execute_tool(self, task_id: str, step: int, worktree, request: dict[str, Any], allowed_paths):
        feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)
        if not isinstance(feedback, dict):
            return feedback

        kind = str(request.get("kind") or "")
        epoch_by_task.setdefault(task_id, 0)

        if kind in _MUTATIONS:
            changed = feedback.get("ok") is not False and feedback.get("executed", True) is not False
            if kind == "write" and "candidate_changed" in feedback:
                changed = changed and bool(feedback.get("candidate_changed"))
            enriched = dict(feedback)
            if changed:
                enriched["evidence_epoch"] = reset_graph(task_id)
                enriched["evidence_state_changed"] = True
            else:
                enriched["evidence_epoch"] = epoch_by_task[task_id]
            return enriched

        if kind == "run":
            failed = (
                feedback.get("executed", True) is not False
                and (
                    feedback.get("ok") is False
                    or feedback.get("exit_code", 0) != 0
                    or bool(feedback.get("timed_out"))
                    or bool(feedback.get("cancelled"))
                )
            )
            enriched = dict(feedback)
            if failed:
                enriched["evidence_epoch"] = reset_graph(task_id)
                enriched["evidence_state_changed"] = True
            else:
                enriched["evidence_epoch"] = epoch_by_task[task_id]
            return enriched

        if kind not in _READ_ONLY or feedback.get("executed", True) is False:
            return feedback

        items = _normalize_evidence(request, feedback)
        connected, basis = connection_for(task_id, request, items)
        objective_terms = objective_terms_by_task.get(task_id, set())
        query_terms = _anchor_terms(request.get("query"))

        if kind == "search" and connected:
            feedback = _rank_connected_search_feedback(feedback, query_terms, objective_terms)
            items = _normalize_evidence(request, feedback)

        enriched = dict(feedback)
        enriched["evidence_items"] = items
        enriched["evidence_epoch"] = epoch_by_task[task_id]

        seen = seen_by_task.setdefault(task_id, set())
        ids = {str(item.get("id") or "") for item in items if str(item.get("id") or "")}
        novel = ids - seen
        if novel:
            seen.update(novel)
        connected_novel = novel if connected else set()

        if connected_novel and kind == "search":
            match_terms = _match_terms_by_path(feedback)
            connected_paths = connected_paths_by_task.setdefault(task_id, set())
            path_terms = path_terms_by_task.setdefault(task_id, {})
            frontier = frontier_order_by_task.setdefault(task_id, [])
            for item in items:
                path = str(item.get("path") or "")
                if not path or item.get("polarity") != "positive":
                    continue
                connected_paths.add(path)
                if path not in frontier:
                    frontier.append(path)
                grounded = path_terms.setdefault(path, set())
                grounded.update(query_terms)
                grounded.update(match_terms.get(path, set()))

        if connected_novel and kind == "inspect":
            path = str(request.get("path") or "").replace("\\", "/")
            if path:
                expanded_paths_by_task.setdefault(task_id, set()).add(path)
                grounded = path_terms_by_task.setdefault(task_id, {}).setdefault(path, set())
                inspect_query_terms = _anchor_terms(request.get("query"))
                grounded.update(inspect_query_terms)
                content = feedback.get("content")
                if isinstance(content, str) and content:
                    content_terms = _semantic_terms(content)
                    if inspect_query_terms:
                        grounded.update(content_terms)
                    else:
                        grounded.update(content_terms & objective_terms)

        states = getattr(self, "_stoe_workflow_state", None)
        state = states.get(task_id) if isinstance(states, dict) else None
        if connected_novel and isinstance(state, dict):
            state["consecutive_exploration"] = 0
            state["exploration_rejections"] = 0
            state["useful_exploration_count"] = int(state.get("useful_exploration_count") or 0) + 1
        elif isinstance(state, dict):
            state.setdefault("useful_exploration_count", 0)

        frontier = current_frontier(task_id)
        enriched["information_gain"] = bool(novel)
        enriched["novel_evidence_count"] = len(novel)
        enriched["connected_progress"] = bool(connected_novel)
        enriched["connected_novel_evidence_count"] = len(connected_novel)
        enriched["connection_basis"] = basis
        enriched["known_evidence_count"] = len(seen)
        enriched["objective_term_count"] = len(objective_terms)
        enriched["connected_frontier"] = frontier[:8]
        enriched["stagnant_exploration_count"] = int(state.get("consecutive_exploration") or 0) if isinstance(state, dict) else 0
        enriched["useful_exploration_count"] = int(state.get("useful_exploration_count") or 0) if isinstance(state, dict) else 0

        summary = _evidence_summary(items)
        progress = f"connected progress: {'yes' if connected_novel else 'no'} ({basis}); novel evidence={len(novel)}"
        frontier_text = ""
        if frontier:
            frontier_text = "; unexpanded connected frontier: " + ", ".join(frontier[:6])
        enriched["evidence_summary"] = summary + "; " + progress + frontier_text
        if kind == "search":
            original_stdout = str(feedback.get("stdout") or "").strip()
            enriched["stdout"] = (enriched["evidence_summary"] + ("\n" + original_stdout if original_stdout else ""))[:4_000]

        if feedback.get("ok") is False and items:
            if connected_novel:
                enriched["required_next_action"] = (
                    "preserve this grounded negative evidence; do not repeat the same read unchanged. "
                    "Continue from another evidence-grounded relation or make repository progress."
                )
            else:
                enriched["required_next_action"] = (
                    "preserve this negative evidence, but it did not extend a grounded relation. "
                    + (
                        "Return to an unexpanded connected candidate path: " + ", ".join(frontier[:4])
                        if frontier else
                        "Return to an objective-directed search or make repository progress."
                    )
                )
        elif novel and not connected_novel:
            enriched["required_next_action"] = (
                "this observation is conserved as new evidence but did not extend an evidence-grounded path; "
                + (
                    "inspect an unexpanded connected candidate instead: " + ", ".join(frontier[:4])
                    if frontier else
                    "return to an objective-directed search or make repository progress"
                )
            )
        return enriched

    def evidence_generate(self, *, role: str, prompt: dict[str, Any], **kwargs):
        if role == "coder" and isinstance(prompt, dict):
            task_id = _task_id_from_generate(kwargs)
            if task_id:
                objective_terms_by_task[task_id] = _semantic_terms(prompt.get("objective"))
        return original_generate(role=role, prompt=prompt, **kwargs)

    coder._execute_tool = MethodType(evidence_execute_tool, coder)
    coder._generate_role = MethodType(evidence_generate, coder)
    coder._stoe_navigation_evidence_installed = True
    coder._stoe_evidence_seen = seen_by_task
    coder._stoe_evidence_epoch = epoch_by_task
    coder._stoe_evidence_objective_terms = objective_terms_by_task
    coder._stoe_evidence_connected_paths = connected_paths_by_task
    coder._stoe_evidence_path_terms = path_terms_by_task
    coder._stoe_evidence_frontier = frontier_order_by_task
