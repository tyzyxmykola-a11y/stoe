"""Local-only model I/O flight recorder and UI bridge for standalone StoeCoder.

The compact events.jsonl journal stays readable while exact model requests and
responses are also appended to model_io.jsonl for sequential debugging. Existing
per-action artifacts remain authoritative and power the expandable browser UI.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from types import MethodType
from typing import Any, Callable

from flask import jsonify, request

_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_SAFE_ACTION = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_MODEL_IO_UI_VERSION = "20260911-3"
_MODEL_IO_LOG_LOCK = threading.Lock()


def _safe_name(action_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(action_id or ""))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _read_json(path: Path) -> Any | None:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_ARTIFACT_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _model_io_log_path(coder: Any) -> Path:
    events_path = getattr(coder, "events_path", None)
    if events_path:
        return Path(events_path).with_name("model_io.jsonl")
    return Path(coder.artifact_root) / "model_io.jsonl"


def _append_model_io(coder: Any, record: dict[str, Any]) -> None:
    path = _model_io_log_path(coder)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with _MODEL_IO_LOG_LOCK:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line)


def _model_io_record(
    coder: Any,
    action_id: str,
    *,
    role: str | None = None,
    resolved_model: Any = None,
    parsed_result: Any = None,
    metrics: Any = None,
    error: Any = None,
) -> dict[str, Any]:
    safe = _safe_name(action_id)
    sidecar = Path(coder.artifact_root) / "_model_io" / safe
    action = Path(coder.artifact_root) / safe
    request_artifact = _read_json(sidecar / "request.json")
    raw_response = _read_json(action / "raw_response.json")
    parsed_response = _read_json(action / "result.json")
    stored_metrics = _read_json(action / "metrics.json")
    captured_error = _read_json(sidecar / "error.json")

    if parsed_response is None:
        parsed_response = parsed_result
    if stored_metrics is None:
        stored_metrics = metrics
    if captured_error is None:
        captured_error = error

    model = None
    if isinstance(stored_metrics, dict):
        model = stored_metrics.get("model")
    if not model and isinstance(request_artifact, dict):
        payload = request_artifact.get("payload")
        if isinstance(payload, dict):
            model = payload.get("model")
    if not model and isinstance(resolved_model, (tuple, list)) and resolved_model:
        model = resolved_model[0]
    if not model and isinstance(resolved_model, str):
        model = resolved_model

    return {
        "time": time.time(),
        "task_id": str(action_id).split(":", 1)[0] if action_id else None,
        "action_id": action_id,
        "role": role,
        "model": model,
        "request": request_artifact,
        "raw_response": raw_response,
        "parsed_response": parsed_response,
        "metrics": stored_metrics,
        "error": captured_error,
    }


def clear_runtime_logs(coder: Any) -> dict[str, Any]:
    """Manually clear compact events and sequential model I/O logs only."""

    events_path = Path(coder.events_path)
    model_io_path = _model_io_log_path(coder)
    cleared: list[str] = []
    with _MODEL_IO_LOG_LOCK:
        for path in (events_path, model_io_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8", newline="\n")
            cleared.append(str(path))
    return {"ok": True, "cleared": cleared, "artifacts_preserved": True}


def install_model_io_capture(coder: Any) -> None:
    """Capture exact Ollama I/O per action and append one JSONL flight record."""

    ollama = coder.ollama
    if getattr(ollama, "_stoe_model_io_capture_installed", False):
        return

    original_generate = ollama.generate
    original_json = ollama._json
    context = threading.local()
    sidecar_root = Path(coder.artifact_root) / "_model_io"

    def captured_json(self, path: str, payload: dict[str, Any] | None = None, timeout: int = 30):
        action_id = getattr(context, "action_id", None)
        if path == "/api/generate" and action_id and isinstance(payload, dict):
            directory = sidecar_root / _safe_name(action_id)
            _atomic_json(directory / "request.json", {
                "action_id": action_id,
                "captured_at": time.time(),
                "endpoint": path,
                "timeout_seconds": timeout,
                "payload": payload,
            })
        return original_json(path, payload, timeout)

    def captured_generate(self, *, action_id: str, **kwargs):
        context.action_id = action_id
        role = kwargs.get("role")
        resolved_model = kwargs.get("resolved_model")
        try:
            returned = original_generate(action_id=action_id, **kwargs)
        except Exception as exc:
            directory = sidecar_root / _safe_name(action_id)
            captured_error = {
                "action_id": action_id,
                "captured_at": time.time(),
                "type": type(exc).__name__,
                "message": str(exc)[:2000],
            }
            _atomic_json(directory / "error.json", captured_error)
            _append_model_io(coder, _model_io_record(
                coder,
                action_id,
                role=role,
                resolved_model=resolved_model,
                error=captured_error,
            ))
            raise
        finally:
            context.action_id = None

        parsed_result = None
        metrics = None
        if isinstance(returned, tuple) and len(returned) >= 2:
            parsed_result, metrics = returned[0], returned[1]
        _append_model_io(coder, _model_io_record(
            coder,
            action_id,
            role=role,
            resolved_model=resolved_model,
            parsed_result=parsed_result,
            metrics=metrics,
        ))
        return returned

    ollama._json = MethodType(captured_json, ollama)
    ollama.generate = MethodType(captured_generate, ollama)
    ollama._stoe_model_io_capture_installed = True


def model_io_snapshot(coder: Any, action_id: str) -> dict[str, Any]:
    """Return only the known model-call artifacts for one validated action id."""

    if not _SAFE_ACTION.fullmatch(str(action_id or "")):
        raise ValueError("invalid model action id")

    safe = _safe_name(action_id)
    sidecar = Path(coder.artifact_root) / "_model_io" / safe
    action = Path(coder.artifact_root) / safe

    request_artifact = _read_json(sidecar / "request.json")
    raw_response = _read_json(action / "raw_response.json")
    parsed_response = _read_json(action / "result.json")
    metrics = _read_json(action / "metrics.json")
    error = _read_json(sidecar / "error.json")

    if all(value is None for value in (request_artifact, raw_response, parsed_response, metrics, error)):
        raise FileNotFoundError("model I/O artifacts not found")

    return {
        "action_id": action_id,
        "request": request_artifact,
        "raw_response": raw_response,
        "parsed_response": parsed_response,
        "metrics": metrics,
        "error": error,
    }


def install_model_io_ui(app: Any, coder: Any, local_request_check: Callable[[], bool]) -> None:
    """Register local Model I/O endpoints and inject the expandable UI script."""

    if app.config.get("STOE_MODEL_IO_UI_INSTALLED"):
        return
    app.config["STOE_MODEL_IO_UI_INSTALLED"] = True

    @app.route("/api/coder/model-io/<path:action_id>", methods=["GET"])
    def coder_model_io(action_id: str):
        if not local_request_check():
            return jsonify({"error": "SToE Coder is localhost-only"}), 403
        try:
            return jsonify(model_io_snapshot(coder, action_id))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.route("/api/coder/logs/clear", methods=["POST"])
    def coder_clear_logs():
        if not local_request_check():
            return jsonify({"error": "SToE Coder is localhost-only"}), 403
        return jsonify(clear_runtime_logs(coder))

    @app.after_request
    def inject_model_io_ui(response):
        if request.path != "/" or response.status_code != 200 or response.mimetype != "text/html":
            return response
        try:
            response.direct_passthrough = False
            body = response.get_data(as_text=True)
            marker_prefix = '<script src="/static/model_io.js'
            marker = f'<script src="/static/model_io.js?v={_MODEL_IO_UI_VERSION}"></script>'
            if marker_prefix not in body:
                insertion = marker + "\n"
                body = body.replace("</body>", insertion + "</body>") if "</body>" in body else body + insertion
                response.set_data(body)
                response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            return response
        return response
