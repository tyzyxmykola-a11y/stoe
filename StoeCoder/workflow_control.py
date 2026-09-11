"""Stage-aware prompt and history control for standalone StoeCoder.

This layer keeps the trusted tool authority unchanged. It compresses stale file
observations and makes the next governed action explicit after a real candidate
mutation so local workers do not fall back into inspect/rewrite loops.
"""

from __future__ import annotations

import copy
import hashlib
from types import MethodType
from typing import Any

_MUTATIONS = {"write", "delete", "move"}


def _task_id(action_id: str) -> str:
    text = str(action_id or "")
    return text.split(":coder:", 1)[0] if ":coder:" in text else text


def _compact_observation(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one necessary pre-edit file body; summarize older/stale bodies."""

    compact = copy.deepcopy(records)
    last_mutation = -1
    latest_inspect_after_mutation = -1

    for index, record in enumerate(compact):
        request = record.get("request") if isinstance(record, dict) else None
        feedback = record.get("feedback") if isinstance(record, dict) else None
        if not isinstance(request, dict) or not isinstance(feedback, dict):
            continue
        kind = str(request.get("kind") or "")
        executed = feedback.get("executed", True) is not False
        if kind in _MUTATIONS and feedback.get("ok") is not False and executed:
            last_mutation = index

    for index, record in enumerate(compact):
        request = record.get("request") if isinstance(record, dict) else None
        feedback = record.get("feedback") if isinstance(record, dict) else None
        if not isinstance(request, dict) or not isinstance(feedback, dict):
            continue
        if (
            str(request.get("kind") or "") == "inspect"
            and index > last_mutation
            and feedback.get("ok") is True
            and isinstance(feedback.get("content"), str)
        ):
            latest_inspect_after_mutation = index

    for index, record in enumerate(compact):
        feedback = record.get("feedback") if isinstance(record, dict) else None
        if not isinstance(feedback, dict) or not isinstance(feedback.get("content"), str):
            continue
        if index == latest_inspect_after_mutation:
            continue
        content = feedback.pop("content")
        feedback["content_omitted"] = True
        feedback["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        feedback.setdefault("chars", len(content))

    return compact


def _workflow_instruction(state: dict[str, Any]) -> tuple[str, str | None]:
    changed = bool(state.get("candidate_changed"))
    tests_run = bool(state.get("tests_run"))
    diff_inspected = bool(state.get("diff_inspected"))
    run_failed = bool(state.get("last_run_failed"))
    path = str(state.get("last_changed_path") or "")

    if not changed:
        return (
            "Choose exactly one next tool action. Inspect only what is necessary before the first edit and do not re-inspect the same file without new trusted evidence. Prefer targeted search over broad exploration. Once enough evidence exists, make the smallest real mutation. Use ordinary file mechanics; no patch serialization.",
            None,
        )
    if run_failed:
        return (
            "A trusted run failed after the candidate changed. Use the supplied failure output to diagnose it. Inspect source again only when that failure creates genuinely new evidence that cannot be resolved from the output; otherwise make the smallest corrective mutation and rerun the failed check. Do not perform confirmation-only reads or no-op rewrites.",
            None,
        )
    if not tests_run:
        return (
            "The candidate bytes have changed successfully. Do not re-inspect or rewrite the just-written file merely to confirm persistence. The next action should be run: execute the relevant deterministic tests. A write counts as progress only when candidate bytes actually change.",
            None,
        )
    if not diff_inspected:
        command = f"git diff -- {path}" if path else "git diff"
        return (
            f"Relevant tests have passed for the current candidate. Do not re-inspect source files. The next action should be run the final Git diff using `{command}`. Use the diff output as the final change inspection.",
            command,
        )
    return (
        "Relevant tests passed and the final Git diff was inspected for the current candidate. If the diff satisfies the objective, finish now. Only make another mutation if the test or diff output exposed a concrete defect; otherwise do not inspect or rewrite files again.",
        None,
    )


def install_workflow_control(coder: Any) -> None:
    """Install compact observations and explicit post-mutation workflow stages."""

    if getattr(coder, "_stoe_workflow_control_installed", False):
        return

    original_worker_observation = coder._worker_observation
    original_generate_role = coder._generate_role

    def controlled_worker_observation(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _compact_observation(original_worker_observation(history))

    def controlled_generate_role(self, *, role: str, **kwargs):
        if role != "coder":
            return original_generate_role(role=role, **kwargs)

        prompt = copy.deepcopy(kwargs.get("prompt") or {})
        task_id = _task_id(str(kwargs.get("action_id") or ""))
        states = getattr(self, "_stoe_workflow_state", {})
        state = dict(states.get(task_id) or {}) if isinstance(states, dict) else {}
        instruction, required_command = _workflow_instruction(state)

        prompt["instruction"] = instruction
        prompt["workflow_state"] = {
            "candidate_changed": bool(state.get("candidate_changed")),
            "last_changed_path": state.get("last_changed_path"),
            "tests_run": bool(state.get("tests_run")),
            "diff_inspected": bool(state.get("diff_inspected")),
            "last_run_failed": bool(state.get("last_run_failed")),
            "inspect_same_changed_file_allowed": bool(state.get("last_run_failed")),
            "required_next_command": required_command,
        }
        tools = prompt.get("available_tools")
        if isinstance(tools, dict):
            tools["run"] = (
                "execute argv list in candidate workspace; after tests, inspect the final change with "
                "['git','diff','--',<changed-path>] rather than re-inspecting source"
            )
        kwargs["prompt"] = prompt
        return original_generate_role(role=role, **kwargs)

    coder._worker_observation = MethodType(controlled_worker_observation, coder)
    coder._generate_role = MethodType(controlled_generate_role, coder)
    coder._stoe_workflow_control_installed = True
