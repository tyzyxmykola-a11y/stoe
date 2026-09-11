"""Trusted stage guard for standalone StoeCoder worker actions.

The model-visible prompt explains the intended workflow, but this module makes
that workflow enforceable. Verification commands come from the shared
repository-aware verification policy; models do not select their own test
frameworks. After verification, final diff inspection must precede finish.
"""

from __future__ import annotations

from types import MethodType
from typing import Any

from anti_loop import _capture_candidate_evidence, _run_command_kind
from verification_policy import worker_verification_commands

_MAX_REJECTED_REPEATS = 2
_MUTATIONS = {"write", "delete", "move"}
_READ_PROGRESS_KEYS = (
    "last_read_signature",
    "consecutive_exploration",
    "duplicate_rejections",
    "exploration_rejections",
)


def _stage(state: dict[str, Any]) -> str:
    if not state.get("candidate_changed"):
        return "pre_edit"
    if state.get("last_run_failed"):
        return "run_failed"
    if not state.get("tests_run"):
        return "candidate_changed"
    if not state.get("diff_inspected"):
        return "tests_passed"
    return "diff_inspected"


def _command_signature(command: Any) -> tuple[str, ...]:
    if not isinstance(command, list):
        return ()
    return tuple(str(item) for item in command)


def _run_success(feedback: Any) -> bool:
    return bool(
        isinstance(feedback, dict)
        and feedback.get("exit_code", 0) == 0
        and not feedback.get("timed_out")
        and not feedback.get("cancelled")
    )


def _touched_paths(coder: Any, state: dict[str, Any]) -> list[str]:
    evidence = getattr(coder, "_task_evidence", None)
    files = getattr(evidence, "files", None)
    if isinstance(files, list) and files:
        return [str(path) for path in files if str(path or "")]
    path = str(state.get("last_changed_path") or "")
    return [path] if path else []


def _ensure_verification_plan(coder: Any, state: dict[str, Any]) -> tuple[list[list[str]], int]:
    raw_commands = state.get("verification_commands")
    if isinstance(raw_commands, list) and all(isinstance(command, list) for command in raw_commands):
        commands = [[str(arg) for arg in command] for command in raw_commands]
    else:
        commands = worker_verification_commands(_touched_paths(coder, state))
        state["verification_commands"] = commands
    try:
        index = int(state.get("verification_index", 0))
    except (TypeError, ValueError):
        index = 0
    index = max(0, min(index, len(commands)))
    state["verification_index"] = index
    if not state.get("last_run_failed"):
        state["tests_run"] = index >= len(commands)
    return commands, index


def _required_action(stage: str, expected: list[str] | None = None) -> str:
    if stage == "candidate_changed":
        if expected is not None:
            return f"run exact verification command {expected!r}"
        return "run the next trusted verification command before final git diff"
    if stage == "tests_passed":
        return "run final git diff now"
    if stage == "diff_inspected":
        return "finish the candidate now"
    if stage == "run_failed":
        return "use the trusted failed-run output to diagnose; inspect only if it adds evidence, then make a corrective candidate change before rerunning verification"
    return "make a real candidate change, then run the trusted verification plan, inspect final git diff, and finish"


def install_workflow_guard(coder: Any) -> None:
    """Install fail-closed stage ordering around the trusted worker tool path."""

    if getattr(coder, "_stoe_workflow_guard_installed", False):
        return
    if not isinstance(getattr(coder, "_stoe_workflow_state", None), dict):
        raise RuntimeError("workflow guard requires anti-loop workflow state")

    original_execute_tool = coder._execute_tool
    guard_state: dict[str, dict[str, Any]] = {}

    def guarded_execute_tool(self, task_id: str, step: int, worktree, request: dict[str, Any], allowed_paths):
        runtime_states = self._stoe_workflow_state
        existing_state = runtime_states.get(task_id)
        runtime_state = existing_state if isinstance(existing_state, dict) else {}
        if runtime_state.get("candidate_changed"):
            _ensure_verification_plan(self, runtime_state)
        local = guard_state.setdefault(task_id, {
            "last_rejection_signature": None,
            "rejection_count": 0,
            "last_run_signature": None,
            "last_run_success": None,
            "last_run_transitioned": None,
        })
        kind = str(request.get("kind") or "")
        stage_before = _stage(runtime_state)

        def reject(condition: str, required_next_action: str, signature: tuple[Any, ...]):
            if signature == local.get("last_rejection_signature"):
                local["rejection_count"] = int(local.get("rejection_count") or 0) + 1
            else:
                local["last_rejection_signature"] = signature
                local["rejection_count"] = 1
            self._event(
                "Guard", condition, level="warning", task_id=task_id, step=step,
                kind=kind, workflow_stage=stage_before,
                required_next_action=required_next_action,
            )
            if local["rejection_count"] >= _MAX_REJECTED_REPEATS:
                _capture_candidate_evidence(self, worktree)
                raise RuntimeError("coder repeated stage-invalid action after trusted rejection: " + condition)
            return {
                "ok": False,
                "executed": False,
                "error": condition,
                "failure_condition": condition,
                "workflow_stage": stage_before,
                "required_next_action": required_next_action,
            }

        if kind == "finish" and stage_before != "diff_inspected":
            return reject(
                f"finish rejected before workflow gates: stage={stage_before}",
                _required_action(stage_before),
                ("finish", stage_before),
            )

        command = request.get("command") if kind == "run" else None
        run_signature = _command_signature(command)
        run_kind = _run_command_kind(command) if kind == "run" else None
        verification_index_before: int | None = None

        if kind == "run":
            if stage_before == "candidate_changed":
                commands, verification_index_before = _ensure_verification_plan(self, runtime_state)
                expected = commands[verification_index_before] if verification_index_before < len(commands) else None
                if expected is None:
                    runtime_state["tests_run"] = True
                    stage_before = _stage(runtime_state)
                elif list(command or []) != expected:
                    if run_kind == "diff":
                        condition = "premature git diff rejected: trusted verification plan is not complete"
                    else:
                        condition = f"stage-invalid run rejected before verification: expected exact command {expected!r}"
                    return reject(
                        condition,
                        _required_action("candidate_changed", expected),
                        ("run", "candidate_changed", run_signature),
                    )
            if stage_before == "tests_passed" and run_kind != "diff":
                return reject(
                    f"stage-invalid run rejected after verification passed: expected final git diff, got {run_kind or 'unclassified'}",
                    _required_action(stage_before),
                    ("run", stage_before, run_signature),
                )
            if stage_before == "diff_inspected":
                return reject(
                    "run rejected after final diff inspection: candidate is ready to finish",
                    _required_action(stage_before),
                    ("run", stage_before, run_signature),
                )
            if stage_before == "run_failed":
                return reject(
                    "run rejected after trusted verification failure: inspect only for new evidence or change the candidate before rerunning verification",
                    _required_action(stage_before),
                    ("run", stage_before, run_signature),
                )
            if (
                run_signature
                and run_signature == local.get("last_run_signature")
                and local.get("last_run_success") is True
                and local.get("last_run_transitioned") is False
            ):
                return reject(
                    "identical successful run rejected because the prior run did not advance workflow state",
                    _required_action(stage_before),
                    ("run", stage_before, run_signature),
                )

        read_progress_before = {key: runtime_state.get(key) for key in _READ_PROGRESS_KEYS}
        feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)

        # The anti-loop layer owns creation of the per-task runtime state. Do not
        # pre-seed an empty dict here: doing so bypasses anti-loop initialization.
        refreshed_state = runtime_states.get(task_id)
        runtime_state = refreshed_state if isinstance(refreshed_state, dict) else {}

        if kind in _MUTATIONS and isinstance(feedback, dict) and feedback.get("executed", True) is not False:
            changed = bool(feedback.get("candidate_changed")) if kind == "write" else feedback.get("ok") is not False
            if changed:
                commands = worker_verification_commands(_touched_paths(self, runtime_state))
                runtime_state["verification_commands"] = commands
                runtime_state["verification_index"] = 0
                runtime_state["tests_run"] = not commands
                runtime_state["diff_inspected"] = False
                runtime_state["last_run_failed"] = False
                local.update({
                    "last_rejection_signature": None,
                    "rejection_count": 0,
                    "last_run_signature": None,
                    "last_run_success": None,
                    "last_run_transitioned": None,
                })
                feedback = dict(feedback)
                feedback["verification_commands"] = commands
                feedback["verification_index"] = 0

        stage_after = _stage(runtime_state)

        if kind == "run" and isinstance(feedback, dict):
            success = _run_success(feedback)
            verification_advanced = False
            if stage_before == "candidate_changed" and verification_index_before is not None:
                commands, current_index = _ensure_verification_plan(self, runtime_state)
                if success and current_index == verification_index_before:
                    next_index = min(current_index + 1, len(commands))
                    runtime_state["verification_index"] = next_index
                    runtime_state["tests_run"] = next_index >= len(commands)
                    runtime_state["diff_inspected"] = False
                    runtime_state["last_run_failed"] = False
                    verification_advanced = next_index != current_index
                elif not success:
                    runtime_state["verification_index"] = verification_index_before
                    runtime_state["tests_run"] = False
                    runtime_state["last_run_failed"] = True
            stage_after = _stage(runtime_state)
            transitioned = stage_after != stage_before or verification_advanced
            local.update({
                "last_run_signature": run_signature,
                "last_run_success": success,
                "last_run_transitioned": transitioned,
                "last_rejection_signature": None,
                "rejection_count": 0,
            })
            feedback = dict(feedback)
            feedback.update({
                "stage_guard_before": stage_before,
                "stage_guard_after": stage_after,
                "workflow_transitioned": transitioned,
                "verification_index": runtime_state.get("verification_index", 0),
                "verification_total": len(runtime_state.get("verification_commands") or []),
            })
            if success and not transitioned and runtime_state:
                for key, value in read_progress_before.items():
                    runtime_state[key] = value

        return feedback

    coder._execute_tool = MethodType(guarded_execute_tool, coder)
    coder._stoe_workflow_guard_installed = True
