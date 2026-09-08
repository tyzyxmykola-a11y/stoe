from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .token_budget import TokenBudgetManager, TokenEstimator


ACTION_ID = "self-code-cycle:v2:deduplicate-development-context"
MODEL_NAME = "gemma4:26b"
MODEL_DIGEST = "08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68"
EDITABLE_PATH = "agent/src/stoe_agent/development_report.py"
PARENT_SHA256 = "cd31b0dd4ce7a2c8fdfec4553c02171b2510527fddf251fee901ea5c0279dce7"
FORMAT = "stoe.line_patch"
VERSION = 2
MAX_REPLACEMENT_LINES = 64
MAX_LINE_CHARS = 180
MAX_CANDIDATE_BYTES = 8192
MAX_CANDIDATE_LINES = 100
# NDJSON repeats an event envelope for each streamed token, so this bounds transport
# capture rather than confusing wire bytes with model payload bytes.
MAX_RESPONSE_BYTES = 8_000_000
MAX_CONTEXT = 16_384
CHECKPOINT_RESERVE = 1024
QUALIFICATION_CALL_IDS = (
    "self-code-cycle:v2:format-qualification-1",
    "self-code-cycle:v2:format-qualification-2",
)


class V2BoundaryError(ValueError):
    pass


class DuplicateJSONKeyError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def strict_json_loads(value: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise DuplicateJSONKeyError(f"duplicate JSON field: {key}")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=reject_duplicates)


def analyze_ollama_stream(raw: bytes, *, output_limit_tokens: int) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    stream_errors: list[str] = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = strict_json_loads(line.decode("utf-8", errors="strict"))
            if not isinstance(event, dict):
                raise TypeError("stream event is not an object")
            events.append(event)
        except Exception as exc:
            stream_errors.append(f"line {number}: {type(exc).__name__}: {exc}")
    final = events[-1] if events else {}
    response_text = "".join(str(event.get("response", "")) for event in events)
    response_channel = "response"
    if not response_text:
        response_text = "".join(str(event.get("thinking", "")) for event in events)
        response_channel = "thinking"
    parsed = None
    parser_error = None
    try:
        parsed = strict_json_loads(response_text)
    except Exception as exc:
        parser_error = f"{type(exc).__name__}: {exc}"
    done = bool(final.get("done")) and not stream_errors
    done_reason = str(final.get("done_reason") or ("done" if done else "incomplete"))
    eval_count = final.get("eval_count")
    if stream_errors:
        diagnosis = "STREAM_RECONSTRUCTION_FAILURE"
    elif not done:
        diagnosis = "INTERRUPTED_STREAM"
    elif parser_error and (
        done_reason in {"length", "limit"}
        or (isinstance(eval_count, int) and eval_count >= output_limit_tokens)
    ):
        diagnosis = "OUTPUT_TRUNCATION"
    elif parser_error:
        diagnosis = "SCHEMA_NONCOMPLIANCE"
    else:
        diagnosis = "COMPLETE_STRUCTURED_OUTPUT"
    return {
        "event_count": len(events),
        "stream_errors": stream_errors,
        "stream_complete": done,
        "done_reason": done_reason,
        "response_channel": response_channel,
        "response_chars": len(response_text),
        "response_text": response_text,
        "parsed": parsed,
        "parser_error": parser_error,
        "diagnosis": diagnosis,
        "prompt_tokens": final.get("prompt_eval_count"),
        "output_tokens": eval_count,
        "total_tokens": (
            int(final.get("prompt_eval_count", 0)) + int(eval_count)
            if final.get("prompt_eval_count") is not None and isinstance(eval_count, int)
            else None
        ),
        "provider_total_duration_ns": final.get("total_duration"),
        "provider_load_duration_ns": final.get("load_duration"),
        "provider_prompt_duration_ns": final.get("prompt_eval_duration"),
        "provider_generation_duration_ns": final.get("eval_duration"),
        "output_limit_tokens": output_limit_tokens,
    }


def record_transport_termination(analysis: dict[str, Any], transport_error: str | None) -> None:
    """Attach trusted-transport termination without rewriting captured evidence."""
    analysis["transport_error"] = transport_error
    if transport_error and "raw response exceeded byte limit" in transport_error:
        analysis["diagnosis"] = "RAW_CAPTURE_LIMIT_ABORT"
        analysis["termination_reason"] = "trusted_raw_capture_byte_limit"
    elif transport_error:
        analysis["termination_reason"] = "transport_error"
    else:
        analysis["termination_reason"] = analysis["done_reason"]


class RawOllamaClient:
    def __init__(self, endpoint: str = "http://127.0.0.1:11434", timeout_seconds: int = 900) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _json(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            value = strict_json_loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"Ollama {path} returned a non-object")
        return value

    def capability(self) -> dict[str, Any]:
        version = str(self._json("/api/version").get("version", "unknown"))
        models = self._json("/api/tags").get("models", [])
        match = next((item for item in models if item.get("name") == MODEL_NAME), None)
        if match is None or match.get("digest") != MODEL_DIGEST:
            raise RuntimeError("required gemma4:26b digest is not installed")
        shown = self._json("/api/show", {"model": MODEL_NAME})
        model_info = shown.get("model_info", {})
        context_fields = {
            str(key): int(value)
            for key, value in model_info.items()
            if str(key).endswith(".context_length") and isinstance(value, (int, float))
        } if isinstance(model_info, dict) else {}
        if not context_fields:
            raise RuntimeError("Ollama did not expose context_length")
        return {
            "ollama_version": version,
            "model": MODEL_NAME,
            "digest": MODEL_DIGEST,
            "advertised_context_tokens": max(context_fields.values()),
            "effective_context_tokens": min(MAX_CONTEXT, max(context_fields.values())),
            "context_fields": context_fields,
            "native_structured_output": "JSON schema object supplied in /api/generate format",
        }

    def generate(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        raw_path: Path,
        num_ctx: int,
        num_predict: int,
        seed: int,
    ) -> dict[str, Any]:
        if raw_path.exists():
            raise FileExistsError(f"refusing to overwrite raw response: {raw_path}")
        payload = {
            "model": MODEL_NAME,
            "system": system,
            "prompt": prompt,
            "stream": True,
            "format": schema,
            "options": {
                "temperature": 0,
                "top_p": 0.9,
                "top_k": 40,
                "seed": seed,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
            "keep_alive": "10m",
        }
        request = urllib.request.Request(
            self.endpoint + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        transport_error = None
        with raw_path.open("xb") as raw_handle:
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    while True:
                        line = response.readline()
                        if not line:
                            break
                        raw_handle.write(line)
                        raw_handle.flush()
                        os.fsync(raw_handle.fileno())
                        if raw_handle.tell() > MAX_RESPONSE_BYTES:
                            raise RuntimeError("raw response exceeded byte limit")
            except Exception as exc:
                transport_error = f"{type(exc).__name__}: {exc}"
        raw = raw_path.read_bytes()
        analysis = analyze_ollama_stream(raw, output_limit_tokens=num_predict)
        record_transport_termination(analysis, transport_error)
        analysis.update(
            {
                "wall_duration_seconds": round(time.monotonic() - started, 3),
                "raw_response_path": str(raw_path),
                "raw_response_bytes": len(raw),
                "raw_response_sha256": sha256_bytes(raw),
                "request": {**payload, "prompt": prompt, "system": system},
            }
        )
        return analysis


def patch_schema(parent_sha256: str = PARENT_SHA256) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": [FORMAT]},
            "version": {"type": "integer", "enum": [VERSION]},
            "path": {"type": "string", "enum": [EDITABLE_PATH]},
            "parent_sha256": {"type": "string", "enum": [parent_sha256]},
            "replacement_lines": {
                "type": "array",
                "minItems": 2,
                "maxItems": MAX_REPLACEMENT_LINES,
                "items": {"type": "string", "maxLength": MAX_LINE_CHARS},
            },
            "rationale": {"type": "string", "maxLength": 1200},
            "expected_effect": {"type": "string", "maxLength": 800},
            "risk_notes": {
                "type": "array",
                "maxItems": 6,
                "items": {"type": "string", "maxLength": 300},
            },
        },
        "required": [
            "format", "version", "path", "parent_sha256", "replacement_lines",
            "rationale", "expected_effect", "risk_notes",
        ],
        "additionalProperties": False,
    }


def validate_patch_envelope(value: Any, *, expected_parent: str = PARENT_SHA256) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise V2BoundaryError("patch must be an object")
    required = {
        "format", "version", "path", "parent_sha256", "replacement_lines",
        "rationale", "expected_effect", "risk_notes",
    }
    if set(value) != required:
        raise V2BoundaryError("patch fields are missing or unexpected")
    if value["format"] != FORMAT or value["version"] != VERSION:
        raise V2BoundaryError("unsupported patch format")
    if value["path"] != EDITABLE_PATH or ".." in value["path"] or "\\" in value["path"]:
        raise V2BoundaryError("path is outside exact editable boundary")
    if value["parent_sha256"] != expected_parent:
        raise V2BoundaryError("stale or incorrect parent hash")
    lines = value["replacement_lines"]
    if not isinstance(lines, list) or not 2 <= len(lines) <= MAX_REPLACEMENT_LINES:
        raise V2BoundaryError("replacement line count is invalid")
    if any(not isinstance(line, str) or len(line) > MAX_LINE_CHARS or "\x00" in line for line in lines):
        raise V2BoundaryError("replacement contains oversized, binary, or non-text lines")
    for field, limit in (("rationale", 1200), ("expected_effect", 800)):
        if not isinstance(value[field], str) or not value[field].strip() or len(value[field]) > limit:
            raise V2BoundaryError(f"invalid {field}")
    risks = value["risk_notes"]
    if not isinstance(risks, list) or len(risks) > 6 or any(not isinstance(x, str) or len(x) > 300 for x in risks):
        raise V2BoundaryError("invalid risk notes")
    metadata_text = "\n".join([value["rationale"], value["expected_effect"], *risks])
    if re.search(r"(?i)(?:__\w+__|\b(?:import|exec|eval|open|subprocess|socket)\s*\()", metadata_text):
        raise V2BoundaryError("code or authority request hidden in metadata")
    return value


def reconstruct_candidate(parent: str, patch: dict[str, Any]) -> str:
    validate_patch_envelope(patch, expected_parent=sha256_bytes(parent.encode("utf-8")))
    lines = parent.splitlines()
    function_line = next((index for index, line in enumerate(lines) if line.startswith("def render_retrieved_context(")), None)
    if function_line is None:
        raise V2BoundaryError("trusted parent function was not found")
    candidate = "\n".join(lines[:function_line] + patch["replacement_lines"]) + "\n"
    return candidate


def validate_candidate_source(parent: str, candidate: str) -> dict[str, Any]:
    encoded = candidate.encode("utf-8", errors="strict")
    if len(encoded) > MAX_CANDIDATE_BYTES or len(candidate.splitlines()) > MAX_CANDIDATE_LINES:
        raise V2BoundaryError("candidate exceeds byte or line limit")
    if "\x00" in candidate:
        raise V2BoundaryError("candidate contains NUL/binary data")
    secret_patterns = (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}",
        r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_\-]{20,}\b",
    )
    if any(re.search(pattern, candidate) for pattern in secret_patterns):
        raise V2BoundaryError("candidate resembles secret material")
    try:
        parent_tree = ast.parse(parent)
        tree = ast.parse(candidate)
        compile(tree, EDITABLE_PATH, "exec", dont_inherit=True)
    except (SyntaxError, TypeError, ValueError) as exc:
        raise V2BoundaryError(f"invalid Python candidate: {exc}") from exc
    parent_prefix = [ast.dump(node) for node in parent_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    candidate_prefix = [ast.dump(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if candidate_prefix != parent_prefix:
        raise V2BoundaryError("imports changed")
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    other = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Expr))]
    if len(functions) != 1 or functions[0].name != "render_retrieved_context" or other:
        raise V2BoundaryError("candidate changed module structure")
    if any(
        isinstance(node, ast.Expr)
        and node in tree.body
        and not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))
        for node in ast.walk(tree)
    ):
        raise V2BoundaryError("top-level side effects are forbidden")
    forbidden = (ast.While, ast.AsyncFor, ast.Await, ast.Yield, ast.YieldFrom, ast.Lambda, ast.ClassDef)
    if any(isinstance(node, forbidden) for node in ast.walk(functions[0])):
        raise V2BoundaryError("unbounded/asynchronous/dynamic constructs are forbidden")
    if len(list(ast.walk(functions[0]))) > 600:
        raise V2BoundaryError("candidate operation count exceeds static bound")
    if any(isinstance(node, ast.Name) and node.id.startswith("__") for node in ast.walk(functions[0])):
        raise V2BoundaryError("dunder names are forbidden")
    if any(isinstance(node, ast.Attribute) and node.attr.startswith("__") for node in ast.walk(functions[0])):
        raise V2BoundaryError("dunder traversal is forbidden")
    safe_names = {"str", "len", "set", "dict", "list", "ValueError", "min", "max", "sorted", "sum", "range", "enumerate"}
    safe_methods = {"get", "replace", "append", "add", "join", "setdefault", "items", "values"}
    for node in ast.walk(functions[0]):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in safe_names:
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr in safe_methods:
            continue
        raise V2BoundaryError("call is outside pure reporting capability allowlist")
    return {
        "passed": True,
        "candidate_sha256": sha256_bytes(encoded),
        "candidate_bytes": len(encoded),
        "candidate_lines": len(candidate.splitlines()),
        "ast_nodes": len(list(ast.walk(functions[0]))),
        "security_note": "Capability whitelist plus bounded JSON inputs; not an OS security sandbox.",
    }


def canonicalize_payloads(instances: list[dict[str, Any]], estimator: TokenEstimator | None = None) -> dict[str, Any]:
    estimator = estimator or TokenEstimator()
    before = json.dumps(instances, ensure_ascii=False, sort_keys=True)
    payloads: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    collapsed = 0
    for instance in instances:
        content = str(instance["content"])
        declared = str(instance.get("payload_sha256") or sha256_bytes(content.encode("utf-8")))
        actual = sha256_bytes(content.encode("utf-8"))
        if declared != actual:
            raise V2BoundaryError("payload SHA does not match canonical content")
        if declared not in seen:
            seen[declared] = content
            payloads.append({"sha256": declared, "content": content, "canonical_path": instance.get("canonical_path")})
        elif seen[declared] != content:
            raise V2BoundaryError("one payload SHA maps to conflicting content")
        else:
            collapsed += 1
        connections.append({
            "payload_sha256": declared,
            "ref": instance.get("ref"),
            "relation": instance.get("relation"),
            "direction": instance.get("direction"),
            "provenance": instance.get("provenance"),
        })
    after_value = {"canonical_payloads": payloads, "connections": connections, "collapsed_payload_copies": collapsed}
    after = json.dumps(after_value, ensure_ascii=False, sort_keys=True)
    return {
        **after_value,
        "tokens_before": estimator.estimate(before),
        "tokens_after": estimator.estimate(after),
        "token_savings": estimator.estimate(before) - estimator.estimate(after),
    }


class BoundedRunner:
    def __init__(self, *, timeout: float = 180, output_bytes: int = 2_000_000, ram_bytes: int = 2_000_000_000, processes: int = 12, disk_growth_bytes: int = 250_000_000) -> None:
        self.timeout = timeout
        self.output_bytes = output_bytes
        self.ram_bytes = ram_bytes
        self.processes = processes
        self.disk_growth_bytes = disk_growth_bytes

    @staticmethod
    def _size(root: Path) -> int:
        return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())

    def run(self, command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("psutil is required for bounded candidate evaluation") from exc
        stdout_path = cwd / f".bounded_stdout_{os.getpid()}.tmp"
        stderr_path = cwd / f".bounded_stderr_{os.getpid()}.tmp"
        baseline_disk = self._size(cwd)
        started = time.monotonic()
        violation = None
        with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err)
            root = psutil.Process(process.pid)
            peak_ram = 0
            peak_processes = 1
            while process.poll() is None:
                try:
                    descendants = root.children(recursive=True)
                    family = [root, *descendants]
                    peak_processes = max(peak_processes, len(family))
                    rss = sum(item.memory_info().rss for item in family if item.is_running())
                    peak_ram = max(peak_ram, rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    family = []
                if time.monotonic() - started > self.timeout:
                    violation = "timeout"
                elif stdout_path.stat().st_size + stderr_path.stat().st_size > self.output_bytes:
                    violation = "output"
                elif peak_ram > self.ram_bytes:
                    violation = "ram"
                elif peak_processes > self.processes:
                    violation = "process_count"
                elif self._size(cwd) - baseline_disk > self.disk_growth_bytes:
                    violation = "disk_growth"
                if violation:
                    for child in reversed(family):
                        try:
                            child.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    process.kill()
                    break
                time.sleep(0.05)
            exit_code = process.wait(timeout=10)
        stdout = stdout_path.read_bytes()[: self.output_bytes]
        stderr = stderr_path.read_bytes()[: self.output_bytes]
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)
        return {
            "command": command,
            "exit_code": exit_code,
            "passed": exit_code == 0 and violation is None,
            "violation": violation,
            "duration_seconds": round(time.monotonic() - started, 3),
            "peak_ram_bytes": peak_ram,
            "peak_process_count": peak_processes,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "limits": {
                "timeout_seconds": self.timeout,
                "output_bytes": self.output_bytes,
                "ram_bytes": self.ram_bytes,
                "processes": self.processes,
                "disk_growth_bytes": self.disk_growth_bytes,
            },
        }


def copy_candidate_workspace(repo_root: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)

    def ignore(path: str, names: list[str]) -> set[str]:
        ignored = {".git", "__pycache__", ".pytest_cache"} & set(names)
        if Path(path).name.startswith("runtime"):
            ignored.update(names)
        return ignored

    shutil.copytree(repo_root, destination, ignore=ignore)


class SelfCodeCycleV2:
    def __init__(self, *, repo_root: Path, endpoint: str = "http://127.0.0.1:11434") -> None:
        self.repo_root = repo_root.resolve()
        self.runtime = self.repo_root / "agent" / "runtime" / "self_code_cycle_v2"
        self.evidence = self.repo_root / "agent" / "self_code_candidates" / "self_code_cycle_v2_deduplicate_context"
        self.state_path = self.runtime / "state.json"
        self.client = RawOllamaClient(endpoint)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.evidence.mkdir(parents=True, exist_ok=True)

    def _state(self) -> dict[str, Any]:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"action_id": ACTION_ID, "calls": {}, "status": "new", "created_at": utc_now()}

    def _save(self, state: dict[str, Any]) -> None:
        atomic_json(self.state_path, state)

    def _call(self, *, call_id: str, system: str, prompt: str, schema: dict[str, Any], num_predict: int, seed: int, capability: dict[str, Any]) -> dict[str, Any]:
        state = self._state()
        prior = state["calls"].get(call_id)
        if prior:
            if prior["status"] == "completed":
                return prior["result"]
            raise RuntimeError(f"call {call_id} was interrupted or failed and cannot be repeated")
        raw_path = self.evidence / "raw" / (re.sub(r"[^a-zA-Z0-9_.-]", "_", call_id) + ".ndjson")
        state["calls"][call_id] = {"status": "started", "raw_path": str(raw_path), "started_at": utc_now()}
        self._save(state)
        result = self.client.generate(
            system=system,
            prompt=prompt,
            schema=schema,
            raw_path=raw_path,
            num_ctx=capability["effective_context_tokens"],
            num_predict=num_predict,
            seed=seed,
        )
        state = self._state()
        status = "completed" if result["diagnosis"] == "COMPLETE_STRUCTURED_OUTPUT" else "failed"
        state["calls"][call_id] = {"status": status, "result": result, "completed_at": utc_now()}
        self._save(state)
        return result

    def qualify(self, capability: dict[str, Any]) -> dict[str, Any]:
        examples = [
            ["def render_retrieved_context(items, max_chars):", "    return \"\""],
            [
                "def render_retrieved_context(items, max_chars):",
                "    lines = []",
                "    for item in items:",
                "        lines.append(str(item.get(\"ref\", \"unknown\")))",
                "    return \"\\n\".join(lines)[:max_chars]",
            ],
        ]
        outcomes = []
        for index, expected in enumerate(examples):
            prompt = (
                "Disclosed formatting qualification only. Return the stoe.line_patch JSON object. "
                "Copy these replacement_lines exactly and use concise ordinary prose metadata:\n"
                + json.dumps(expected, ensure_ascii=False)
            )
            result = self._call(
                call_id=QUALIFICATION_CALL_IDS[index],
                system="Return only schema-conforming inert JSON. Do not use markdown or extra prose.",
                prompt=prompt,
                schema=patch_schema(),
                num_predict=1400,
                seed=920_100 + index,
                capability=capability,
            )
            passed = False
            error = None
            try:
                patch = validate_patch_envelope(result["parsed"])
                passed = result["diagnosis"] == "COMPLETE_STRUCTURED_OUTPUT" and patch["replacement_lines"] == expected
                if not passed:
                    error = "schema parsed but exact disclosed replacement_lines were not followed"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            outcomes.append({"call_id": QUALIFICATION_CALL_IDS[index], "passed": passed, "error": error, "raw_sha256": result["raw_response_sha256"], "diagnosis": result["diagnosis"], "tokens": {"prompt": result["prompt_tokens"], "output": result["output_tokens"]}})
            if not passed:
                break
        return {"passed": len(outcomes) == 2 and all(item["passed"] for item in outcomes), "outcomes": outcomes, "call_budget": 2, "calls_used": len(outcomes)}

    def _prompt_context(self) -> dict[str, Any]:
        field = json.loads((self.repo_root / "agent" / "self_code_v2" / "field_retrieval.json").read_text(encoding="utf-8"))
        selected = {item["ref"]: item for item in field["selected"]}
        instances = []
        for item in field["selected"]:
            content = item["content"]
            instances.append({"ref": item["ref"], "relation": "selected_by", "direction": "outgoing", "provenance": item["origin"], "content": content, "payload_sha256": sha256_bytes(content.encode("utf-8")), "canonical_path": item.get("artifact_path")})
        for path in field["typed_paths"]:
            target = path[-1]
            if target in selected:
                item = selected[target]
                content = item["content"]
                instances.append({"ref": target, "relation": path[1].split(":")[0], "direction": path[1].split(":")[1], "provenance": "typed_path:" + "->".join(path), "content": content, "payload_sha256": sha256_bytes(content.encode("utf-8")), "canonical_path": item.get("artifact_path")})
        return {"field": field, "canonicalized": canonicalize_payloads(instances)}

    def run(self, *, allow_generation: bool) -> dict[str, Any]:
        state = self._state()
        if state.get("status") in {"candidate_preserved", "failed_preserved"}:
            return {"decision": "SKIP_CLOSED_ACTION", "state": state}
        parent_path = self.repo_root / EDITABLE_PATH
        if sha256_file(parent_path) != PARENT_SHA256:
            raise RuntimeError("reporting parent hash changed; v2 is not applicable")
        capability = self.client.capability()
        context = self._prompt_context()
        parent = parent_path.read_text(encoding="utf-8")
        numbered_parent = "\n".join(f"{number:03d}: {line}" for number, line in enumerate(parent.splitlines(), 1))
        objective = (
            "Replace render_retrieved_context so identical non-empty sha256 payloads are printed once, but every input record's "
            "ref/origin/kind/outcome/path remains visible as a separate connection. Start output with "
            "'[dedup] collapsed_payload_copies=N'. Records lacking sha256 remain distinct. Preserve input order, do not mutate inputs, "
            "raise ValueError for negative max_chars, and never exceed max_chars."
        )
        prompt_payload = {
            "objective": objective,
            "field_context": context["canonicalized"],
            "field_trace_reference": {
                "observer_state_ref": context["field"]["observer_state_ref"],
                "retrieval_run_id": context["field"]["retrieval_run_id"],
                "typed_paths": context["field"]["typed_paths"],
            },
            "parent_source_numbered": numbered_parent,
            "fixed_splice": "replacement_lines replaces from def render_retrieved_context through EOF; imports are immutable",
            "required_output_examples": [
                "[dedup] collapsed_payload_copies=1",
                "PAYLOAD | <sha256-or-unhashed-identity> | <content once>",
                "CONNECTION | <ref> | <origin> | <kind> | <outcome> | <path>",
            ],
            "validation": {
                "max_candidate_bytes": MAX_CANDIDATE_BYTES,
                "max_candidate_lines": MAX_CANDIDATE_LINES,
                "no_import_changes": True,
                "pure_call_allowlist": ["str", "len", "set", "dict", "list", "min", "max", "sorted", "sum", "range", "enumerate", "get", "replace", "append", "add", "join", "setdefault", "items", "values"],
                "forbidden": ["filesystem", "environment", "network", "processes", "dependencies", "secrets", "dunders", "while", "async", "top-level effects"],
            },
            "connection_conservation_contract": {
                "payload_identity": "A non-empty sha256 identifies canonical byte content only; it does not identify or merge Information Points.",
                "required_per_input_record": ["ref", "origin", "kind", "outcome", "path"],
                "duplicate_payload_rule": "Print content once, then print one CONNECTION record for every original input record in original order.",
                "unhashed_rule": "Treat every record lacking a non-empty sha256 as a distinct payload even when its content text matches.",
                "budget_rule": "Build deterministic logical lines first, then include only complete lines that fit max_chars; header must also fit or return an empty string.",
                "observability": "The first included line reports collapsed_payload_copies as input payload copies minus canonical printed payloads.",
            },
            "focused_test_contract": {
                "duplicate_fixture": "Two refs share one hash and content: content occurs once, both refs and both paths remain visible, collapsed count is one.",
                "unhashed_fixture": "Two un-hashed refs share text: text occurs twice and collapsed count does not increase.",
                "immutability": "Deep comparison of items before and after the call is equal.",
                "bounds": "Output never exceeds max_chars and a negative budget raises ValueError.",
                "activation": "Passing creates only an inactive candidate; no source pointer or active release changes.",
            },
        }
        system = (
            "Return only one schema-conforming inert stoe.line_patch JSON object. replacement_lines must contain the complete Python "
            "function and no imports or markdown. You propose source; do not claim execution, tests, activation, or SToE superiority."
        )
        prompt = json.dumps(prompt_payload, indent=2, ensure_ascii=False, sort_keys=True)
        estimator = TokenEstimator()
        output_reserve = estimator.estimate("x" * (MAX_CANDIDATE_BYTES * 2)) + 256
        manager = TokenBudgetManager(context_limit_tokens=capability["effective_context_tokens"], checkpoint_reserve_tokens=CHECKPOINT_RESERVE, estimator=estimator)
        budget = manager.require_plan(system=system, prompt=prompt, reserved_generation_tokens=output_reserve, categories={"task_context": json.dumps({"objective": objective, "validation": prompt_payload["validation"]}), "retrieved_material": json.dumps(context["canonicalized"]), "tool_results": numbered_parent})
        input_tokens = budget["estimated"]["system_instructions"] + budget["estimated"]["prompt_total"]
        if not 3800 <= input_tokens <= 6500:
            raise RuntimeError(f"main input context is outside compact engineering range: {input_tokens}")
        preflight = {"capability": capability, "context_deduplication": context["canonicalized"], "budget": budget, "input_tokens": input_tokens, "output_reserve_tokens": output_reserve}
        atomic_json(self.evidence / "preflight.json", preflight)
        if not allow_generation:
            return {"decision": "READY_NO_GENERATION", **preflight}
        qualification = self.qualify(capability)
        atomic_json(self.evidence / "qualification.json", qualification)
        if not qualification["passed"]:
            state = self._state()
            state.update({"status": "failed_preserved", "failure": "formatting qualification failed", "qualification": qualification})
            self._save(state)
            return {"decision": "FORMAT_QUALIFICATION_FAILED_NO_REAL_ATTEMPT", "qualification": qualification, **preflight}
        result = self._call(call_id=ACTION_ID, system=system, prompt=prompt, schema=patch_schema(), num_predict=output_reserve, seed=920_241, capability=capability)
        if result["diagnosis"] != "COMPLETE_STRUCTURED_OUTPUT":
            state = self._state()
            state.update({"status": "failed_preserved", "failure": result})
            self._save(state)
            return {"decision": "REAL_GENERATION_FAILED", "model_result": result, "qualification": qualification, **preflight}
        try:
            patch = validate_patch_envelope(result["parsed"])
            candidate = reconstruct_candidate(parent, patch)
            validation = validate_candidate_source(parent, candidate)
        except Exception as exc:
            failure = {
                "decision": "REAL_PATCH_VALIDATION_FAILED",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "raw_response_sha256": result["raw_response_sha256"],
                "raw_path": result["raw_path"],
                "model_diagnosis": result["diagnosis"],
            }
            atomic_json(self.evidence / "validation_failure.json", failure)
            state = self._state()
            state.update({"status": "failed_preserved", "failure": failure})
            self._save(state)
            return {
                **failure,
                "qualification": qualification,
                "model_result": result,
                **preflight,
            }
        canonical = {"format": "stoe.validated_source_candidate", "version": 1, "action_id": ACTION_ID, "model_patch": patch, "parent_sha256": PARENT_SHA256, "candidate_sha256": validation["candidate_sha256"], "candidate_bytes": validation["candidate_bytes"], "candidate_lines": validation["candidate_lines"]}
        workspace = self.runtime / "candidate_workspace"
        copy_candidate_workspace(self.repo_root, workspace)
        isolated_target = workspace / EDITABLE_PATH
        isolated_target.write_text(candidate, encoding="utf-8", newline="\n")
        if sha256_file(isolated_target) != canonical["candidate_sha256"]:
            raise RuntimeError("candidate SHA mismatch after isolated write")
        runner = BoundedRunner()
        env = dict(os.environ)
        tests = []
        commands = [
            ([sys.executable, "agent/tools/check_report_candidate.py"], workspace),
            ([sys.executable, "-m", "compileall", "-q", "agent/src/stoe_agent"], workspace),
            ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], workspace / "agent"),
            ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], workspace / "experiments" / "stoe_v9_1_experiment"),
            ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], workspace / "experiments" / "stoe_v3"),
            ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], workspace / "plugins" / "stoe-memory"),
        ]
        for index, (command, cwd) in enumerate(commands):
            call_env = dict(env)
            if cwd.name in {"agent", "stoe_v9_1_experiment"}:
                call_env["PYTHONPATH"] = str(cwd / "src")
            test = runner.run(command, cwd=cwd, env=call_env)
            test["test_id"] = ["focused", "compile", "agent", "v9_1", "v3", "memory_plugin"][index]
            tests.append(test)
            if not test["passed"]:
                break
        decision = "VALID_INACTIVE_CANDIDATE" if len(tests) == len(commands) and all(test["passed"] for test in tests) else "CANDIDATE_REJECTED_BY_EVALUATION"
        atomic_json(self.evidence / "candidate.json", canonical)
        (self.evidence / "candidate_development_report.py").write_text(candidate, encoding="utf-8", newline="\n")
        atomic_json(self.evidence / "evaluation.json", {"decision": decision, "validation": validation, "tests": tests, "isolation": {"workspace": str(workspace), "active_source_changed": False, "security_boundary": "AST capability whitelist plus monitored process tree; isolated directory is not an OS sandbox"}})
        state = self._state()
        state.update({"status": "candidate_preserved" if decision == "VALID_INACTIVE_CANDIDATE" else "failed_preserved", "decision": decision, "candidate_sha256": validation["candidate_sha256"]})
        self._save(state)
        return {"decision": decision, "candidate": canonical, "validation": validation, "tests": tests, "model_result": result, "qualification": qualification, **preflight, "activation": "INACTIVE_PENDING_MYKOLA_APPROVAL"}
