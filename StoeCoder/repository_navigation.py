"""Trusted compact repository navigation for standalone StoeCoder.

The model should not have to trawl raw repository-wide ripgrep output. This
adapter turns search into a bounded repository map and then tracks whether a
read-only action actually exposed new evidence. The existing anti-loop guard
remains the boundedness authority; information gain only corrects its
consecutive-exploration counter after useful observations.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from types import MethodType
from typing import Any

_MAX_MATCHED_FILES = 12
_MAX_EXCERPT_FILES = 8
_MAX_EXCERPTS = 16
_MAX_EXCERPT_CHARS = 240
_MAX_SUMMARY_CHARS = 4_000

_SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".kt", ".kts", ".c", ".cc", ".cpp", ".h",
    ".hpp", ".cs", ".rb", ".php", ".sh", ".ps1", ".html", ".css",
    ".scss", ".sql",
}
_CONFIG_EXTENSIONS = {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg"}
_DOC_EXTENSIONS = {".md", ".rst", ".txt", ".pdf", ".doc", ".docx"}
_LOW_VALUE_PARTS = {
    "runtime", "artifacts", "results", "result", "data", "datasets", "archive",
    "archives", "papers", "paper", "publications", "node_modules", ".venv",
    "__pycache__",
}


def _safe_base(worktree: Any, value: Any) -> tuple[Path, str]:
    root = Path(worktree).resolve()
    raw = str(value or ".")
    if "\x00" in raw:
        raise ValueError("search path is invalid")
    target = (root / raw).resolve()
    if target != root and root not in target.parents:
        raise ValueError("search path escapes candidate workspace")
    relative = target.relative_to(root).as_posix()
    if relative == ".git" or relative.startswith(".git/"):
        raise ValueError("worker cannot inspect Git internals")
    if any(part.lower() in {".env", "credentials.json", "id_rsa", "id_ed25519"} for part in target.parts):
        raise ValueError("credential-bearing path is unavailable to workers")
    return target, relative


def _normalize_output_path(worktree: Any, raw: str) -> str | None:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return None
    root = str(Path(worktree).resolve()).replace("\\", "/").rstrip("/")
    if text.lower().startswith(root.lower() + "/"):
        text = text[len(root) + 1 :]
    while text.startswith("./"):
        text = text[2:]
    if not text or text == ".git" or text.startswith(".git/") or text.startswith("../"):
        return None
    return text


def _rank_path(path: str) -> tuple[int, int, str]:
    candidate = Path(path)
    suffix = candidate.suffix.lower()
    parts = {part.lower() for part in candidate.parts}
    score = 30
    if suffix in _SOURCE_EXTENSIONS:
        score = 0
    elif suffix in _CONFIG_EXTENSIONS:
        score = 10
    elif suffix in _DOC_EXTENSIONS:
        score = 50
    if parts & _LOW_VALUE_PARTS:
        score += 30
    if "tests" in parts or "test" in parts:
        score += 3
    return score, len(candidate.parts), path.lower()


def _artifact_text(result: Any) -> str:
    path = str(getattr(result, "stdout_artifact", "") or "")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return str(getattr(result, "stdout", "") or "")


def _result_failure(result: Any) -> dict[str, Any] | None:
    exit_code = int(getattr(result, "exit_code", -1))
    timed_out = bool(getattr(result, "timed_out", False))
    cancelled = bool(getattr(result, "cancelled", False))
    if exit_code in {0, 1} and not timed_out and not cancelled:
        return None
    return {
        "ok": False,
        "kind": "search",
        "executed": True,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "cancelled": cancelled,
        "stderr": str(getattr(result, "stderr", "") or "")[:1_000],
        "error": "trusted repository search failed",
    }


def _parse_excerpt_line(worktree: Any, line: str) -> dict[str, Any] | None:
    match = re.match(r"^(.*?):(\d+):(.*)$", line)
    if not match:
        return None
    path = _normalize_output_path(worktree, match.group(1))
    if path is None:
        return None
    text = match.group(3).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > _MAX_EXCERPT_CHARS:
        text = text[: _MAX_EXCERPT_CHARS - 1] + "…"
    return {"path": path, "line": int(match.group(2)), "text": text}


def _summary(matched_files: list[str], matches: list[dict[str, Any]], omitted: int) -> str:
    lines = [f"matched files: {len(matched_files) + omitted}"]
    for path in matched_files:
        lines.append(f"- {path}")
    if omitted:
        lines.append(f"- … {omitted} additional matched files omitted")
    if matches:
        lines.append("excerpts:")
        for item in matches:
            lines.append(f"{item['path']}:{item['line']}: {item['text']}")
    text = "\n".join(lines)
    if len(text) > _MAX_SUMMARY_CHARS:
        return text[: _MAX_SUMMARY_CHARS - 1] + "…"
    return text


def _evidence_keys(request: dict[str, Any], feedback: dict[str, Any]) -> set[str]:
    kind = str(request.get("kind") or "")
    if feedback.get("ok") is False:
        return set()
    if kind == "inspect":
        content = feedback.get("content")
        if not isinstance(content, str) or not content:
            return set()
        path = str(feedback.get("path") or request.get("path") or "")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return {f"inspect:{path}:{digest}"}
    if kind == "search":
        files = feedback.get("matched_files")
        if not isinstance(files, list):
            return set()
        return {f"search-file:{str(path)}" for path in files if str(path)}
    return set()


def install_repository_navigation(coder: Any) -> None:
    """Replace raw worker search output with a compact ranked repository map."""

    if getattr(coder, "_stoe_repository_navigation_installed", False):
        return

    original_execute_tool = coder._execute_tool
    original_generate = coder._generate_role

    def navigated_execute_tool(self, task_id: str, step: int, worktree, request: dict[str, Any], allowed_paths):
        if str(request.get("kind") or "") != "search":
            return original_execute_tool(task_id, step, worktree, request, allowed_paths)

        query = str(request.get("query") or "")
        if not query or "\x00" in query or len(query) > 2_000:
            return {"ok": False, "kind": "search", "executed": False, "error": "search query is empty or invalid"}

        base, base_relative = _safe_base(worktree, request.get("path") or ".")
        if not base.exists():
            return {
                "ok": False,
                "kind": "search",
                "executed": True,
                "query": query,
                "base": base_relative,
                "matched_files": [],
                "matches": [],
                "error": "search base not found",
            }

        root = Path(worktree).resolve()
        rg_base = "." if base_relative == "." else base_relative
        files_result = self._runner.run(
            action_id=f"{task_id}:tool:{step}:search-files",
            command=[
                "rg", "-l", "--hidden",
                "--glob", "!.git/**",
                "--glob", "!.venv/**",
                "--glob", "!node_modules/**",
                "--glob", "!agent/runtime/**",
                "--", query, rg_base,
            ],
            cwd=root,
            timeout=60,
        )
        failure = _result_failure(files_result)
        if failure is not None:
            failure.update({"query": query, "base": base_relative, "matched_files": [], "matches": []})
            return failure

        all_files: list[str] = []
        seen: set[str] = set()
        for line in _artifact_text(files_result).splitlines():
            path = _normalize_output_path(root, line)
            if path is not None and path not in seen:
                seen.add(path)
                all_files.append(path)
        all_files.sort(key=_rank_path)
        selected_files = all_files[:_MAX_MATCHED_FILES]
        excerpt_files = selected_files[:_MAX_EXCERPT_FILES]
        matches: list[dict[str, Any]] = []
        excerpt_result = None

        if excerpt_files:
            excerpt_result = self._runner.run(
                action_id=f"{task_id}:tool:{step}:search-excerpts",
                command=["rg", "-n", "-m", "2", "--", query, *excerpt_files],
                cwd=root,
                timeout=60,
            )
            excerpt_failure = _result_failure(excerpt_result)
            if excerpt_failure is None:
                for line in _artifact_text(excerpt_result).splitlines():
                    parsed = _parse_excerpt_line(root, line)
                    if parsed is not None:
                        matches.append(parsed)
                        if len(matches) >= _MAX_EXCERPTS:
                            break

        omitted = max(0, len(all_files) - len(selected_files))
        durations = float(getattr(files_result, "duration_seconds", 0.0) or 0.0)
        if excerpt_result is not None:
            durations += float(getattr(excerpt_result, "duration_seconds", 0.0) or 0.0)
        summary = _summary(selected_files, matches, omitted)
        return {
            "ok": True,
            "kind": "search",
            "executed": True,
            "query": query,
            "base": base_relative,
            "exit_code": 0 if all_files else 1,
            "duration_seconds": round(durations, 3),
            "matched_file_count": len(all_files),
            "matched_files": selected_files,
            "omitted_file_count": omitted,
            "matches": matches,
            "stdout": summary,
            "stderr": "",
            "timed_out": False,
            "cancelled": False,
            "truncated": bool(omitted or len(matches) >= _MAX_EXCERPTS),
            "search_artifacts": [
                value for value in (
                    str(getattr(files_result, "stdout_artifact", "") or ""),
                    str(getattr(excerpt_result, "stdout_artifact", "") or "") if excerpt_result is not None else "",
                ) if value
            ],
        }

    def navigated_generate(self, *, role: str, prompt: dict[str, Any], **kwargs):
        if role == "coder" and isinstance(prompt, dict):
            prompt = dict(prompt)
            tools = dict(prompt.get("available_tools") or {})
            tools["search"] = (
                "trusted compact repository search under an optional relative path; returns ranked matched_files and bounded excerpts rather than raw repository-wide output"
            )
            prompt["available_tools"] = tools
        return original_generate(role=role, prompt=prompt, **kwargs)

    coder._execute_tool = MethodType(navigated_execute_tool, coder)
    coder._generate_role = MethodType(navigated_generate, coder)
    coder._stoe_repository_navigation_installed = True


def install_information_gain_tracking(coder: Any) -> None:
    """Make anti-loop exploration accounting depend on new evidence, not reads."""

    if getattr(coder, "_stoe_information_gain_installed", False):
        return
    if not isinstance(getattr(coder, "_stoe_workflow_state", None), dict):
        raise RuntimeError("information-gain tracking requires anti-loop workflow state")

    original_execute_tool = coder._execute_tool
    seen_by_task: dict[str, set[str]] = {}

    def gain_aware_execute_tool(self, task_id: str, step: int, worktree, request: dict[str, Any], allowed_paths):
        feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)
        kind = str(request.get("kind") or "")
        if kind not in {"inspect", "search"} or not isinstance(feedback, dict):
            return feedback
        if feedback.get("executed", True) is False:
            return feedback

        states = self._stoe_workflow_state
        state = states.get(task_id)
        if not isinstance(state, dict):
            return feedback

        seen = seen_by_task.setdefault(task_id, set())
        evidence = _evidence_keys(request, feedback)
        novel = evidence - seen
        enriched = dict(feedback)
        if novel:
            seen.update(novel)
            state["consecutive_exploration"] = 0
            state["exploration_rejections"] = 0
            state["useful_exploration_count"] = int(state.get("useful_exploration_count") or 0) + 1
            enriched["information_gain"] = True
            enriched["novel_evidence_count"] = len(novel)
            enriched["stagnant_exploration_count"] = 0
        else:
            state.setdefault("useful_exploration_count", 0)
            enriched["information_gain"] = False
            enriched["novel_evidence_count"] = 0
            enriched["stagnant_exploration_count"] = int(state.get("consecutive_exploration") or 0)
        enriched["useful_exploration_count"] = int(state.get("useful_exploration_count") or 0)
        return enriched

    coder._execute_tool = MethodType(gain_aware_execute_tool, coder)
    coder._stoe_information_gain_installed = True
