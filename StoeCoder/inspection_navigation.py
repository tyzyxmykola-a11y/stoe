"""Trusted large-file inspection and model-tool request normalization.

Repository search can locate a relevant file, but an unanchored inspect of a
large file only exposes its prefix. This adapter lets the worker reuse the
existing optional ``query`` field on ``inspect`` to request bounded line windows
from anywhere in one file. It also canonicalizes a common malformed model
search request where the query is emitted inside ``command`` instead of
``query``.

Install this inside the anti-loop wrapper so anchored reads still pass through
the normal read-only boundedness and information-gain controls.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import MethodType
from typing import Any

from repository_navigation import _query_terms

_MAX_CONTENT_CHARS = 16_000
_MAX_MATCH_LINES = 8
_CONTEXT_LINES = 7
_GENERIC_ANCHOR_TERMS = {"def", "class", "async", "return", "self", "str", "int", "bool", "none"}


def _safe_target(worktree: Any, value: Any) -> tuple[Path, str]:
    root = Path(worktree).resolve()
    raw = str(value or "")
    if not raw or "\x00" in raw:
        raise ValueError("inspect path is empty or invalid")
    target = (root / raw).resolve()
    if target != root and root not in target.parents:
        raise ValueError("inspect path escapes candidate workspace")
    relative = target.relative_to(root).as_posix()
    if relative == ".git" or relative.startswith(".git/"):
        raise ValueError("worker cannot inspect Git internals")
    if any(part.lower() in {".env", "credentials.json", "id_rsa", "id_ed25519"} for part in target.parts):
        raise ValueError("credential-bearing path is unavailable to workers")
    return target, relative


def _canonicalize_tool_request(value: Any) -> Any:
    """Normalize only the observed safe search-shorthand form.

    Exact model output remains available in the Model I/O flight recorder. The
    trusted executive receives a canonical request so downstream guards,
    diagnostics, and history all see the actual query that will execute.
    """

    if not isinstance(value, dict) or str(value.get("kind") or "") != "search":
        return value
    if str(value.get("query") or "").strip():
        return value
    command = value.get("command")
    if not isinstance(command, list) or len(command) < 2:
        return value
    if str(command[0]).strip().lower() != "search":
        return value
    query = " ".join(str(item).strip() for item in command[1:] if str(item).strip()).strip()
    if not query:
        return value
    normalized = dict(value)
    normalized["query"] = query
    normalized.pop("command", None)
    return normalized


def _strong_code_anchor(query: str) -> re.Pattern[str] | None:
    """Return a declaration pattern that must match strongly.

    Declaration-shaped anchors should never degrade into weak keyword matches
    such as matching every ``def`` line when the requested function does not
    exist. Plain identifiers remain useful as partial navigation anchors and are
    handled by the normal exact/keyword path below.
    """

    stripped = query.strip()
    function = re.match(r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
    if function:
        name = re.escape(function.group(1))
        return re.compile(rf"^\s*(?:async\s+)?def\s+{name}\s*\(")
    klass = re.match(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
    if klass:
        name = re.escape(klass.group(1))
        return re.compile(rf"^\s*class\s+{name}\b")
    return None


def _match_lines(lines: list[str], query: str) -> tuple[str, list[int]]:
    """Return strong declaration matches, exact regex matches, or confident keyword matches."""

    strong = _strong_code_anchor(query)
    if strong is not None:
        matches = [index for index, line in enumerate(lines) if strong.search(line)][:_MAX_MATCH_LINES]
        return ("symbol", matches) if matches else ("none", [])

    exact: list[int] = []
    try:
        pattern = re.compile(query)
    except re.error:
        pattern = re.compile(re.escape(query))
    for index, line in enumerate(lines):
        if pattern.search(line):
            exact.append(index)
            if len(exact) >= _MAX_MATCH_LINES:
                break
    if exact:
        return "exact", exact

    terms = [term for term in _query_terms(query) if term not in _GENERIC_ANCHOR_TERMS]
    if not terms:
        return "none", []
    minimum_score = 1 if len(terms) == 1 else max(2, (len(terms) + 1) // 2)
    scored: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        lowered = line.lower()
        score = sum(1 for term in terms if term in lowered)
        if score >= minimum_score:
            scored.append((-score, index))
    scored.sort()
    selected = sorted(index for _, index in scored[:_MAX_MATCH_LINES])
    return ("keyword_fallback", selected) if selected else ("none", [])


def _merge_windows(match_lines: list[int], total_lines: int) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for index in match_lines:
        start = max(0, index - _CONTEXT_LINES)
        end = min(total_lines, index + _CONTEXT_LINES + 1)
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    return windows


def _window_content(path: str, lines: list[str], windows: list[tuple[int, int]]) -> str:
    chunks: list[str] = []
    used = 0
    for start, end in windows:
        header = f"# {path} lines {start + 1}-{end}\n"
        body = "".join(f"{index + 1}: {lines[index]}" for index in range(start, end))
        chunk = header + body
        remaining = _MAX_CONTENT_CHARS - used
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        chunks.append(chunk)
        used += len(chunk)
        if used >= _MAX_CONTENT_CHARS:
            break
    return "\n".join(chunks)


def install_inspection_navigation(coder: Any) -> None:
    """Add query-addressable inspect while preserving the core tool schema."""

    if getattr(coder, "_stoe_inspection_navigation_installed", False):
        return

    original_execute_tool = coder._execute_tool
    original_generate = coder._generate_role

    def navigated_execute_tool(self, task_id: str, step: int, worktree, request: dict[str, Any], allowed_paths):
        kind = str(request.get("kind") or "")
        query = str(request.get("query") or "").strip()
        if kind != "inspect" or not query:
            feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)
            if kind == "inspect" and isinstance(feedback, dict) and feedback.get("ok") is not False and feedback.get("truncated"):
                feedback = dict(feedback)
                feedback["anchor_available"] = True
                feedback["required_next_action"] = (
                    "this file is truncated; if more evidence from this file is necessary, re-inspect the same path once with query set to a relevant identifier or phrase instead of repeating the unanchored inspect"
                )
            return feedback

        target, relative = _safe_target(worktree, request.get("path"))
        if allowed_paths and relative not in allowed_paths:
            raise PermissionError(f"path outside bounded worker scope: {relative}")
        if not target.is_file():
            return {
                "ok": False,
                "kind": "inspect",
                "executed": True,
                "path": relative,
                "query": query,
                "anchored": True,
                "error": "file not found",
                "required_next_action": "search from repository root '.' for relevant identifiers instead of guessing another path",
            }

        data = target.read_text(encoding="utf-8", errors="replace")
        lines = data.splitlines(keepends=True)
        mode, matches = _match_lines(lines, query)
        if not matches:
            return {
                "ok": False,
                "kind": "inspect",
                "executed": True,
                "path": relative,
                "query": query,
                "anchored": True,
                "query_mode": mode,
                "match_count": 0,
                "error": "inspect anchor produced no matching lines",
                "required_next_action": "the requested anchor is absent; use compact repository search to locate the real symbol or inspect another relevant file instead of repeating this anchor",
            }

        windows = _merge_windows(matches, len(lines))
        content = _window_content(relative, lines, windows)
        return {
            "ok": True,
            "kind": "inspect",
            "executed": True,
            "path": relative,
            "query": query,
            "anchored": True,
            "query_mode": mode,
            "match_count": len(matches),
            "match_lines": [index + 1 for index in matches],
            "chars": len(content),
            "file_chars": len(data),
            "content": content,
            "truncated": len(content) < len(data),
            "required_next_action": "use the anchored evidence to edit if sufficient; request a different anchor only when genuinely new evidence is still required",
        }

    def navigated_generate(self, *, role: str, prompt: dict[str, Any], **kwargs):
        if role == "coder" and isinstance(prompt, dict):
            prompt = dict(prompt)
            tools = dict(prompt.get("available_tools") or {})
            tools["inspect"] = (
                "read one repository-relative file; for a large/truncated file, set optional query to an identifier or phrase to receive bounded matching line windows from anywhere in that file; declaration-shaped anchors such as 'def name' or 'class Name' require that declaration to exist and do not fall back to generic keyword matches; do not repeat the same anchor"
            )
            tools["search"] = (
                str(tools.get("search") or "repository search")
                + "; put the search phrase in query (trusted normalization also accepts the narrow shorthand command=['search', '<query>'])"
            )
            prompt["available_tools"] = tools
        result, metrics = original_generate(role=role, prompt=prompt, **kwargs)
        if role == "coder":
            result = _canonicalize_tool_request(result)
        return result, metrics

    coder._execute_tool = MethodType(navigated_execute_tool, coder)
    coder._generate_role = MethodType(navigated_generate, coder)
    coder._stoe_inspection_navigation_installed = True
