"""Trusted anti-loop guard for standalone StoeCoder tool actions.

This guard does not change model authority. It prevents repeated read-only
exploration from consuming the entire tool budget without progress and returns
explicit feedback to the next coder model call.
"""

from __future__ import annotations

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


def install_anti_loop(coder: Any) -> None:
    """Install one fail-closed read-only exploration guard on a runtime instance."""

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

            feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)
            state["last_read_signature"] = signature
            state["consecutive_exploration"] += 1
            state["duplicate_rejections"] = 0
            return feedback

        feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)
        if kind in _PROGRESS_ACTIONS:
            state.update({
                "last_read_signature": None,
                "consecutive_exploration": 0,
                "duplicate_rejections": 0,
                "exploration_rejections": 0,
            })
        return feedback

    coder._execute_tool = MethodType(guarded_execute_tool, coder)
    coder._stoe_anti_loop_installed = True
