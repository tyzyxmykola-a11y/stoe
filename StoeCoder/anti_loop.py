"""Trusted anti-loop guard for standalone StoeCoder tool actions.

This guard does not change model authority. It prevents repeated read-only
exploration and no-op rewrites from consuming the tool budget without progress,
returns explicit feedback to the next coder model call, and preserves candidate
stats before a guard-triggered failure removes the isolated worktree.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import MethodType
from typing import Any

_READ_ONLY = {"inspect", "search"}
_PROGRESS_ACTIONS = {"write", "delete", "move", "run", "finish"}
_MAX_CONSECUTIVE_EXPLORATION = 3
_MAX_REJECTED_REPEATS = 2


def _clip(value: Any, limit: int = 180) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _signature(request: dict[str, Any]) -> tuple[str, str, str]:
    kind = str(request.get("kind") or "")
    path = str(request.get("path") or ".")
    query = str(request.get("query") or "") if kind == "search" else ""
    return kind, path, query


def _describe(request: dict[str, Any]) -> str:
    kind = str(request.get("kind") or "action")
    path = _clip(request.get("path") or ".")
    if kind == "search":
        return f'search "{_clip(request.get("query"), 120)}" in {path}'
    return f"{kind} {path}"


def _candidate_path(worktree: Any, value: Any) -> tuple[Path, str] | None:
    try:
        if not isinstance(value, str) or not value or "\x00" in value:
            return None
        root = Path(worktree).resolve()
        target = (root / value).resolve()
        if target != root and root not in target.parents:
            return None
        if any(part.lower() in {".env", "credentials.json", "id_rsa", "id_ed25519"} for part in target.parts):
            return None
        return target, target.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def _capture_candidate_evidence(coder: Any, worktree: Any) -> None:
    """Best-effort diff stats before fail-closed guard termination."""

    evidence = getattr(coder, "_task_evidence", None)
    root = Path(worktree)
    if evidence is None or getattr(evidence, "files", None) or not root.exists():
        return
    try:
        subprocess.run(["git", "add", "-N", "."], cwd=root, stdin=subprocess.DEVNULL,
                       capture_output=True, check=False)
        names = subprocess.run(
            ["git", "diff", "--name-only", "-z"], cwd=root, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        ).stdout
        touched = [path for path in names.split("\x00") if path]
        additions = deletions = binary_files = 0
        numstat = subprocess.run(
            ["git", "diff", "--numstat", "-z"], cwd=root, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        ).stdout
        for record in numstat.split("\x00"):
            counts = record.split("\t", 2)
            if len(counts) != 3:
                continue
            if counts[0] == "-" or counts[1] == "-":
                binary_files += 1
            else:
                additions += int(counts[0])
                deletions += int(counts[1])
        evidence.files = touched
        evidence.additions = additions
        evidence.deletions = deletions
        evidence.binary_files = binary_files
    except (OSError, ValueError, subprocess.SubprocessError):
        # Evidence enrichment must never weaken or mask the original guard failure.
        return


def install_anti_loop(coder: Any) -> None:
    """Install one fail-closed exploration/no-op guard on a runtime instance."""

    if getattr(coder, "_stoe_anti_loop_installed", False):
        return

    original_execute_tool = coder._execute_tool
    task_state: dict[str, dict[str, Any]] = {}

    def guarded_execute_tool(self, task_id: str, step: int, worktree, request: dict[str, Any], allowed_paths):
        state = task_state.setdefault(task_id, {
            "last_read_signature": None,
            "consecutive_exploration": 0,
            "duplicate_rejections": 0,
            "exploration_rejections": 0,
        })
        kind = str(request.get("kind") or "")

        old_bytes: bytes | None = None
        write_target: Path | None = None
        write_relative: str | None = None
        if kind == "write":
            resolved = _candidate_path(worktree, request.get("path"))
            content = request.get("content", "")
            if resolved is not None and isinstance(content, str) and "\x00" not in content and len(content.encode("utf-8")) <= 240_000:
                write_target, write_relative = resolved
                if not allowed_paths or write_relative in allowed_paths:
                    proposed = content.encode("utf-8")
                    if write_target.is_file():
                        try:
                            old_bytes = write_target.read_bytes()
                        except OSError:
                            old_bytes = None
                    if old_bytes is not None and old_bytes == proposed:
                        digest = hashlib.sha256(old_bytes).hexdigest()
                        condition = f"no-op write rejected: {write_relative} already has identical content"
                        self._event(
                            "Guard", condition, level="warning", task_id=task_id, step=step,
                            kind="write", path=write_relative,
                            required_next_action="run relevant tests, inspect final git diff, or finish",
                        )
                        return {
                            "ok": False,
                            "executed": False,
                            "candidate_changed": False,
                            "error": condition,
                            "failure_condition": condition,
                            "path": write_relative,
                            "sha256": digest,
                            "old_sha256": digest,
                            "new_sha256": digest,
                            "bytes": len(old_bytes),
                            "required_next_action": "run relevant tests, inspect final git diff, or finish",
                        }

        if kind in _READ_ONLY:
            signature = _signature(request)
            detail = _describe(request)

            if signature == state["last_read_signature"]:
                state["duplicate_rejections"] += 1
                condition = f"duplicate read-only action rejected: {detail}"
                self._event(
                    "Guard",
                    condition,
                    level="warning",
                    task_id=task_id,
                    step=step,
                    kind=kind,
                    path=_clip(request.get("path") or "."),
                    query=_clip(request.get("query"), 120) if kind == "search" else None,
                    required_next_action="choose a different action; prefer write, run, or finish",
                )
                if state["duplicate_rejections"] >= _MAX_REJECTED_REPEATS:
                    _capture_candidate_evidence(self, worktree)
                    raise RuntimeError(
                        f"coder repeated identical read-only action after trusted rejection: {detail}"
                    )
                return {
                    "ok": False,
                    "error": condition,
                    "failure_condition": condition,
                    "required_next_action": "choose a different action; prefer write, run, or finish",
                    "executed": False,
                }

            if state["consecutive_exploration"] >= _MAX_CONSECUTIVE_EXPLORATION:
                state["exploration_rejections"] += 1
                condition = (
                    f"consecutive exploration limit reached ({_MAX_CONSECUTIVE_EXPLORATION}); "
                    f"read-only action rejected: {detail}"
                )
                self._event(
                    "Guard",
                    condition,
                    level="warning",
                    task_id=task_id,
                    step=step,
                    kind=kind,
                    required_next_action="write, run, or finish before more exploration",
                )
                if state["exploration_rejections"] >= _MAX_REJECTED_REPEATS:
                    _capture_candidate_evidence(self, worktree)
                    raise RuntimeError(
                        "coder exceeded consecutive exploration limit after trusted rejection"
                    )
                return {
                    "ok": False,
                    "error": condition,
                    "failure_condition": condition,
                    "required_next_action": "write, run, or finish before more exploration",
                    "executed": False,
                }

            try:
                feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)
            except Exception:
                _capture_candidate_evidence(self, worktree)
                raise
            state["last_read_signature"] = signature
            state["consecutive_exploration"] += 1
            state["duplicate_rejections"] = 0
            return feedback

        try:
            feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)
        except Exception:
            _capture_candidate_evidence(self, worktree)
            raise

        if kind == "write" and isinstance(feedback, dict) and feedback.get("ok") and write_target is not None and write_target.is_file():
            try:
                new_bytes = write_target.read_bytes()
            except OSError:
                new_bytes = b""
            feedback = dict(feedback)
            feedback.update({
                "executed": True,
                "candidate_changed": old_bytes != new_bytes,
                "old_sha256": hashlib.sha256(old_bytes).hexdigest() if old_bytes is not None else None,
                "new_sha256": hashlib.sha256(new_bytes).hexdigest(),
                "required_next_action": "run relevant deterministic tests, then inspect final git diff with run, then finish",
            })

        made_progress = kind in _PROGRESS_ACTIONS
        if kind == "write":
            made_progress = bool(isinstance(feedback, dict) and feedback.get("candidate_changed"))
        if made_progress:
            state.update({
                "last_read_signature": None,
                "consecutive_exploration": 0,
                "duplicate_rejections": 0,
                "exploration_rejections": 0,
            })
        return feedback

    coder._execute_tool = MethodType(guarded_execute_tool, coder)
    coder._stoe_anti_loop_installed = True
