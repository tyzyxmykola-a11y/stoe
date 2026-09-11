"""Trusted event-log enrichment for the standalone StoeCoder UI.

The core runtime remains unchanged. This adapter rewrites only event presentation
at the runtime boundary while preserving the existing events.jsonl journal.
"""

from __future__ import annotations

import json
import re
from types import MethodType
from typing import Any

_TOOL_KINDS = {"inspect", "search", "write", "delete", "move", "run", "finish"}
_MAX_VISIBLE_FIELD = 180
_MAX_VISIBLE_COMMAND = 240


def _clip(value: Any, limit: int = _MAX_VISIBLE_FIELD) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _role_model(coder: Any, role: str) -> str:
    evidence = getattr(coder, "_task_evidence", None)
    selected = getattr(evidence, "selected_roles", None) or []
    for item in selected:
        if isinstance(item, dict) and item.get("name") == role:
            return str(item.get("resolved_model") or item.get("model") or "")
    return ""


def _artifact_dir(coder: Any, action_id: str):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(action_id or ""))
    return coder.artifact_root / safe


def _read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _tool_request(coder: Any, action_id: str) -> dict[str, Any] | None:
    if not action_id:
        return None
    value = _read_json(_artifact_dir(coder, action_id) / "result.json")
    if value and value.get("kind") in _TOOL_KINDS:
        return value
    return None


def _redact_arg(arg: str) -> str:
    lowered = arg.lower()
    sensitive = ("token=", "password=", "passwd=", "secret=", "authorization=", "api_key=", "apikey=")
    if any(marker in lowered for marker in sensitive):
        if "=" in arg:
            return arg.split("=", 1)[0] + "=<redacted>"
        return "<redacted>"
    return arg


def _command_preview(command: Any) -> str:
    if not isinstance(command, list):
        return ""
    text = " ".join(_redact_arg(_clip(arg, 80)) for arg in command[:16])
    if len(command) > 16:
        text += " …"
    return _clip(text, _MAX_VISIBLE_COMMAND)


def _format_tool_request(request: dict[str, Any]) -> str:
    kind = str(request.get("kind") or "action")
    path = _clip(request.get("path") or ".")
    if kind == "inspect":
        return f"inspect {path}"
    if kind == "search":
        query = _clip(request.get("query"), 120)
        return f'search "{query}" in {path}'
    if kind in {"write", "delete"}:
        return f"{kind} {path}"
    if kind == "move":
        return f"move {path} → {_clip(request.get('destination'))}"
    if kind == "run":
        command = _command_preview(request.get("command"))
        cwd = _clip(request.get("cwd") or ".")
        return f"run {command or '(command)'} in {cwd}"
    if kind == "finish":
        summary = _clip(request.get("summary"), 200)
        return "finish" + (f" {summary}" if summary else "")
    return kind


def _safe_tool_metadata(request: dict[str, Any]) -> dict[str, Any]:
    kind = str(request.get("kind") or "")
    metadata: dict[str, Any] = {"kind": kind}
    if kind in {"inspect", "search", "write", "delete", "move"}:
        metadata["path"] = _clip(request.get("path"))
    if kind == "search":
        metadata["query"] = _clip(request.get("query"), 120)
    if kind == "move":
        metadata["destination"] = _clip(request.get("destination"))
    if kind == "run":
        metadata["cwd"] = _clip(request.get("cwd") or ".")
        metadata["command_preview"] = _command_preview(request.get("command"))
    if kind == "finish":
        metadata["summary"] = _clip(request.get("summary"), 200)
    return metadata


def _incomplete_reason(coder: Any) -> tuple[str | None, str | None]:
    try:
        state = coder._load_state()
    except Exception:
        return None, None
    action_id = state.get("active_action")
    if not action_id:
        return None, None
    raw = _read_json(_artifact_dir(coder, action_id) / "raw_response.json")
    reason = raw.get("done_reason") if raw else None
    return str(action_id), str(reason) if reason not in {None, ""} else None


def install_event_logging(coder: Any) -> None:
    """Install one bounded event-enrichment layer on a StoeCoder runtime instance."""

    if getattr(coder, "_stoe_event_logging_installed", False):
        return

    original_event = coder._event

    def enriched_event(self, source: str, message: str, level: str = "info", **metadata: Any) -> str:
        if source == "Worker":
            model = str(metadata.get("model") or _role_model(self, "coder") or "")
            role_source = f"Coder[{model}]" if model else "Coder"
            if message.endswith(" requested"):
                action_id = str(metadata.get("action_id") or "")
                request = _tool_request(self, action_id)
                if request is not None:
                    message = _format_tool_request(request)
                    metadata = {**metadata, "role": "coder", "model": model or metadata.get("model"),
                                **_safe_tool_metadata(request)}
                else:
                    kind = message.split(" ", 1)[0]
                    message = f"{kind} requested"
                    metadata = {**metadata, "role": "coder", "model": model or metadata.get("model"),
                                "kind": kind}
            else:
                metadata = {**metadata, "role": "coder", "model": model or metadata.get("model")}
            source = role_source

        elif source == "Reviewer":
            model = str(metadata.get("model") or _role_model(self, "reviewer") or "")
            if model:
                source = f"Reviewer[{model}]"
            metadata = {**metadata, "role": "reviewer", "model": model or metadata.get("model")}

        elif source == "Coder" and message == "local worker response incomplete":
            model = _role_model(self, "coder")
            action_id, reason = _incomplete_reason(self)
            source = f"Coder[{model}]" if model else "Coder"
            message = "response incomplete" + (f" · done_reason={_clip(reason, 80)}" if reason else "")
            metadata = {**metadata, "role": "coder", "model": model or metadata.get("model")}
            if action_id:
                metadata["action_id"] = action_id
            if reason:
                metadata["done_reason"] = _clip(reason, 80)

        return original_event(source, message, level=level, **metadata)

    coder._event = MethodType(enriched_event, coder)
    coder._stoe_event_logging_installed = True
