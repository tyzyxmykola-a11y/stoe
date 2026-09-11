"""Trusted workflow-state controls for the standalone StoeCoder worker loop.

This adapter keeps the core executive authority unchanged while making the
model-visible workflow explicit: retain only the file content needed for the
next edit, surface the current stage, and direct post-edit work toward tests,
Git diff, and finish rather than repeated inspection.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import MethodType
from typing import Any

_MUTATIONS = {"write", "delete", "move"}


def _request_kind(item: dict[str, Any]) -> str:
    return str((item.get("request") or {}).get("kind") or "")


def _successful_mutation(item: dict[str, Any]) -> bool:
    kind = _request_kind(item)
    feedback = item.get("feedback") or {}
    if kind == "write":
        return bool(feedback.get("candidate_changed"))
    return kind in {"delete", "move"} and bool(feedback.get("ok"))


def _successful_run(item: dict[str, Any]) -> bool:
    if _request_kind(item) != "run":
        return False
    feedback = item.get("feedback") or {}
    return feedback.get("exit_code") == 0 and not feedback.get("timed_out") and not feedback.get("cancelled")


def _is_git_diff(item: dict[str, Any]) -> bool:
    if _request_kind(item) != "run":
        return False
    command = list((item.get("request") or {}).get("command") or [])
    if not command:
        return False
    executable = Path(str(command[0])).name.lower()
    return executable in {"git", "git.exe"} and any(str(arg).lower() == "diff" for arg in command[1:])


def workflow_state(history: list[dict[str, Any]]) -> dict[str, Any]:
    mutation_indices = [index for index, item in enumerate(history) if _successful_mutation(item)]
    if not mutation_indices:
        return {
            "stage": "pre_edit",
            "candidate_changed": False,
            "inspect_same_file_allowed": True,
            "required_next_actions": ["inspect only what is necessary, then make the smallest correct edit"],
        }

    last_mutation = mutation_indices[-1]
    after = history[last_mutation + 1 :]
    test_run_seen = any(_successful_run(item) and not _is_git_diff(item) for item in after)
    diff_seen = any(_successful_run(item) and _is_git_diff(item) for item in after)

    missing: list[str] = []
    if not test_run_seen:
        missing.append("run relevant deterministic tests")
    if not diff_seen:
        missing.append("run git diff for the final candidate")
    missing.append("finish")

    if test_run_seen and diff_seen:
        stage = "ready_to_finish"
    elif test_run_seen:
        stage = "verification_run"
    elif diff_seen:
        stage = "diff_inspected_needs_tests"
    else:
        stage = "candidate_changed"

    return {
        "stage": stage,
        "candidate_changed": True,
        "inspect_same_file_allowed": False,
        "tests_seen_after_last_change": test_run_seen,
        "diff_seen_after_last_change": diff_seen,
        "required_next_actions": missing,
    }


def compact_observation(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    state = workflow_state(history)
    recent = history[-5:]
    keep_inspect_content_index: int | None = None

    if not state["candidate_changed"]:
        for index in range(len(recent) - 1, -1, -1):
            item = recent[index]
            feedback = item.get("feedback") or {}
            if _request_kind(item) == "inspect" and isinstance(feedback.get("content"), str):
                keep_inspect_content_index = index
                break

    compacted: list[dict[str, Any]] = []
    for index, item in enumerate(recent):
        request = dict(item.get("request") or {})
        feedback = dict(item.get("feedback") or {})
        content = feedback.get("content")
        if _request_kind(item) == "inspect" and isinstance(content, str) and index != keep_inspect_content_index:
            feedback.pop("content", None)
            feedback["content_omitted"] = True
            feedback["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        compacted.append({"request": request, "feedback": feedback})

    return [{"workflow_state": state}, *compacted]


def _state_from_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    for item in prompt.get("recent_tool_feedback") or []:
        if isinstance(item, dict) and isinstance(item.get("workflow_state"), dict):
            return dict(item["workflow_state"])
    return {"stage": "pre_edit", "candidate_changed": False, "inspect_same_file_allowed": True,
            "required_next_actions": ["inspect only what is necessary, then make the smallest correct edit"]}


def install_workflow_controls(coder: Any) -> None:
    """Install compact observations and explicit post-edit workflow state."""

    if getattr(coder, "_stoe_workflow_controls_installed", False):
        return

    original_observation = coder._worker_observation
    original_generate = coder._generate_role

    def controlled_observation(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Preserve the core method as the source of the current observation window
        # contract, but derive compact model-visible state from the full history.
        original_observation(history)
        return compact_observation(history)

    def controlled_generate(self, *, action_id: str, role: str, prompt: dict[str, Any], **kwargs):
        if role == "coder" and isinstance(prompt, dict):
            prompt = dict(prompt)
            state = _state_from_prompt(prompt)
            prompt["workflow_state"] = state
            tools = dict(prompt.get("available_tools") or {})
            tools["run"] = (
                "execute argv list in candidate workspace; use this for tests and for final diff, "
                "for example ['git','diff','--','StoeCoder/README.md']"
            )
            prompt["available_tools"] = tools
            if state.get("candidate_changed"):
                required = "; then ".join(state.get("required_next_actions") or ["finish"])
                prompt["instruction"] = (
                    "Choose exactly one next tool action. The candidate already changed. "
                    "Do not re-inspect a file already read unless trusted feedback says it changed outside your edit or the previous read was unavailable. "
                    f"Required next sequence: {required}. "
                    "Use run with git diff for final diff inspection; do not use inspect as a substitute for diff."
                )
            else:
                prompt["instruction"] = (
                    "Choose exactly one next tool action. Inspect only what is necessary before editing, then make the smallest correct change. "
                    "After a real mutation, run relevant tests, inspect the final Git diff with run, and finish. "
                    "Use ordinary file mechanics; no patch serialization."
                )
        return original_generate(action_id=action_id, role=role, prompt=prompt, **kwargs)

    coder._worker_observation = MethodType(controlled_observation, coder)
    coder._generate_role = MethodType(controlled_generate, coder)
    coder._stoe_workflow_controls_installed = True
