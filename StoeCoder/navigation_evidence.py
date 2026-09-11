"""Trusted evidence-quality and replay controls for StoeCoder navigation.

Repository navigation already bounds raw search output and anti-loop bounds
consecutive exploration. This adapter adds two missing semantics between them:

* distinguish implementation evidence from tests/support so a regression test
  mentioning an intentionally absent symbol is never presented as the symbol's
  implementation location;
* remember read/search signatures across intervening reads, so workers cannot
  replay the same exploration after a different observation unless a real
  mutation or failed run changes the evidence state.

Install after anti-loop and before information-gain tracking. Raw ripgrep
artifacts remain untouched; only model-facing compact evidence is classified.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import MethodType
from typing import Any

from anti_loop import _capture_candidate_evidence
from repository_navigation import _CONFIG_EXTENSIONS, _SOURCE_EXTENSIONS

_READ_ONLY = {"inspect", "search"}
_MUTATIONS = {"write", "delete", "move"}
_MAX_REPLAY_REJECTIONS = 2

_TEST_PARTS = {"test", "tests", "testing", "__tests__"}


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _read_signature(request: dict[str, Any]) -> tuple[str, str, str] | None:
    kind = str(request.get("kind") or "")
    if kind not in _READ_ONLY:
        return None
    path = str(request.get("path") or ".").replace("\\", "/").rstrip("/") or "."
    query = _normalized_text(request.get("query"))
    return kind, path.lower(), query


def _is_test_path(path: str) -> bool:
    candidate = Path(str(path).replace("\\", "/"))
    parts = {part.lower() for part in candidate.parts}
    name = candidate.name.lower()
    return bool(
        parts & _TEST_PARTS
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def _is_implementation_path(path: str) -> bool:
    if _is_test_path(path):
        return False
    suffix = Path(path).suffix.lower()
    return suffix in _SOURCE_EXTENSIONS or suffix in _CONFIG_EXTENSIONS


def _anchor_symbol(query: Any) -> str | None:
    text = str(query or "").strip()
    function = re.match(r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    if function:
        return function.group(1).lower()
    klass = re.match(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    if klass:
        return klass.group(1).lower()
    return None


def _classify_search_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    raw_files = [str(path) for path in feedback.get("matched_files", []) if str(path)]
    implementation = [path for path in raw_files if _is_implementation_path(path)]
    tests = [path for path in raw_files if _is_test_path(path)]
    support = [path for path in raw_files if path not in implementation and path not in tests]
    visible_files = implementation + support
    visible_set = set(visible_files)

    matches = feedback.get("matches")
    visible_matches = []
    if isinstance(matches, list):
        visible_matches = [
            dict(item) for item in matches
            if isinstance(item, dict) and str(item.get("path") or "") in visible_set
        ]

    result = dict(feedback)
    result["raw_matched_files"] = raw_files
    result["raw_matched_file_count"] = int(feedback.get("matched_file_count") or len(raw_files))
    result["implementation_files"] = implementation
    result["implementation_file_count"] = len(implementation)
    result["test_files"] = tests
    result["test_file_count"] = len(tests)
    result["support_files"] = support
    result["support_file_count"] = len(support)
    result["source_evidence"] = bool(implementation)
    result["test_only"] = bool(raw_files) and bool(tests) and not implementation and not support
    result["matched_files"] = visible_files
    result["matched_file_count"] = len(visible_files)
    result["matches"] = visible_matches

    lines = [f"search mode: {feedback.get('query_mode', 'unknown')}"]
    terms = feedback.get("query_terms")
    if isinstance(terms, list) and terms and feedback.get("query_mode") == "keyword_fallback":
        lines.append("keywords: " + ", ".join(str(term) for term in terms))
    fallback = feedback.get("base_fallback_from")
    if fallback:
        lines.append(f"requested base '{fallback}' was absent; searched repository root instead")

    if implementation:
        lines.append(f"implementation files: {len(implementation)}")
        lines.extend(f"- {path}" for path in implementation)
    else:
        lines.append("implementation files: 0")
    if support:
        lines.append(f"support files: {len(support)}")
        lines.extend(f"- {path}" for path in support)
    if tests:
        lines.append(f"test files: {len(tests)} (supporting evidence only; not implementation locations)")
        lines.extend(f"- {path}" for path in tests)
    if visible_matches:
        lines.append("implementation/support excerpts:")
        for item in visible_matches:
            lines.append(f"{item.get('path')}:{item.get('line')}: {item.get('text')}")

    if result["test_only"]:
        lines.append(
            "warning: this query matched only tests. A regression test can mention an intentionally absent or hypothetical symbol; do not treat test text as proof that an implementation exists."
        )
        result["required_next_action"] = (
            "test-only search evidence does not locate implementation; do not inspect these tests to infer the guessed implementation symbol. Search broader objective/domain terms or inspect an independently identified source file."
        )
    elif not implementation and raw_files:
        result["required_next_action"] = (
            "no implementation file was identified; use support evidence only as context and search broader objective/domain terms before editing"
        )

    result["stdout"] = "\n".join(lines)[:4_000]
    return result


def install_navigation_evidence(coder: Any) -> None:
    """Add source/test classification and cross-tool semantic replay memory."""

    if getattr(coder, "_stoe_navigation_evidence_installed", False):
        return

    original_execute_tool = coder._execute_tool
    original_generate = coder._generate_role
    state_by_task: dict[str, dict[str, Any]] = {}

    def task_state(task_id: str) -> dict[str, Any]:
        return state_by_task.setdefault(task_id, {
            "seen_reads": set(),
            "last_executed_read": None,
            "replay_rejections": 0,
            "absent_symbols": set(),
        })

    def reset_navigation(state: dict[str, Any]) -> None:
        state["seen_reads"].clear()
        state["last_executed_read"] = None
        state["replay_rejections"] = 0
        state["absent_symbols"].clear()

    def reject_replay(self, task_id: str, step: int, worktree, state: dict[str, Any], condition: str, *, kind: str, request: dict[str, Any]):
        state["replay_rejections"] += 1
        self._event(
            "Guard", condition, level="warning", task_id=task_id, step=step, kind=kind,
            path=str(request.get("path") or "."), query=str(request.get("query") or "")[:120],
            required_next_action="use new source evidence or make progress; do not replay the same navigation request",
        )
        if state["replay_rejections"] >= _MAX_REPLAY_REJECTIONS:
            _capture_candidate_evidence(self, worktree)
            raise RuntimeError("coder repeated semantic navigation replay after trusted rejection")
        return {
            "ok": False,
            "executed": False,
            "kind": kind,
            "error": condition,
            "failure_condition": condition,
            "required_next_action": "use new source evidence or make progress; do not replay the same navigation request",
        }

    def evidence_execute_tool(self, task_id: str, step: int, worktree, request: dict[str, Any], allowed_paths):
        kind = str(request.get("kind") or "")
        state = task_state(task_id)
        signature = _read_signature(request)

        if kind == "search":
            query = _normalized_text(request.get("query"))
            if query and query in state["absent_symbols"]:
                condition = (
                    f'search of guessed absent symbol rejected: "{query}" was just absent from a strong code anchor; '
                    "search broader objective/domain terms or another independently identified source file instead"
                )
                return reject_replay(self, task_id, step, worktree, state, condition, kind=kind, request=request)

        # Immediate identical repeats remain anti-loop's responsibility. This
        # guard catches replay only after another read has intervened.
        if signature is not None and signature in state["seen_reads"] and signature != state["last_executed_read"]:
            condition = (
                "semantic replay rejected: this exact read/search request already executed in the current evidence state; "
                "an intervening read does not make it new evidence"
            )
            return reject_replay(self, task_id, step, worktree, state, condition, kind=kind, request=request)

        feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)
        if not isinstance(feedback, dict):
            return feedback

        if kind == "search" and feedback.get("executed", True) is not False and feedback.get("ok") is not False:
            feedback = _classify_search_feedback(feedback)

        if kind == "inspect" and feedback.get("executed", True) is not False:
            if feedback.get("anchored") and feedback.get("ok") is False and feedback.get("query_mode") == "none":
                symbol = _anchor_symbol(request.get("query"))
                if symbol:
                    state["absent_symbols"].add(symbol)
                    feedback = dict(feedback)
                    feedback["absent_symbol"] = symbol
                feedback = dict(feedback)
                feedback["required_next_action"] = (
                    "the requested strong code anchor is absent in this file. Do not search the exact guessed symbol again without independent evidence. Search broader objective/domain terms or inspect another independently identified source file."
                )

        if signature is not None and feedback.get("executed", True) is not False:
            state["seen_reads"].add(signature)
            state["last_executed_read"] = signature
            state["replay_rejections"] = 0

        if kind in _MUTATIONS:
            changed = feedback.get("ok") is not False and feedback.get("executed", True) is not False
            if kind == "write" and "candidate_changed" in feedback:
                changed = changed and bool(feedback.get("candidate_changed"))
            if changed:
                reset_navigation(state)
        elif kind == "run" and feedback.get("executed", True) is not False:
            failed = (
                feedback.get("ok") is False
                or feedback.get("exit_code", 0) != 0
                or bool(feedback.get("timed_out"))
                or bool(feedback.get("cancelled"))
            )
            if failed:
                reset_navigation(state)

        return feedback

    def evidence_generate(self, *, role: str, prompt: dict[str, Any], **kwargs):
        if role == "coder" and isinstance(prompt, dict):
            prompt = dict(prompt)
            tools = dict(prompt.get("available_tools") or {})
            tools["search"] = (
                str(tools.get("search") or "repository search")
                + "; results distinguish implementation_files from test_files/support_files; test-only hits are not implementation evidence; exact read/search replays remain blocked across intervening reads until a real mutation or failed run changes the evidence state"
            )
            prompt["available_tools"] = tools
        return original_generate(role=role, prompt=prompt, **kwargs)

    coder._execute_tool = MethodType(evidence_execute_tool, coder)
    coder._generate_role = MethodType(evidence_generate, coder)
    coder._stoe_navigation_evidence_installed = True
    coder._stoe_navigation_evidence_state = state_by_task
