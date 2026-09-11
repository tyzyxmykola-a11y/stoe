"""Generic typed evidence model for StoeCoder repository navigation.

The worker should make progress by learning new facts about the candidate, not by
changing query wording.  This adapter normalizes trusted inspect/search results
into typed evidence and lets the existing anti-loop counter measure stagnation
against that evidence set.

Evidence is deliberately task-agnostic.  It records provenance (implementation,
test, config, docs, runtime, other), polarity (positive/negative), path/span and a
stable observation digest.  It does not encode objective-specific symbol names or
special-case a particular failure trajectory.

Install after anti-loop.  The adapter owns information-gain accounting for the
standalone runtime; repository_navigation.install_information_gain_tracking is
kept only as a compatibility helper for its focused unit tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MethodType
from typing import Any

from repository_navigation import (
    _CONFIG_EXTENSIONS,
    _DOC_EXTENSIONS,
    _LOW_VALUE_PARTS,
    _SOURCE_EXTENSIONS,
    _query_terms,
)

_READ_ONLY = {"inspect", "search"}
_MUTATIONS = {"write", "delete", "move"}
_TEST_PARTS = {"test", "tests", "testing", "__tests__"}
_SOURCE_KINDS = ("implementation", "test", "config", "docs", "runtime", "other")


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _query_family(value: Any) -> str:
    """Canonicalize semantically equivalent word-order variations cheaply."""

    text = _normalized_text(value)
    terms = _query_terms(text)
    if terms:
        return "|".join(sorted(set(terms)))
    return text


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
    if not lines:
        return None
    return [min(lines), max(lines)]


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
            observation="inspect",
            source_kind=source_kind,
            path=path,
            polarity="positive",
            digest=digest,
        )
        return [item]

    if feedback.get("executed", True) is False:
        return []

    # A trusted failed read is still useful once: it conserves negative evidence
    # about this path/query in the current repository state.
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
        observation="inspect",
        source_kind=source_kind,
        path=path,
        polarity="negative",
        digest=digest,
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
            observation="search",
            source_kind="other",
            path=base,
            polarity="negative",
            digest=digest,
        )
        return [item]

    by_path: dict[str, list[dict[str, Any]]] = {}
    for item in matches:
        path = str(item.get("path") or "")
        if path:
            by_path.setdefault(path, []).append(item)

    evidence: list[dict[str, Any]] = []
    for path in files:
        excerpts = by_path.get(path, [])
        excerpt_material = "\n".join(
            f"{item.get('line', '')}:{_normalized_text(item.get('text'))}" for item in excerpts
        )
        # Query wording is intentionally excluded from positive search identity.
        # Rephrasing a search that exposes the same file/excerpt is not new evidence.
        digest = _sha(excerpt_material or path.lower())
        source_kind = _source_kind(path)
        span_values = [int(item["line"]) for item in excerpts if isinstance(item.get("line"), int)]
        span = [min(span_values), max(span_values)] if span_values else None
        item = {
            "observation": "search",
            "source_kind": source_kind,
            "path": path,
            "query_family": query_family,
            "polarity": "positive",
            "digest": digest,
            "span": span,
        }
        item["id"] = _evidence_id(
            observation="search",
            source_kind=source_kind,
            path=path,
            polarity="positive",
            digest=digest,
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
    source_counts = {kind: 0 for kind in _SOURCE_KINDS}
    positive = negative = 0
    for item in items:
        source_counts[str(item.get("source_kind") or "other")] = source_counts.get(
            str(item.get("source_kind") or "other"), 0
        ) + 1
        if item.get("polarity") == "negative":
            negative += 1
        else:
            positive += 1
    kinds = ", ".join(f"{kind}={source_counts.get(kind, 0)}" for kind in _SOURCE_KINDS)
    return (
        f"typed evidence: {len(items)}; source kinds: {kinds}; "
        f"polarity: positive={positive}, negative={negative}"
    )


def install_navigation_evidence(coder: Any) -> None:
    """Normalize read observations and make novelty the progress criterion."""

    if getattr(coder, "_stoe_navigation_evidence_installed", False):
        return

    original_execute_tool = coder._execute_tool
    original_generate = coder._generate_role
    seen_by_task: dict[str, set[str]] = {}
    epoch_by_task: dict[str, int] = {}

    def advance_epoch(task_id: str) -> int:
        seen_by_task.setdefault(task_id, set()).clear()
        epoch_by_task[task_id] = int(epoch_by_task.get(task_id, 0)) + 1
        return epoch_by_task[task_id]

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
                enriched["evidence_epoch"] = advance_epoch(task_id)
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
                enriched["evidence_epoch"] = advance_epoch(task_id)
                enriched["evidence_state_changed"] = True
            else:
                enriched["evidence_epoch"] = epoch_by_task[task_id]
            return enriched

        if kind not in _READ_ONLY or feedback.get("executed", True) is False:
            return feedback

        items = _normalize_evidence(request, feedback)
        summary = _evidence_summary(items)
        enriched = dict(feedback)
        enriched["evidence_items"] = items
        enriched["evidence_summary"] = summary
        enriched["evidence_epoch"] = epoch_by_task[task_id]

        if kind == "search":
            original_stdout = str(feedback.get("stdout") or "").strip()
            enriched["stdout"] = (summary + ("\n" + original_stdout if original_stdout else ""))[:4_000]
        elif feedback.get("ok") is False and items:
            enriched["required_next_action"] = (
                "preserve this negative evidence for the current repository state; do not repeat the same read unchanged. "
                "Choose an action likely to expose different evidence or make repository progress."
            )

        states = getattr(self, "_stoe_workflow_state", None)
        state = states.get(task_id) if isinstance(states, dict) else None
        seen = seen_by_task.setdefault(task_id, set())
        ids = {str(item.get("id") or "") for item in items if str(item.get("id") or "")}
        novel = ids - seen

        if novel:
            seen.update(novel)
            if isinstance(state, dict):
                state["consecutive_exploration"] = 0
                state["exploration_rejections"] = 0
                state["useful_exploration_count"] = int(state.get("useful_exploration_count") or 0) + 1
            enriched["information_gain"] = True
            enriched["novel_evidence_count"] = len(novel)
            enriched["stagnant_exploration_count"] = 0
        else:
            if isinstance(state, dict):
                state.setdefault("useful_exploration_count", 0)
                stagnant = int(state.get("consecutive_exploration") or 0)
                useful = int(state.get("useful_exploration_count") or 0)
            else:
                stagnant = 0
                useful = 0
            enriched["information_gain"] = False
            enriched["novel_evidence_count"] = 0
            enriched["stagnant_exploration_count"] = stagnant
            enriched["useful_exploration_count"] = useful

        if isinstance(state, dict):
            enriched["useful_exploration_count"] = int(state.get("useful_exploration_count") or 0)
        enriched["known_evidence_count"] = len(seen)
        return enriched

    def evidence_generate(self, *, role: str, prompt: dict[str, Any], **kwargs):
        if role == "coder" and isinstance(prompt, dict):
            prompt = dict(prompt)
            tools = dict(prompt.get("available_tools") or {})
            guidance = (
                "trusted read feedback is normalized into typed evidence_items with source_kind, polarity, path/span and stable identity; "
                "source_kind is provenance rather than truth, so implementation/test/config/docs/runtime evidence may play different roles; "
                "changing query wording without exposing a new evidence set is not progress; negative observations are conserved and may be revisited after a repository mutation or failed execution changes the evidence state"
            )
            tools["search"] = str(tools.get("search") or "repository search") + "; " + guidance
            tools["inspect"] = str(tools.get("inspect") or "file inspection") + "; " + guidance
            prompt["available_tools"] = tools
        return original_generate(role=role, prompt=prompt, **kwargs)

    coder._execute_tool = MethodType(evidence_execute_tool, coder)
    coder._generate_role = MethodType(evidence_generate, coder)
    coder._stoe_navigation_evidence_installed = True
    coder._stoe_evidence_seen = seen_by_task
    coder._stoe_evidence_epoch = epoch_by_task
