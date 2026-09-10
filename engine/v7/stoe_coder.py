"""Local SToE Coder executive for the v7 Information Field Navigator.

The browser submits operator intent.  This trusted, localhost-only executive
owns filesystem, subprocess, Git, Ollama, and SToE Memory authority.  Local
workers receive an isolated Git worktree and a bounded inspect/edit/run feedback
loop; credentials and activation authority are never placed in model context.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / "agent" / "runtime" / "stoe_coder_v1"
STATE_PATH = RUNTIME_ROOT / "state.json"
EVENTS_PATH = RUNTIME_ROOT / "events.jsonl"
ARTIFACT_ROOT = RUNTIME_ROOT / "artifacts"
WORKTREE_ROOT = RUNTIME_ROOT / "worktrees"
DEFAULT_OBSERVER = "STATE_055a46a188ab4ec9"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MAX_OUTPUT_BYTES = 1_000_000
MAX_VISIBLE_OUTPUT = 6_000
MAX_TOOL_STEPS = 14


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _git(repo: Path, *args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=repo, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
    return result


def _safe_repo_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("path is empty or invalid")
    candidate = (root / value).resolve()
    if candidate != root.resolve() and root.resolve() not in candidate.parents:
        raise ValueError("path escapes candidate workspace")
    relative = candidate.relative_to(root.resolve()).as_posix()
    if relative == ".git" or relative.startswith(".git/"):
        raise ValueError("worker cannot modify Git internals")
    if any(part.lower() in {".env", "credentials.json", "id_rsa", "id_ed25519"} for part in candidate.parts):
        raise ValueError("credential-bearing path is unavailable to workers")
    return candidate


def _default_state() -> dict[str, Any]:
    return {
        "format": "stoe.coder.state.v1", "authority": "FULL LOCAL",
        "orchestration": "AUTO", "status": "idle", "observer": DEFAULT_OBSERVER,
        "objective": "", "task_id": None, "active_action": None,
        "closed_actions": [], "branch": None, "head": None, "git": "unknown",
        "tests": "not_run", "worker": None, "model": None, "stop_requested": False,
        "last_result": None, "next_action": "operator_intent",
    }


def _ollama_schema(schema: Any) -> Any:
    """Remove bounds unsupported by Ollama's grammar compiler.

    The original schema remains the deterministic post-parse authority.
    """
    if isinstance(schema, dict):
        return {key: _ollama_schema(value) for key, value in schema.items() if key not in {"maxLength", "maxItems", "minLength", "minItems"}}
    if isinstance(schema, list):
        return [_ollama_schema(value) for value in schema]
    return schema


def _validate_bounds(value: Any, schema: dict[str, Any], path: str = "result") -> None:
    if isinstance(value, str) and len(value) > int(schema.get("maxLength", len(value))):
        raise ValueError(f"{path} exceeds maxLength")
    if isinstance(value, list):
        if len(value) > int(schema.get("maxItems", len(value))):
            raise ValueError(f"{path} exceeds maxItems")
        for index, item in enumerate(value):
            _validate_bounds(item, schema.get("items", {}), f"{path}[{index}]")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _validate_bounds(item, properties[key], f"{path}.{key}")


@dataclass
class CommandResult:
    action_id: str
    cwd: str
    command: list[str]
    exit_code: int
    duration_seconds: float
    stdout: str
    stderr: str
    stdout_artifact: str
    stderr_artifact: str
    stdout_sha256: str
    stderr_sha256: str
    truncated: bool
    timed_out: bool
    cancelled: bool

    def compact(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id, "cwd": self.cwd, "command": self.command,
            "exit_code": self.exit_code, "duration_seconds": self.duration_seconds,
            "stdout": self.stdout, "stderr": self.stderr,
            "stdout_artifact": self.stdout_artifact, "stderr_artifact": self.stderr_artifact,
            "stdout_sha256": self.stdout_sha256, "stderr_sha256": self.stderr_sha256,
            "truncated": self.truncated, "timed_out": self.timed_out, "cancelled": self.cancelled,
        }


class FullLocalRunner:
    """Trusted command runner under the current Windows user identity.

    It intentionally does not use an executable allowlist.  A narrow destructive
    boundary protects canonical history, remote releases/tags, and credentials.
    """

    def __init__(self, artifact_root: Path, stop_event: threading.Event | None = None) -> None:
        self.artifact_root = artifact_root.resolve()
        self.stop_event = stop_event or threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    @staticmethod
    def validate_command(command: list[str]) -> list[str]:
        if not isinstance(command, list) or not command or len(command) > 64:
            raise ValueError("command must contain 1..64 arguments")
        if any(not isinstance(arg, str) or not arg or len(arg) > 4_000 for arg in command):
            raise ValueError("command argument is invalid")
        joined = " ".join(command).lower()
        forbidden = (
            "git push --force", "git push -f", "git reset --hard", "git filter-repo",
            "git filter-branch", "git push origin main", "git push origin master",
            "git push --delete", "git tag -d", "gh release delete",
            "credential.helper", "git credential", "ssh-keygen", "export private key",
        )
        if any(token in joined for token in forbidden):
            raise PermissionError("command crosses the protected destructive/credential boundary")
        return list(command)

    def cancel(self) -> None:
        self.stop_event.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    def run(self, *, action_id: str, command: list[str], cwd: Path, timeout: int = 300) -> CommandResult:
        command = self.validate_command(command)
        cwd = cwd.resolve()
        run_dir = self.artifact_root / re.sub(r"[^A-Za-z0-9_.-]", "_", action_id)
        if run_dir.exists():
            raise RuntimeError("closed command action cannot be retried")
        run_dir.mkdir(parents=True)
        stdout_path, stderr_path = run_dir / "stdout.bin", run_dir / "stderr.bin"
        started = time.monotonic()
        timed_out = cancelled = False
        process: subprocess.Popen[bytes] | None = None
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            try:
                process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL, stdout=stdout_file, stderr=stderr_file)
            except OSError as exc:
                stderr_file.write((f"command launch failed: {exc}\n").encode("utf-8", "replace"))
            if process is not None:
                with self._lock:
                    self._process = process
                deadline = started + max(1, min(timeout, 3_600))
                while process.poll() is None:
                    if self.stop_event.is_set():
                        cancelled = True; process.terminate(); break
                    if time.monotonic() >= deadline:
                        timed_out = True; process.terminate(); break
                    time.sleep(0.05)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
                with self._lock:
                    self._process = None
        stdout_data, stderr_data = stdout_path.read_bytes(), stderr_path.read_bytes()
        if len(stdout_data) + len(stderr_data) > MAX_OUTPUT_BYTES:
            timed_out = True
        visible_out = stdout_data[:MAX_VISIBLE_OUTPUT].decode("utf-8", "replace")
        visible_err = stderr_data[:MAX_VISIBLE_OUTPUT].decode("utf-8", "replace")
        result = CommandResult(
            action_id, str(cwd), command, process.returncode if process is not None and process.returncode is not None else -1,
            round(time.monotonic() - started, 3), visible_out, visible_err,
            str(stdout_path), str(stderr_path), _sha256(stdout_data), _sha256(stderr_data),
            len(stdout_data) > MAX_VISIBLE_OUTPUT or len(stderr_data) > MAX_VISIBLE_OUTPUT,
            timed_out, cancelled,
        )
        _atomic_json(run_dir / "result.json", result.compact())
        return result


class OllamaWorker:
    def __init__(self, endpoint: str = OLLAMA_URL, artifact_root: Path = ARTIFACT_ROOT) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.artifact_root = artifact_root.resolve()

    def _json(self, path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.endpoint + path, data=data, headers={"Content-Type": "application/json"}, method="GET" if data is None else "POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama unavailable or malformed: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Ollama response is not an object")
        return value

    def models(self) -> list[dict[str, Any]]:
        return list(self._json("/api/tags").get("models", []))

    def choose(self, role: str) -> tuple[str, str]:
        models = self.models()
        names = {str(item.get("name")): str(item.get("digest")) for item in models}
        failures: dict[str, int] = {}
        for path in list(self.artifact_root.glob("*/raw_response.json"))[-50:]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("done_reason") in {"length", "error"}:
                failed_model = str(value.get("model", ""))
                failures[failed_model] = failures.get(failed_model, 0) + 1
        task_models: dict[tuple[str, str], int] = {}
        for path in self.artifact_root.glob("TASK_*_coder_*/raw_response.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            task_prefix = path.parent.name.split("_coder_", 1)[0]
            key = (task_prefix, str(value.get("model", "")))
            task_models[key] = task_models.get(key, 0) + 1
        for (_, failed_model), count in task_models.items():
            if count >= MAX_TOOL_STEPS:
                failures[failed_model] = failures.get(failed_model, 0) + 2
        state_path = self.artifact_root.parent / "state.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            last = state.get("last_result") or {}
            if "exhausted tool-step budget" in str(last.get("error", "")) and last.get("metrics"):
                failed_model = str(last["metrics"][-1].get("model", ""))
                failures[failed_model] = failures.get(failed_model, 0) + 2
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass
        preferences = (
            ["qwen3-coder:latest", "gemma4:26b", "gemma3:27b", "gemma4:12b"]
            if role in {"coder", "debugger"}
            else ["gemma4:26b", "gemma3:27b", "maverick:latest", "llama3.1:latest"]
        )
        for name in preferences:
            if name in names and failures.get(name, 0) < 2:
                return name, names[name]
        candidates = [item for item in models if "embed" not in str(item.get("name", "")).lower()]
        if not candidates:
            raise RuntimeError("no generation-capable local model is installed")
        candidates.sort(key=lambda item: int(item.get("size", 0)), reverse=True)
        return str(candidates[0]["name"]), str(candidates[0].get("digest", ""))

    def generate(self, *, action_id: str, role: str, prompt: dict[str, Any], schema: dict[str, Any], output_tokens: int, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
        model, digest = self.choose(role)
        run_dir = self.artifact_root / re.sub(r"[^A-Za-z0-9_.-]", "_", action_id)
        if run_dir.exists():
            raise RuntimeError("closed model action cannot be retried")
        run_dir.mkdir(parents=True)
        serialized = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
        payload = {
            "model": model, "think": False, "stream": False, "format": _ollama_schema(schema),
            "system": "You are a local SToE Coder worker inside an isolated candidate worktree. Use only the supplied tool feedback. Return exactly the requested JSON. Never claim a tool ran unless its result is supplied. Never request credentials or protected-history changes.",
            "prompt": serialized,
            "options": {"temperature": 0, "top_p": 0.9, "top_k": 40, "seed": seed, "num_ctx": 16_384, "num_predict": output_tokens},
            "keep_alive": 0,
        }
        started = time.monotonic()
        raw = self._json("/api/generate", payload, timeout=900)
        raw_bytes = (json.dumps(raw, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        (run_dir / "raw_response.json").write_bytes(raw_bytes)
        if raw.get("done") is not True or raw.get("done_reason") in {"length", "error"}:
            raise RuntimeError("local worker response incomplete")
        result = json.loads(str(raw.get("response", "")))
        _validate_bounds(result, schema)
        _atomic_json(run_dir / "result.json", result)
        metrics = {
            "action_id": action_id, "model": model, "digest": digest,
            "prompt_tokens": raw.get("prompt_eval_count"), "output_tokens": raw.get("eval_count"),
            "prompt_chars": len(serialized), "output_chars": len(str(raw.get("response", ""))),
            "artifact_bytes": len(raw_bytes) + (run_dir / "result.json").stat().st_size,
            "duration_seconds": round(time.monotonic() - started, 3),
            "raw_sha256": _sha256(raw_bytes), "result_path": str(run_dir / "result.json"),
        }
        _atomic_json(run_dir / "metrics.json", metrics)
        return result, metrics


TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["inspect", "search", "write", "delete", "move", "run", "finish"]},
        "path": {"type": "string", "maxLength": 300},
        "destination": {"type": "string", "maxLength": 300},
        "query": {"type": "string", "maxLength": 300},
        "content": {"type": "string", "maxLength": 60_000},
        "command": {"type": "array", "items": {"type": "string", "maxLength": 4_000}, "maxItems": 64},
        "cwd": {"type": "string", "maxLength": 300},
        "summary": {"type": "string", "maxLength": 1_000},
    },
    "required": ["kind", "path", "destination", "query", "content", "command", "cwd", "summary"],
    "additionalProperties": False,
}


class StoeCoderRuntime:
    def __init__(self, repo_root: Path = REPO_ROOT, *, ollama: OllamaWorker | None = None, field_store: Any | None = None, runtime_root: Path | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.runtime_root = (runtime_root or (self.repo_root / "agent" / "runtime" / "stoe_coder_v1")).resolve()
        self.state_path = self.runtime_root / "state.json"
        self.events_path = self.runtime_root / "events.jsonl"
        self.artifact_root = self.runtime_root / "artifacts"
        self.worktree_root = self.runtime_root / "worktrees"
        self.ollama = ollama or OllamaWorker(artifact_root=self.artifact_root)
        self._field = field_store
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._runner = FullLocalRunner(self.artifact_root, self._stop)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            _atomic_json(self.state_path, _default_state())

    def _load_state(self) -> dict[str, Any]:
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if value.get("format") != "stoe.coder.state.v1":
            raise RuntimeError("incompatible SToE Coder state")
        return value

    def _save_state(self, value: dict[str, Any]) -> None:
        _atomic_json(self.state_path, value)

    def _event(self, source: str, message: str, level: str = "info", **metadata: Any) -> None:
        event = {"id": uuid.uuid4().hex[:16], "time": time.time(), "source": source, "message": message[:500], "level": level, "metadata": metadata}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            state = self._load_state()
        branch = _git(self.repo_root, "branch", "--show-current").stdout.strip()
        head = _git(self.repo_root, "rev-parse", "HEAD").stdout.strip()
        porcelain = _git(self.repo_root, "status", "--porcelain=v1").stdout.splitlines()
        return {**state, "branch": branch, "head": head, "git": "clean" if not porcelain else f"{len(porcelain)} changed", "event_count": len(self.events())}

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        lines = self.events_path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 500)):]
        return [json.loads(line) for line in lines if line.strip()]

    def models(self) -> list[dict[str, Any]]:
        return [{"name": item.get("name"), "digest": item.get("digest"), "size": item.get("size")} for item in self.ollama.models()]

    def chat(self, message: str) -> dict[str, Any]:
        message = str(message or "").strip()
        if not message or len(message) > 4_000:
            raise ValueError("chat message must contain 1..4000 characters")
        before = (_git(self.repo_root, "rev-parse", "HEAD").stdout.strip(), _git(self.repo_root, "status", "--porcelain=v1").stdout)
        state = self.status()
        schema = {"type": "object", "properties": {"answer": {"type": "string", "maxLength": 2_000}}, "required": ["answer"], "additionalProperties": False}
        action_id = f"chat:{_sha256((message + state['observer']).encode())[:16]}"
        result, metrics = self.ollama.generate(action_id=action_id, role="reviewer", prompt={"operator_question": message, "status": {key: state.get(key) for key in ("status", "observer", "objective", "branch", "head", "git", "tests")}, "constraint": "Answer conversationally. Do not propose or claim repository mutation."}, schema=schema, output_tokens=800, seed=9101)
        after = (_git(self.repo_root, "rev-parse", "HEAD").stdout.strip(), _git(self.repo_root, "status", "--porcelain=v1").stdout)
        if before != after:
            raise RuntimeError("conversation boundary violated: repository state changed")
        self._event("Coder", "conversation answered without repository mutation", model=metrics["model"], metrics=metrics)
        return {"result": result["answer"], "metrics": metrics, "mutated": False}

    @staticmethod
    def task_identity(objective: str, parent_head: str, observer: str, predecessor: str | None = None) -> str:
        payload = {"objective": objective, "parent_head": parent_head, "observer": observer, "predecessor": predecessor}
        return "TASK_" + _sha256(json.dumps(payload, sort_keys=True).encode())[:16]

    def submit_task(self, objective: str, *, commit: bool = False, push: bool = False, allowed_paths: list[str] | None = None, predecessor: str | None = None) -> dict[str, Any]:
        objective = str(objective or "").strip()
        if not objective or len(objective) > 4_000:
            raise ValueError("objective must contain 1..4000 characters")
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("a development task is already active")
            state = self._load_state()
            branch = _git(self.repo_root, "branch", "--show-current").stdout.strip()
            head = _git(self.repo_root, "rev-parse", "HEAD").stdout.strip()
            if not branch.startswith("feature/"):
                raise RuntimeError("autonomous development requires a feature branch")
            if _git(self.repo_root, "status", "--porcelain=v1").stdout.strip():
                raise RuntimeError("active repository must be clean before a task")
            task_id = self.task_identity(objective, head, state["observer"], predecessor)
            if task_id in state.get("closed_actions", []):
                raise RuntimeError("task identity is already closed")
            state.update({"status": "queued", "objective": objective, "task_id": task_id, "active_action": None, "branch": branch, "head": head, "git": "clean", "tests": "not_run", "stop_requested": False, "last_result": None, "next_action": "worker_inspection", "task_options": {"commit": commit, "push": push, "allowed_paths": allowed_paths}})
            self._save_state(state)
            self._stop.clear()
            self._thread = threading.Thread(target=self._task_main, args=(task_id, objective, commit, push, allowed_paths), daemon=True)
            self._thread.start()
        self._event("Coder", "objective accepted", task_id=task_id, branch=branch, head=head)
        return {"accepted": True, "task_id": task_id, "status": "queued"}

    def stop(self) -> dict[str, Any]:
        self._runner.cancel()
        with self._state_lock:
            state = self._load_state()
            state.update({"stop_requested": True, "status": "stopping", "next_action": "resume_or_new_task"})
            self._save_state(state)
        self._event("Coder", "stop requested", level="warning", task_id=state.get("task_id"))
        return {"stopping": True, "task_id": state.get("task_id")}

    def resume(self) -> dict[str, Any]:
        with self._state_lock:
            state = self._load_state()
            if state["status"] not in {"stopped", "failed"} or not state.get("objective"):
                raise RuntimeError("no stopped or failed task is resumable")
            old_task = state.get("task_id")
            objective = state["objective"]
            options = state.get("task_options") or {}
        result = self.submit_task(objective, commit=bool(options.get("commit")), push=bool(options.get("push")), allowed_paths=options.get("allowed_paths"), predecessor=old_task)
        self._event("Coder", "task resumed as a fresh action lineage", prior_task=old_task, task_id=result["task_id"])
        return result

    def _worker_observation(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return history[-6:]

    def _task_main(self, task_id: str, objective: str, commit_requested: bool, push_requested: bool, allowed_paths: list[str] | None) -> None:
        worktree = self.worktree_root / task_id
        parent_head = _git(self.repo_root, "rev-parse", "HEAD").stdout.strip()
        history: list[dict[str, Any]] = []
        metrics: list[dict[str, Any]] = []
        touched: list[str] = []
        integrated = False
        try:
            _git(self.repo_root, "worktree", "add", "--detach", str(worktree), parent_head, timeout=180)
            self._event("SToE", "observer loaded", observer=self._load_state()["observer"])
            with self._state_lock:
                state = self._load_state(); state.update({"status": "active", "worker": "coder", "next_action": "local_tool_loop"}); self._save_state(state)
            for step in range(1, MAX_TOOL_STEPS + 1):
                if self._stop.is_set():
                    raise InterruptedError("operator stopped task")
                action_id = f"{task_id}:coder:{step}"
                with self._state_lock:
                    state = self._load_state(); state.update({"active_action": action_id, "next_action": "worker_tool_request"}); self._save_state(state)
                prompt = {"objective": objective, "candidate_workspace": "isolated Git worktree", "allowed_paths": allowed_paths or ["repository files except .git and credentials"], "available_tools": {"inspect": "read one repository-relative file", "search": "ripgrep query under optional relative path", "write": "replace/create UTF-8 text file", "delete": "delete ordinary candidate file", "move": "rename ordinary candidate file", "run": "execute argv list in candidate workspace", "finish": "declare candidate ready only after inspecting diff and running relevant tests"}, "recent_tool_feedback": self._worker_observation(history), "instruction": "Choose exactly one next tool action. Inspect before editing. Run tests and inspect git diff before finish. Use ordinary file mechanics; no patch serialization."}
                request, call_metrics = self.ollama.generate(action_id=action_id, role="coder", prompt=prompt, schema=TOOL_SCHEMA, output_tokens=4_000, seed=9200 + step)
                metrics.append(call_metrics)
                self._event("Worker", f"{request['kind']} requested", action_id=action_id, model=call_metrics["model"], metrics=call_metrics)
                feedback = self._execute_tool(task_id, step, worktree, request, allowed_paths)
                history.append({"request": {key: value for key, value in request.items() if key != "content"}, "feedback": feedback})
                if request["kind"] == "finish":
                    break
            else:
                raise RuntimeError("local worker exhausted tool-step budget")
            _git(worktree, "add", "-N", ".")
            touched = [line for line in _git(worktree, "diff", "--name-only").stdout.splitlines() if line]
            if not touched:
                raise RuntimeError("worker finished without a repository change")
            if allowed_paths and any(path not in allowed_paths for path in touched):
                raise RuntimeError(f"worker changed path outside task scope: {touched}")
            diff = _git(worktree, "diff", "--binary", "--no-ext-diff").stdout
            diff_path = self.artifact_root / task_id / "candidate.diff"
            diff_path.parent.mkdir(parents=True, exist_ok=True)
            diff_path.write_text(diff, encoding="utf-8", newline="\n")
            tests = self._verify_candidate(task_id, worktree, touched)
            review = self._review(task_id, objective, diff, tests, metrics)
            if review["verdict"] != "accept":
                raise RuntimeError("independent reviewer rejected candidate: " + "; ".join(review.get("defects", [])))
            self._integrate(task_id, parent_head, worktree, touched)
            integrated = True
            active_tests = self._verify_candidate(task_id + ":active", self.repo_root, touched)
            commit_sha = push_result = None
            if commit_requested or push_requested:
                _git(self.repo_root, "add", "--", *touched)
                message = "SToE Coder: " + re.sub(r"\s+", " ", objective).strip()[:68]
                _git(self.repo_root, "commit", "-m", message)
                commit_sha = _git(self.repo_root, "rev-parse", "HEAD").stdout.strip()
                self._event("Git", f"commit {commit_sha[:12]}", commit=commit_sha)
            if push_requested:
                branch = _git(self.repo_root, "branch", "--show-current").stdout.strip()
                push = self._runner.run(action_id=f"{task_id}:push", command=["git", "push", "origin", branch], cwd=self.repo_root, timeout=300)
                if push.exit_code:
                    raise RuntimeError("authenticated git push failed: " + push.stderr[-500:])
                push_result = "passed"
                self._event("Git", "pushed", branch=branch, commit=commit_sha)
            observer = self._conserve(task_id, objective, parent_head, touched, tests, commit_sha, push_result, metrics)
            with self._state_lock:
                state = self._load_state(); state["closed_actions"] = list(dict.fromkeys(state.get("closed_actions", []) + [task_id] + [item["action_id"] for item in metrics])); state.update({"status": "completed", "observer": observer, "active_action": None, "tests": "passed", "worker": None, "model": None, "stop_requested": False, "last_result": {"touched": touched, "tests": active_tests, "review": review, "commit": commit_sha, "push": push_result, "metrics": metrics}, "next_action": "operator_intent"}); self._save_state(state)
            self._event("SToE", f"{observer}", observer=observer)
        except InterruptedError as exc:
            if integrated and _git(self.repo_root, "rev-parse", "HEAD").stdout.strip() == parent_head:
                self._rollback(parent_head, touched)
            self._event("Coder", str(exc), level="warning", task_id=task_id)
            with self._state_lock:
                state = self._load_state(); state["closed_actions"] = list(dict.fromkeys(item for item in state.get("closed_actions", []) + [state.get("active_action")] if item)); state.update({"status": "stopped", "last_result": {"error": str(exc)}, "next_action": "resume"}); self._save_state(state)
        except Exception as exc:
            if integrated and _git(self.repo_root, "rev-parse", "HEAD").stdout.strip() == parent_head:
                self._rollback(parent_head, touched)
            self._event("Coder", str(exc), level="error", task_id=task_id)
            with self._state_lock:
                state = self._load_state(); state["closed_actions"] = list(dict.fromkeys(item for item in state.get("closed_actions", []) + [task_id, state.get("active_action")] if item)); state.update({"status": "failed", "last_result": {"error": str(exc), "touched": touched, "metrics": metrics}, "next_action": "diagnose_or_resume"}); self._save_state(state)
        finally:
            if worktree.exists():
                _git(self.repo_root, "worktree", "remove", "--force", str(worktree), timeout=180, check=False)

    def _execute_tool(self, task_id: str, step: int, worktree: Path, request: dict[str, Any], allowed_paths: list[str] | None) -> dict[str, Any]:
        kind = request["kind"]
        path = request.get("path", "")
        if kind in {"inspect", "write", "delete", "move"}:
            target = _safe_repo_path(worktree, path)
            relative = target.relative_to(worktree).as_posix()
            if allowed_paths and relative not in allowed_paths:
                raise PermissionError(f"path outside bounded worker scope: {relative}")
        if kind == "inspect":
            if not target.is_file():
                return {"ok": False, "error": "file not found", "path": relative}
            data = target.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "path": relative, "chars": len(data), "content": data[:16_000], "truncated": len(data) > 16_000}
        if kind == "search":
            base = _safe_repo_path(worktree, path or ".")
            action_id = f"{task_id}:tool:{step}:search"
            result = self._runner.run(action_id=action_id, command=["rg", "-n", "--", request["query"], str(base)], cwd=worktree, timeout=60)
            return result.compact()
        if kind == "write":
            content = request.get("content", "")
            if "\x00" in content or len(content.encode("utf-8")) > 240_000:
                raise ValueError("worker content is binary or oversized")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
            return {"ok": True, "path": relative, "sha256": _sha256(target.read_bytes()), "bytes": target.stat().st_size}
        if kind == "delete":
            if target.is_dir():
                raise ValueError("worker delete accepts ordinary files only")
            if target.exists():
                target.unlink()
            return {"ok": True, "path": relative}
        if kind == "move":
            destination = _safe_repo_path(worktree, request.get("destination", ""))
            destination_relative = destination.relative_to(worktree).as_posix()
            if allowed_paths and destination_relative not in allowed_paths:
                raise PermissionError("move destination outside bounded worker scope")
            destination.parent.mkdir(parents=True, exist_ok=True)
            target.replace(destination)
            return {"ok": True, "from": relative, "to": destination_relative}
        if kind == "run":
            cwd = _safe_repo_path(worktree, request.get("cwd") or ".")
            result = self._runner.run(action_id=f"{task_id}:tool:{step}:run", command=request.get("command") or [], cwd=cwd, timeout=300)
            return result.compact()
        if kind == "finish":
            return {"ok": True, "summary": request.get("summary", "")}
        raise ValueError("unknown worker tool action")

    def _verification_commands(self, touched: list[str]) -> list[list[str]]:
        commands: list[list[str]] = [["git", "diff", "--check"]]
        if any(path.startswith("engine/v7/") for path in touched):
            commands.append([sys.executable, "-m", "unittest", "discover", "-s", "engine/v7/tests", "-q"])
        if any(path.startswith("agent/") for path in touched):
            commands.append([sys.executable, "-m", "unittest", "discover", "-s", "agent/tests", "-q"])
        if any(path.startswith("stoe-hermes/") for path in touched):
            commands.append([sys.executable, "-m", "unittest", "discover", "-s", "stoe-hermes/tests", "-q"])
        return commands

    def _verify_candidate(self, task_id: str, workspace: Path, touched: list[str]) -> list[dict[str, Any]]:
        results = []
        for index, command in enumerate(self._verification_commands(touched), 1):
            env_path = os.pathsep.join([str(workspace / "agent" / "src"), str(workspace / "stoe-hermes" / "src"), str(workspace / "engine" / "v7"), os.environ.get("PYTHONPATH", "")])
            previous = os.environ.get("PYTHONPATH")
            os.environ["PYTHONPATH"] = env_path
            try:
                result = self._runner.run(action_id=f"{task_id}:verify:{index}", command=command, cwd=workspace, timeout=600)
            finally:
                if previous is None:
                    os.environ.pop("PYTHONPATH", None)
                else:
                    os.environ["PYTHONPATH"] = previous
            results.append(result.compact())
            self._event("Tests", "PASS" if result.exit_code == 0 else "FAIL", command=command, exit_code=result.exit_code)
            if result.exit_code or result.timed_out or result.cancelled:
                raise RuntimeError(f"deterministic verification failed: {' '.join(command)}")
        return results

    def _review(self, task_id: str, objective: str, diff: str, tests: list[dict[str, Any]], metrics: list[dict[str, Any]]) -> dict[str, Any]:
        schema = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["accept", "reject"]}, "summary": {"type": "string", "maxLength": 1_200}, "defects": {"type": "array", "items": {"type": "string", "maxLength": 600}, "maxItems": 8}}, "required": ["verdict", "summary", "defects"], "additionalProperties": False}
        action_id = f"{task_id}:reviewer:1"
        result, review_metrics = self.ollama.generate(action_id=action_id, role="reviewer", prompt={"objective": objective, "candidate_diff": diff[:30_000], "diff_truncated": len(diff) > 30_000, "deterministic_tests": [{"command": item["command"], "exit_code": item["exit_code"]} for item in tests], "requirements": ["change implements objective", "no unrelated authority expansion", "tests support acceptance", "no credential material"]}, schema=schema, output_tokens=1_200, seed=9301)
        metrics.append(review_metrics)
        self._event("Reviewer", result["verdict"], model=review_metrics["model"], metrics=review_metrics)
        return result

    def _integrate(self, task_id: str, parent_head: str, candidate_root: Path, touched: list[str]) -> None:
        if _git(self.repo_root, "rev-parse", "HEAD").stdout.strip() != parent_head or _git(self.repo_root, "status", "--porcelain=v1").stdout.strip():
            raise RuntimeError("active repository changed before trusted integration")
        for relative in touched:
            source = _safe_repo_path(candidate_root, relative)
            target = _safe_repo_path(self.repo_root, relative)
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            elif target.is_file():
                target.unlink()
        actual = [line for line in _git(self.repo_root, "diff", "--name-only").stdout.splitlines() if line]
        if sorted(actual) != sorted(touched):
            self._rollback(parent_head, touched)
            raise RuntimeError("integrated path set differs from reviewed candidate")
        self._event("Coder", "reviewed candidate integrated", task_id=task_id, touched=touched)

    def _rollback(self, parent_head: str, touched: list[str]) -> None:
        for path in touched:
            tracked = _git(self.repo_root, "cat-file", "-e", f"{parent_head}:{path}", check=False).returncode == 0
            if tracked:
                _git(self.repo_root, "restore", "--source", parent_head, "--staged", "--worktree", "--", path, check=False)
            else:
                target = _safe_repo_path(self.repo_root, path)
                if target.is_file():
                    target.unlink()

    def _field_store(self) -> Any | None:
        if self._field is not None:
            return self._field
        core = self.repo_root / "plugins" / "stoe-memory" / "core.py"
        if not core.is_file():
            return None
        spec = importlib.util.spec_from_file_location("stoe_coder_memory", core)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
        store = module.FieldStore(); store.initialize(); self._field = store
        return store

    def _conserve(self, task_id: str, objective: str, parent_head: str, touched: list[str], tests: list[dict[str, Any]], commit: str | None, push: str | None, metrics: list[dict[str, Any]]) -> str:
        store = self._field_store()
        if store is None:
            return "STATE_LOCAL_ONLY_" + task_id[-8:]
        session = "development:stoe-coder-v1"
        refs = {name: f"IP_{task_id[5:].lower()}_{name}" for name in ("objective", "worker", "evaluation", "commit", "push", "next")}
        nodes = [
            (refs["objective"], objective, "DevelopmentObjectiveIP", "supported", {"parent_head": parent_head}),
            (refs["worker"], f"Local tool-equipped worker changed {', '.join(touched)}.", "WorkerActionIP", "supported", {"model_actions": [item["action_id"] for item in metrics]}),
            (refs["evaluation"], "Deterministic candidate and active-worktree verification passed; independent reviewer accepted.", "EvaluationIP", "passed", {"tests": len(tests)}),
            (refs["next"], "Accept the next distinct operator intent from the successor observer.", "NextActionIP", "active", {}),
        ]
        if commit:
            nodes.append((refs["commit"], f"SToE Coder created commit {commit}.", "CommitIP", "supported", {"commit": commit}))
        if push:
            nodes.append((refs["push"], f"SToE Coder pushed commit {commit} using inherited local Git authentication.", "PushIP", "supported", {"commit": commit}))
        for ref, content, kind, outcome, metadata in nodes:
            store.add_ip(ref=ref, content=content, kind=kind, origin="evaluation" if kind == "EvaluationIP" else "runtime_reasoning", outcome=outcome, session_id=session, metadata=metadata)
        store.add_relation(source_ref=refs["worker"], target_ref=refs["objective"], relation="generated_by", note="Tool-equipped worker implements objective")
        store.add_relation(source_ref=refs["evaluation"], target_ref=refs["worker"], relation="evaluates", note="Deterministic and independent evaluation")
        predecessor = refs["evaluation"]
        if commit:
            store.add_relation(source_ref=refs["commit"], target_ref=predecessor, relation="depends_on", note="Commit requires passing evaluation"); predecessor = refs["commit"]
        if push:
            store.add_relation(source_ref=refs["push"], target_ref=predecessor, relation="follows", note="Authenticated feature push follows commit"); predecessor = refs["push"]
        store.add_relation(source_ref=refs["next"], target_ref=predecessor, relation="follows", note="Successor observer follows completed task")
        state = store.set_observer_state(goal="Continue SToE Coder development from the verified successor state.", question="What is the next operator intent?", active_constraints=["feature branch", "FULL LOCAL executive", "local workers first", "protected destructive boundary"], changed_constraints=[f"SToE Coder completed {task_id}."], evidence=["deterministic tests passed", "independent reviewer accepted"], open_questions=["next operator intent"], recent_refs=[ref for ref, *_ in nodes], current_reasoning_ref=refs["next"], session_id=session)
        return state["observer_state_ref"]


_runtime: StoeCoderRuntime | None = None


def get_runtime() -> StoeCoderRuntime:
    global _runtime
    if _runtime is None:
        _runtime = StoeCoderRuntime()
    return _runtime
