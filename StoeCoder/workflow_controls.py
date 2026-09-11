"""Trusted workflow-state controls for the standalone StoeCoder worker loop.

This adapter keeps the core executive authority unchanged while making the
model-visible workflow explicit. Verification commands are derived from the
same repository-aware policy used by the trusted final verifier, so the model
executes a plan instead of choosing a test framework.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import MethodType
from typing import Any

from anti_loop import _capture_candidate_evidence
from verification_policy import worker_verification_commands

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
    return (
        feedback.get("executed", True) is not False
        and feedback.get("exit_code") == 0
        and not feedback.get("timed_out")
        and not feedback.get("cancelled")
    )


def _failed_executed_run(item: dict[str, Any]) -> bool:
    if _request_kind(item) != "run":
        return False
    feedback = item.get("feedback") or {}
    return feedback.get("executed", True) is not False and not _successful_run(item)


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


def _command(item: dict[str, Any]) -> list[str]:
    return [str(arg) for arg in ((item.get("request") or {}).get("command") or [])]


def _verification_progress(after: list[dict[str, Any]], commands: list[list[str]]) -> int:
    index = 0
    for item in after:
        if index >= len(commands):
            break
        if _successful_run(item) and _command(item) == commands[index]:
            index += 1
    return index


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
            "verification_commands": [],
            "verification_index": 0,
            "verification_total": 0,
            "required_next_actions": ["inspect only what is necessary, then make the smallest correct edit"],
            "required_next_command": None,
        }

    last_mutation = mutation_indices[-1]
    mutation = history[last_mutation]
    after = history[last_mutation + 1 :]
    changed_path = _mutation_path(mutation)
    commands = worker_verification_commands([changed_path] if changed_path else [])
    verification_index = _verification_progress(after, commands)
    verification_complete = verification_index >= len(commands)
    successful_diff = any(_successful_run(item) and _run_kind(item) == "diff" for item in after)
    last_run = next((item for item in reversed(after) if _request_kind(item) == "run"), None)
    last_run_failed = bool(last_run is not None and _failed_executed_run(last_run))

    if last_run_failed:
        stage = "run_failed"
        required = ["use the trusted failed-run output to diagnose and make only a necessary corrective change before rerunning verification"]
        command = None
        inspect_allowed = True
    elif not verification_complete:
        stage = "candidate_changed"
        required = ["run the next trusted verification command", "run git diff for the final candidate", "finish"]
        command = commands[verification_index]
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
        "tests_seen_after_last_change": verification_complete,
        "diff_seen_after_last_change": successful_diff,
        "last_run_failed": last_run_failed,
        "verification_commands": commands,
        "verification_index": verification_index,
        "verification_total": len(commands),
        "required_next_actions": required,
        "required_next_command": command,
    }


def compact_observation(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    state = workflow_state(history)
    recent = history[-6:]
    keep_inspect_content_index: int | None = None

    if not state["candidate_changed"] or state["inspect_same_file_allowed"]:
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


def _runtime_touched_paths(coder: Any, raw: dict[str, Any], fallback: dict[str, Any]) -> list[str]:
    evidence = getattr(coder, "_task_evidence", None)
    files = getattr(evidence, "files", None)
    if isinstance(files, list) and files:
        return [str(path) for path in files if str(path or "")]
    changed_path = str(raw.get("last_changed_path") or fallback.get("last_changed_path") or "")
    return [changed_path] if changed_path else []


def _runtime_state(coder: Any, task_id: str | None, fallback: dict[str, Any]) -> dict[str, Any]:
    states = getattr(coder, "_stoe_workflow_state", None)
    raw = states.get(task_id) if isinstance(states, dict) and task_id else None
    if not isinstance(raw, dict) or not raw.get("candidate_changed"):
        return fallback

    changed_path = str(raw.get("last_changed_path") or "") or fallback.get("last_changed_path")
    last_run_failed = bool(raw.get("last_run_failed"))
    diff_inspected = bool(raw.get("diff_inspected"))
    raw_commands = raw.get("verification_commands")
    if isinstance(raw_commands, list) and all(isinstance(command, list) for command in raw_commands):
        commands = [[str(arg) for arg in command] for command in raw_commands]
    else:
        commands = worker_verification_commands(_runtime_touched_paths(coder, raw, fallback))
    try:
        verification_index = int(raw.get("verification_index", 0))
    except (TypeError, ValueError):
        verification_index = 0
    verification_index = max(0, min(verification_index, len(commands)))
    tests_run = bool(raw.get("tests_run")) or verification_index >= len(commands)

    if last_run_failed:
        stage = "run_failed"
        required = ["use the trusted failed-run output to diagnose and make only a necessary corrective change before rerunning verification"]
        command = None
        inspect_allowed = True
    elif not tests_run:
        stage = "candidate_changed"
        required = ["run the next trusted verification command", "run git diff for the final candidate", "finish"]
        command = commands[verification_index] if verification_index < len(commands) else None
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
        "verification_commands": commands,
        "verification_index": verification_index,
        "verification_total": len(commands),
        "required_next_actions": required,
        "required_next_command": command,
    }


def _instruction(state: dict[str, Any]) -> str:
    stage = state.get("stage")
    path = state.get("last_changed_path")
    if stage == "pre_edit":
        return (
            "Choose exactly one next tool action. Inspect only what is necessary before editing and do not re-inspect the same file without new trusted evidence. "
            "Prefer targeted search over broad exploration. Then make the smallest real change. After a real mutation, follow the supplied verification plan, inspect the final Git diff with run, and finish. "
            "Use ordinary file mechanics; no patch serialization."
        )
    if stage == "run_failed":
        return (
            "A trusted verification command failed after the candidate changed. Use the supplied failure output to diagnose it. Inspect source again only when that failure creates genuinely new evidence that cannot be resolved from the output; otherwise make the smallest corrective mutation. "
            "Do not improvise a different test framework or rerun commands before a corrective change. If you inspect source because of the failure, use the supplied full inspect content when editing; never replace a whole file with only an excerpt."
        )
    if stage == "candidate_changed":
        command = state.get("required_next_command")
        return (
            "The candidate bytes changed successfully. Do not re-inspect or rewrite the just-written file merely to confirm persistence. "
            f"Choose run now with exactly the trusted next verification command {command!r}. The repository verification policy, not the model, selects this command."
        )
    if stage == "tests_passed":
        command = state.get("required_next_command") or (["git", "diff", "--", path] if path else ["git", "diff"])
        return (
            f"The trusted worker verification plan completed for the current candidate. Do not re-inspect source files. Choose run now with the exact final-diff command {command!r}. "
            "Use that Git diff output as the final change inspection."
        )
    return (
        "The trusted worker verification plan completed and the final Git diff was inspected for the current candidate. If the diff satisfies the objective, choose finish now. "
        "Only mutate again if the verification or diff output exposed a concrete defect; otherwise do not inspect or rewrite files again."
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
                "execute argv list in candidate workspace; when workflow_state.required_next_command is non-null, use that argv exactly; "
                "verification commands are selected by the trusted repository policy; do not substitute another test framework and do not use inspect as a substitute for diff"
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
