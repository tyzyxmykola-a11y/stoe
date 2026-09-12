"""Bounded trusted diagnostics for standalone StoeCoder runs.

Adds actionable observability to the existing events.jsonl journal without
creating a second logging channel or exposing prompts, role contracts, source
contents, credentials, raw model responses, or full command output.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from types import MethodType
from typing import Any

from stoe_coder import MAX_TOOL_STEPS

_MAX_TAIL = 700


def _clip(value: Any, limit: int = 500) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _redact_tail(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+", r"\1 <redacted>", text)
    text = re.sub(
        r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+",
        lambda match: match.group(1) + "=<redacted>",
        text,
    )
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n") if line.strip()]
    return _clip(" | ".join(lines[-8:]), _MAX_TAIL)


def _safe_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _artifact_dir(coder: Any, action_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(action_id or ""))
    return Path(coder.artifact_root) / safe


def _selected_model(coder: Any, role: str) -> str:
    evidence = getattr(coder, "_task_evidence", None)
    for item in getattr(evidence, "selected_roles", None) or []:
        if isinstance(item, dict) and item.get("name") == role:
            return str(item.get("resolved_model") or item.get("model") or "")
    return ""


def _role_source(coder: Any, role: str) -> str:
    model = _selected_model(coder, role)
    label = role.title()
    return f"{label}[{model}]" if model else label


def _step_from_action(action_id: str) -> int | None:
    match = re.search(r":coder:(\d+)$", str(action_id or ""))
    return int(match.group(1)) if match else None


def _failure_class(condition: Any) -> str:
    text = str(condition or "").lower()
    if "deterministic verification failed" in text:
        return "verification_failed"
    if "independent reviewer rejected" in text:
        return "review_rejected"
    if "response incomplete" in text:
        return "model_incomplete"
    if "repeated identical read-only action" in text or "consecutive exploration limit" in text:
        return "action_loop"
    if "without a repository change" in text:
        return "no_candidate_change"
    if "outside task scope" in text:
        return "scope_violation"
    if "active repository changed" in text or "integrated path set differs" in text:
        return "integration_invalidated"
    if "operator stopped" in text:
        return "operator_stopped"
    return "runtime_failure"


def _raw_model_detail(coder: Any, action_id: str) -> dict[str, Any]:
    raw = _safe_json(_artifact_dir(coder, action_id) / "raw_response.json") or {}
    return {
        "done": raw.get("done"),
        "done_reason": raw.get("done_reason"),
        "prompt_tokens": raw.get("prompt_eval_count"),
        "output_tokens": raw.get("eval_count"),
    }


def _verification_failure(coder: Any, task_id: str, touched: list[str]) -> dict[str, Any] | None:
    commands = coder._verification_commands(touched)
    for index, command in enumerate(commands, 1):
        result = _safe_json(_artifact_dir(coder, f"{task_id}:verify:{index}") / "result.json")
        if not result:
            continue
        if result.get("exit_code") or result.get("timed_out") or result.get("cancelled"):
            tail = _redact_tail(result.get("stderr")) or _redact_tail(result.get("stdout"))
            return {
                "index": index,
                "total": len(commands),
                "command": command,
                "exit_code": result.get("exit_code"),
                "duration_seconds": result.get("duration_seconds"),
                "timed_out": bool(result.get("timed_out")),
                "cancelled": bool(result.get("cancelled")),
                "tail": tail,
            }
    return None


def install_diagnostic_logging(coder: Any) -> None:
    """Install one bounded diagnostics layer on an initialized runtime."""

    if getattr(coder, "_stoe_diagnostic_logging_installed", False):
        return

    original_generate_role = coder._generate_role
    original_execute_tool = coder._execute_tool
    original_verify_candidate = coder._verify_candidate
    original_review = coder._review
    original_integrate = coder._integrate
    original_rollback = coder._rollback
    original_task_main = coder._task_main

    def diagnostic_generate_role(self, *, role, **kwargs):
        action_id = str(kwargs.get("action_id") or "")
        source = _role_source(self, role)
        started = time.monotonic()
        try:
            result, metrics = original_generate_role(role=role, **kwargs)
        except Exception as exc:
            detail = _raw_model_detail(self, action_id)
            duration = round(time.monotonic() - started, 3)
            message = f"model call failed · {duration}s"
            if detail.get("done_reason") not in {None, ""}:
                message += f" · done_reason={_clip(detail['done_reason'], 80)}"
            message += f" · {_clip(exc, 260)}"
            self._event(source, message, level="error", event_type="model_call_failed",
                        role=role, action_id=action_id, duration_seconds=duration, **detail)
            raise
        duration = metrics.get("duration_seconds", round(time.monotonic() - started, 3))
        step = _step_from_action(action_id)
        token_text = ""
        if metrics.get("prompt_tokens") is not None or metrics.get("output_tokens") is not None:
            token_text = f" · {metrics.get('prompt_tokens', '?')}→{metrics.get('output_tokens', '?')} tokens"
        prefix = f"model call {step}" if step is not None else "model call"
        self._event(source, f"{prefix} · {duration}s{token_text}", event_type="model_call_complete",
                    role=role, action_id=action_id, model=metrics.get("model"), digest=metrics.get("digest"),
                    duration_seconds=duration, prompt_tokens=metrics.get("prompt_tokens"),
                    output_tokens=metrics.get("output_tokens"))
        return result, metrics

    def diagnostic_execute_tool(self, task_id: str, step: int, worktree, request: dict[str, Any], allowed_paths):
        kind = str(request.get("kind") or "")
        source = _role_source(self, "coder")
        started = time.monotonic()
        try:
            feedback = original_execute_tool(task_id, step, worktree, request, allowed_paths)
        except Exception as exc:
            self._event(source, f"step {step}/{MAX_TOOL_STEPS} · {kind} failed · {_clip(exc, 300)}",
                        level="error", event_type="tool_result", task_id=task_id, step=step,
                        remaining_steps=max(0, MAX_TOOL_STEPS - step), kind=kind, executed=False,
                        failure_condition=_clip(exc, 500))
            raise

        elapsed = round(time.monotonic() - started, 3)
        remaining = max(0, MAX_TOOL_STEPS - step)
        executed = feedback.get("executed", True) is not False
        message = f"step {step}/{MAX_TOOL_STEPS} · {kind} result"
        metadata: dict[str, Any] = {
            "event_type": "tool_result", "task_id": task_id, "step": step,
            "remaining_steps": remaining, "kind": kind, "executed": executed,
            "duration_seconds": elapsed,
        }

        if not executed:
            message += f" · rejected · {_clip(feedback.get('error'), 260)} · remaining={remaining}"
            metadata["failure_condition"] = _clip(feedback.get("failure_condition") or feedback.get("error"), 500)
        elif kind == "inspect":
            message += f" · chars={feedback.get('chars', 0)} · truncated={'yes' if feedback.get('truncated') else 'no'}"
            metadata.update(chars=feedback.get("chars"), truncated=bool(feedback.get("truncated")))
        elif kind == "search":
            matches = len([line for line in str(feedback.get("stdout") or "").splitlines() if line.strip()])
            message += f" · exit={feedback.get('exit_code')} · matches≈{matches} · {feedback.get('duration_seconds', elapsed)}s"
            metadata.update(exit_code=feedback.get("exit_code"), approximate_matches=matches,
                            timed_out=bool(feedback.get("timed_out")), cancelled=bool(feedback.get("cancelled")))
        elif kind == "write":
            path = _clip(feedback.get("path") or request.get("path"), 220)
            message = f"candidate changed · {path} · bytes={feedback.get('bytes', '?')}"
            metadata.update(path=path, bytes=feedback.get("bytes"), sha256=feedback.get("sha256"))
        elif kind == "delete":
            path = _clip(feedback.get("path") or request.get("path"), 220)
            message = f"candidate changed · deleted {path}"
            metadata["path"] = path
        elif kind == "move":
            message = f"candidate changed · move {_clip(feedback.get('from'), 180)} → {_clip(feedback.get('to'), 180)}"
            metadata.update(source_path=_clip(feedback.get("from"), 220), destination=_clip(feedback.get("to"), 220))
        elif kind == "run":
            message += f" · exit={feedback.get('exit_code')} · {feedback.get('duration_seconds', elapsed)}s"
            if feedback.get("timed_out"):
                message += " · timeout"
            if feedback.get("cancelled"):
                message += " · cancelled"
            metadata.update(exit_code=feedback.get("exit_code"), timed_out=bool(feedback.get("timed_out")),
                            cancelled=bool(feedback.get("cancelled")))
            if feedback.get("exit_code") or feedback.get("timed_out") or feedback.get("cancelled"):
                tail = _redact_tail(feedback.get("stderr")) or _redact_tail(feedback.get("stdout"))
                if tail:
                    message += f" · tail={tail}"
                    metadata["output_tail"] = tail
        elif kind == "finish":
            message += " · candidate declared ready"

        self._event(source, message, level="warning" if not executed else "info", **metadata)
        return feedback

    def diagnostic_verify_candidate(self, task_id: str, workspace, touched: list[str]):
        self._event("Candidate", "verification start · files=" + (", ".join(touched[:8]) if touched else "(none)"),
                    task_id=task_id, touched=touched, check_count=len(self._verification_commands(touched)))
        started = time.monotonic()
        try:
            results = original_verify_candidate(task_id, workspace, touched)
        except Exception:
            detail = _verification_failure(self, task_id, touched)
            if detail:
                message = (f"failure detail · check={detail['index']}/{detail['total']} · exit={detail['exit_code']}"
                           f" · {detail['duration_seconds']}s")
                if detail["timed_out"]:
                    message += " · timeout"
                if detail["cancelled"]:
                    message += " · cancelled"
                if detail["tail"]:
                    message += f" · tail={detail['tail']}"
                self._event("Tests", message, level="error", event_type="verification_failure_detail", **detail)
            raise
        self._event("Tests", f"verification complete · {len(results)}/{len(results)} PASS · {round(time.monotonic() - started, 3)}s",
                    event_type="verification_complete", task_id=task_id, checks=len(results))
        return results

    def diagnostic_review(self, task_id: str, objective: str, diff: str, tests: list[dict[str, Any]], metrics: list[dict[str, Any]]):
        source = _role_source(self, "reviewer")
        self._event(source, f"review started · diff_chars={len(diff)} · checks={len(tests)}",
                    task_id=task_id, event_type="review_started", diff_chars=len(diff), checks=len(tests))
        started = time.monotonic()
        try:
            result = original_review(task_id, objective, diff, tests, metrics)
        except Exception as exc:
            self._event(source, f"review failed · {_clip(exc, 360)}", level="error",
                        task_id=task_id, event_type="review_failed")
            raise
        summary = _clip(result.get("summary"), 360)
        self._event(source, f"{result.get('verdict')} · {summary}" if summary else str(result.get("verdict")),
                    level="info" if result.get("verdict") == "accept" else "warning", task_id=task_id,
                    event_type="review_detail", duration_seconds=round(time.monotonic() - started, 3),
                    verdict=result.get("verdict"), summary=summary,
                    defects=[_clip(item, 400) for item in (result.get("defects") or [])[:8]])
        for defect in (result.get("defects") or [])[:8]:
            self._event(source, "defect · " + _clip(defect, 420), level="warning",
                        task_id=task_id, event_type="review_defect")
        return result

    def diagnostic_integrate(self, task_id: str, parent_head: str, candidate_root, touched: list[str]):
        self._event("Integration", "start · files=" + (", ".join(touched[:8]) if touched else "(none)"),
                    task_id=task_id, touched=touched)
        try:
            result = original_integrate(task_id, parent_head, candidate_root, touched)
        except Exception as exc:
            self._event("Integration", "failed · " + _clip(exc, 420), level="error", task_id=task_id,
                        touched=touched, failure_condition=_clip(exc, 500))
            raise
        self._event("Integration", f"complete · files={len(touched)}", task_id=task_id, touched=touched)
        return result

    def diagnostic_rollback(self, parent_head: str, touched: list[str]):
        self._event("Rollback", f"start · files={len(touched)}", level="warning", parent_head=parent_head, touched=touched)
        result = original_rollback(parent_head, touched)
        self._event("Rollback", "complete", level="warning", parent_head=parent_head, touched=touched)
        return result

    def diagnostic_task_main(self, task_id: str, objective: str, commit_requested: bool, push_requested: bool, allowed_paths):
        result = original_task_main(task_id, objective, commit_requested, push_requested, allowed_paths)
        try:
            report = self._load_state().get("task_report") or {}
            outcome = str(report.get("outcome") or "")
            failure = str(report.get("failure_condition") or "")
            if outcome and outcome != "success":
                failure_class = _failure_class(failure)
                self._event("Failure", f"{failure_class} · {_clip(failure, 500)}",
                            level="error" if outcome == "failure" else "warning",
                            event_type="terminal_failure_detail", task_id=task_id, outcome=outcome,
                            failure_class=failure_class, failure_condition=_clip(failure, 800))
        except Exception as exc:
            self._event("Diagnostics", "terminal diagnostic read failed · " + _clip(exc, 260),
                        level="warning", task_id=task_id)
        return result

    coder._generate_role = MethodType(diagnostic_generate_role, coder)
    coder._execute_tool = MethodType(diagnostic_execute_tool, coder)
    coder._verify_candidate = MethodType(diagnostic_verify_candidate, coder)
    coder._review = MethodType(diagnostic_review, coder)
    coder._integrate = MethodType(diagnostic_integrate, coder)
    coder._rollback = MethodType(diagnostic_rollback, coder)
    coder._task_main = MethodType(diagnostic_task_main, coder)
    coder._stoe_diagnostic_logging_installed = True
