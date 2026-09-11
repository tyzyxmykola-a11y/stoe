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

from anti_loop import _capture_candidate_evidence

_MUTATIONS = {"write", "delete", "move"}


def _request_kind(item: dict[str, Any]) -> str:
    return str((item.get("request") or {}).get("kind") or "")


def _successful_mutation(item: dict[str, Any]) -> bool:
    kind = _request_kind(item)
    feedback = item.get("feedback") or {}
    if kind == "write":
        return bool(feedback.get("candidate_changed"))
    return kind in {"delete", "move"} and bool(feedback.get("ok")) and feedback.get("executed", True) is not False


def _successful_run(item: dict[str, Any]) -> bool:
    if _request_kind(item) != "run":
        return False
    feedback = item.get("feedback") or {}
    return feedback.get("exit_code") == 0 and not feedback.get("timed_out") and not feedback.get("cancelled")


def _run_kind(item: dict[str, Any]) -> str | None:
    if _request_kind(item) != "run":
        return None
    feedback = item.get("feedback") or {}
    explicit = feedback.get("workflow_run_kind")
    if explicit in {"tests", "diff", "other"}:
        return explicit
    command = list((item.get("request") or {}).get("command") or [])
    if not command:
        return None
    lower = [str(arg).lower() for arg in command]
    executable = Path(lower[0]).name
    if executable in {"git", "git.exe"} and "diff" in lower[1:]:
        return "diff"
    joined = " ".join(lower)
    if "unittest" in joined or "pytest" in joined or any("test" in arg for arg in lower[1:]):
        return "tests"
    return "other"


def _mutation_path(item: dict[str, Any]) -> str | None:
    request = item.get("request") or {}
    feedback = item.get("feedback") or {}
    if _request_kind(item) == "move":
        return str(feedback.get("to") or request.get("destination") or request.get("path") or "") or None
    return str(feedback.get("path") or request.get("path") or "") or None


def workflow_state(history: list[dict[str, Any]]) -> dict[str, Any]:
    mutation_indices = [index for index, item in enumerate(history) if _successful_mutation(item)]
    if not mutation_indices:
        return {
            "stage": "pre_edit",
            "candidate_changed": False,
            "last_changed_path": None,
            "inspect_same_file_allowed": True,
            "tests_seen_after_last_change": False,
            "diff_seen_after_last_change": False,
            "last_run_failed": False,
            "required_next_actions": ["inspect only what is necessary, then make the smallest correct edit"],
            "required_next_command": None,
        }

    last_mutation = mutation_indices[-1]
    mutation = history[last_mutation]
    after = history[last_mutation + 1 :]
    successful_tests = any(_successful_run(item) and _run_kind(item) == "tests" for item in after)
    successful_diff = any(_successful_run(item) and _run_kind(item) == "diff" for item in after)
    last_run = next((item for item in reversed(after) if _request_kind(item) == "run"), None)
    last_run_failed = bool(last_run is not None and not _successful_run(last_run))
    changed_path = _mutation_path(mutation)

    if last_run_failed:
        stage = "run_failed"
        required = ["use the trusted failed-run output to diagnose and make only a necessary corrective change or rerun"]
        command = None
        inspect_allowed = True
    elif not successful_tests:
        stage = "candidate_changed"
        required = ["run relevant deterministic tests", "run git diff for the final candidate", "finish"]
        command = None
        inspect_allowed = False
    elif not successful_diff:
        stage = "tests_passed"
        required = ["run git diff for the final candidate", "finish"]
        command = ["git", "diff", "--", changed_path] if changed_path else ["git", "diff"]
        inspect_allowed = False
    else:
        stage = "ready_to_finish"
        required = ["finish"]
        command = None
        inspect_allowed = False

    return {
        "stage": stage,
        "candidate_changed": True,
        "last_changed_path": changed_path,
        "inspect_same_file_allowed": inspect_allowed,
        "tests_seen_after_last_change": successful_tests,
        "diff_seen_after_last_change": successful_diff,
        "last_run_failed": last_run_failed,
        "required_next_actions": required,
        "required_next_command": command,
    }


def compact_observation(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    state = workflow_state(history)
    recent = history[-6:]
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
            feedback.setdefault("chars", len(content))
        compacted.append({"request": request, "feedback": feedback})

    return [{"workflow_state": state}, *compacted]


def _state_from_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    for item in prompt.get("recent_tool_feedback") or []:
        if isinstance(item, dict) and isinstance(item.get("workflow_state"), dict):
            return dict(item["workflow_state"])
    return workflow_state([])


def _task_id_from_action(action_id: str) -> str | None:
    marker = ":coder:"
    if not isinstance(action_id, str) or marker not in action_id:
        return None
    task_id = action_id.split(marker, 1)[0]
    return task_id if task_id.startswith("TASK_") else None


def _runtime_state(coder: Any, task_id: str | None, fallback: dict[str, Any]) -> dict[str, Any]:
    states = getattr(coder, "_stoe_workflow_state", None)
    raw = states.get(task_id) if isinstance(states, dict) and task_id else None
    if not isinstance(raw, dict) or not raw.get("candidate_changed"):
        return fallback

    changed_path = str(raw.get("last_changed_path") or "") or fallback.get("last_changed_path")
    last_run_failed = bool(raw.get("last_run_failed"))
    tests_run = bool(raw.get("tests_run"))
    diff_inspected = bool(raw.get("diff_inspected"))

    if last_run_failed:
        stage = "run_failed"
        required = ["use the trusted failed-run output to diagnose and make only a necessary corrective change or rerun"]
        command = None
        inspect_allowed = True
    elif not tests_run:
        stage = "candidate_changed"
        required = ["run relevant deterministic tests", "run git diff for the final candidate", "finish"]
        command = None
        inspect_allowed = False
    elif not diff_inspected:
        stage = "tests_passed"
        required = ["run git diff for the final candidate", "finish"]
        command = ["git", "diff", "--", changed_path] if changed_path else ["git", "diff"]
        inspect_allowed = False
    else:
        stage = "ready_to_finish"
        required = ["finish"]
        command = None
        inspect_allowed = False

    return {
        "stage": stage,
        "candidate_changed": True,
        "last_changed_path": changed_path,
        "inspect_same_file_allowed": inspect_allowed,
        "tests_seen_after_last_change": tests_run,
        "diff_seen_after_last_change": diff_inspected,
        "last_run_failed": last_run_failed,
        "required_next_actions": required,
        "required_next_command": command,
    }


def _instruction(state: dict[str, Any]) -> str:
    stage = state.get("stage")
    path = state.get("last_changed_path")
    if stage == "pre_edit":
        return (
            "Choose exactly one next tool action. Inspect only what is necessary before editing and do not re-inspect the same file without new trusted evidence. "
            "Prefer targeted search over broad exploration. Then make the smallest real change. After a real mutation, run relevant tests, inspect the final Git diff with run, and finish. "
            "Use ordinary file mechanics; no patch serialization."
        )
    if stage == "run_failed":
        return (
            "A trusted run failed after the candidate changed. Use the supplied failure output to diagnose it. Inspect source again only when that failure creates genuinely new evidence that cannot be resolved from the output; otherwise make the smallest corrective mutation and rerun the failed check. "
            "Do not perform confirmation-only reads or no-op rewrites."
        )
    if stage == "candidate_changed":
        return (
            "The candidate bytes changed successfully. Do not re-inspect or rewrite the just-written file merely to confirm persistence. "
            "Choose run now and execute the relevant deterministic tests. A write counts as progress only when candidate bytes actually change."
        )
    if stage == "tests_passed":
        command = state.get("required_next_command") or (["git", "diff", "--", path] if path else ["git", "diff"])
        return (
            f"Relevant deterministic tests passed for the current candidate. Do not re-inspect source files. Choose run now with the exact final-diff command {command!r}. "
            "Use that Git diff output as the final change inspection."
        )
    return (
        "Relevant deterministic tests passed and the final Git diff was inspected for the current candidate. If the diff satisfies the objective, choose finish now. "
        "Only mutate again if the test or diff output exposed a concrete defect; otherwise do not inspect or rewrite files again."
    )


def install_workflow_controls(coder: Any) -> None:
    """Install compact observations and explicit post-edit workflow state."""

    if getattr(coder, "_stoe_workflow_controls_installed", False):
        return

    original_observation = coder._worker_observation
    original_generate = coder._generate_role

    def controlled_observation(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        original_observation(history)
        return compact_observation(history)

    def controlled_generate(self, *, action_id: str, role: str, prompt: dict[str, Any], **kwargs):
        if role == "coder" and isinstance(prompt, dict):
            prompt = dict(prompt)
            recent = [dict(item) if isinstance(item, dict) else item for item in (prompt.get("recent_tool_feedback") or [])]
            fallback = _state_from_prompt({"recent_tool_feedback": recent})
            task_id = _task_id_from_action(action_id)
            state = _runtime_state(self, task_id, fallback)
            if recent and isinstance(recent[0], dict) and "workflow_state" in recent[0]:
                recent[0] = {"workflow_state": state}
            prompt["recent_tool_feedback"] = recent
            prompt["workflow_state"] = state
            tools = dict(prompt.get("available_tools") or {})
            tools["run"] = (
                "execute argv list in candidate workspace; use this for deterministic tests and for final git diff, "
                "for example ['git','diff','--','StoeCoder/README.md']; do not use inspect as a substitute for diff"
            )
            prompt["available_tools"] = tools
            prompt["instruction"] = _instruction(state)
        try:
            return original_generate(action_id=action_id, role=role, prompt=prompt, **kwargs)
        except Exception:
            if role == "coder":
                task_id = _task_id_from_action(action_id)
                worktree_root = getattr(self, "worktree_root", None)
                if task_id and worktree_root is not None:
                    _capture_candidate_evidence(self, Path(worktree_root) / task_id)
            raise

    coder._worker_observation = MethodType(controlled_observation, coder)
    coder._generate_role = MethodType(controlled_generate, coder)
    coder._stoe_workflow_controls_installed = True
