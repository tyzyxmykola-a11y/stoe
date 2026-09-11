"""Trusted stage guard for standalone StoeCoder worker actions.

The model-visible prompt explains the intended workflow, but this module makes
that workflow enforceable. After a real candidate mutation, tests must precede
final diff inspection; after diff inspection, the worker must finish. Repeated
run commands that do not advance workflow state do not reset anti-loop progress.
"""

from __future__ import annotations

from types import MethodType
from typing import Any

from anti_loop import _capture_candidate_evidence, _run_command_kind

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


def required_test_command(path: Any) -> list[str] | None:
    """Return the trusted deterministic test command for a known project path."""

    normalized = str(path or "").replace("\\", "/")
    if normalized == "StoeCoder" or normalized.startswith("StoeCoder/"):
        return ["python", "-m", "unittest", "discover", "-s", "StoeCoder/tests", "-q"]
    return None


def _run_success(feedback: Any) -> bool:
    return bool(
        isinstance(feedback, dict)
        and feedback.get("exit_code", 0) == 0
        and not feedback.get("timed_out")
        and not feedback.get("cancelled")
    )


def _required_action(stage: str) -> str:
    if stage == "candidate_changed":
        return "run relevant deterministic tests before final git diff"
    if stage == "tests_passed":
        return "run final git diff now"
    if stage == "diff_inspected":
        return "finish the candidate now"
    if stage == "run_failed":
        return "use the trusted failed-run output to diagnose; change the candidate if needed before retrying the same command"
    return "make a real candidate change, then run tests, inspect final git diff, and finish"


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
            required = _required_action(stage_before)
            return reject(
                f"finish rejected before workflow gates: stage={stage_before}",
                required,
                ("finish", stage_before),
            )

        command = request.get("command") if kind == "run" else None
        run_signature = _command_signature(command)
        run_kind = _run_command_kind(command) if kind == "run" else None

        if kind == "run":
            expected_tests = required_test_command(runtime_state.get("last_changed_path")) if stage_before == "candidate_changed" else None
            if stage_before == "candidate_changed" and run_kind == "diff":
                required = (
                    f"run exact deterministic tests command {expected_tests!r} before final git diff"
                    if expected_tests else _required_action(stage_before)
                )
                return reject(
                    "premature git diff rejected: deterministic tests have not passed for the current candidate",
                    required,
                    ("run", stage_before, run_signature),
                )
            if stage_before == "candidate_changed" and expected_tests is not None and list(command or []) != expected_tests:
                required = f"run exact deterministic tests command {expected_tests!r}"
                return reject(
                    f"stage-invalid run rejected before tests: expected exact deterministic test command {expected_tests!r}",
                    required,
                    ("run", stage_before, run_signature),
                )
            if stage_before == "tests_passed" and run_kind != "diff":
                required = _required_action(stage_before)
                return reject(
                    f"stage-invalid run rejected after tests passed: expected final git diff, got {run_kind or 'unclassified'}",
                    required,
                    ("run", stage_before, run_signature),
                )
            if stage_before == "diff_inspected":
                required = _required_action(stage_before)
                return reject(
                    "run rejected after final diff inspection: candidate is ready to finish",
                    required,
                    ("run", stage_before, run_signature),
                )
            if (
                stage_before == "run_failed"
                and run_signature
                and run_signature == local.get("last_run_signature")
                and local.get("last_run_success") is False
            ):
                required = _required_action(stage_before)
                return reject(
                    "identical failed run rejected without intervening candidate change",
                    required,
                    ("run", stage_before, run_signature),
                )
            if (
                run_signature
                and run_signature == local.get("last_run_signature")
                and local.get("last_run_success") is True
                and local.get("last_run_transitioned") is False
            ):
                required = _required_action(stage_before)
                return reject(
                    "identical successful run rejected because the prior run did not advance workflow state",
                    required,
                    ("run", stage_before, run_signature),
                )

        read_progress_before = {key: runtime_state.get(key) for key in _READ_PROGRESS_KEYS}
        feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)

        # The anti-loop layer owns creation of the per-task runtime state. Do not
        # pre-seed an empty dict here: doing so bypasses anti-loop initialization
        # and causes fresh-task reads to fail on missing state keys.
        refreshed_state = runtime_states.get(task_id)
        runtime_state = refreshed_state if isinstance(refreshed_state, dict) else {}
        stage_after = _stage(runtime_state)

        if kind == "run" and isinstance(feedback, dict):
            success = _run_success(feedback)
            transitioned = stage_after != stage_before
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
            })
            if success and not transitioned and runtime_state:
                for key, value in read_progress_before.items():
                    runtime_state[key] = value

        if kind in _MUTATIONS and isinstance(feedback, dict) and feedback.get("executed", True) is not False:
            changed = bool(feedback.get("candidate_changed")) if kind == "write" else feedback.get("ok") is not False
            if changed:
                local.update({
                    "last_rejection_signature": None,
                    "rejection_count": 0,
                    "last_run_signature": None,
                    "last_run_success": None,
                    "last_run_transitioned": None,
                })

        return feedback

    coder._execute_tool = MethodType(guarded_execute_tool, coder)
    coder._stoe_workflow_guard_installed = True
