"""Local-only model I/O flight recorder and UI bridge for standalone StoeCoder.

The compact events.jsonl journal stays compact. Exact Ollama request payloads are
captured once in a sidecar artifact tree, while raw/parsed responses remain in
the normal action artifacts. The browser fetches them only when the operator
expands a Model I/O entry.
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


def install_model_io_capture(coder: Any) -> None:
    """Capture the exact payload passed to Ollama /api/generate per action."""

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
        try:
            result = original_generate(action_id=action_id, **kwargs)
        except Exception as exc:
            directory = sidecar_root / _safe_name(action_id)
            _atomic_json(directory / "error.json", {
                "action_id": action_id,
                "captured_at": time.time(),
                "type": type(exc).__name__,
                "message": str(exc)[:2000],
            })
            raise
        finally:
            context.action_id = None
        return result

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
    """Register the local artifact endpoint and inject the expandable UI script."""

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

    @app.after_request
    def inject_model_io_ui(response):
        if request.path != "/" or response.status_code != 200 or response.mimetype != "text/html":
            return response
        try:
            response.direct_passthrough = False
            body = response.get_data(as_text=True)
            marker = '<script src="/static/model_io.js"></script>'
            if marker not in body:
                insertion = marker + "\n"
                body = body.replace("</body>", insertion + "</body>") if "</body>" in body else body + insertion
                response.set_data(body)
                response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            # UI enrichment must never prevent the core localhost UI from loading.
            return response
        return response
