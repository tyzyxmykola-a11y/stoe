from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import venv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


INTEGRATION_VERSION = "0.1.0"
EDITABLE_PATH = "stoe-hermes/src/stoe_hermes/context_renderer.py"
RELEASE_STATES = {"active", "candidate", "rejected", "approved", "superseded", "rolled_back", "divergent"}
PROTECTED_MARKERS = (
    ".git/", ".env", "credential", "secret", "activation", "supervisor", "succession.py",
    "protected_eval", "research_checkpoints", "research_state", "config.yaml", "pyproject.toml",
    "requirements", "uv.lock", "package-lock", "hermes-agent/",
)
MAX_PATCH_LINES = 80
MAX_LINE_CHARS = 200
MAX_CANDIDATE_BYTES = 12_000
FORBIDDEN_AST_TYPES = (
    ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef, ast.Lambda,
    ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Raise, ast.Global, ast.Nonlocal,
)


class SuccessionError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _run(command: list[str], *, cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, check=False)


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = _run(["git", *args], cwd=repo)
    if check and result.returncode:
        raise SuccessionError(f"git {' '.join(args)} failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def inspect_checkout(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain=v1", "--branch")
    porcelain = [line for line in status.splitlines() if not line.startswith("##")]
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
    upstream_sha = _git(repo, "rev-parse", "@{u}", check=False) if upstream else ""
    relation = "untracked"
    ahead = behind = None
    if upstream_sha:
        counts = _git(repo, "rev-list", "--left-right", "--count", f"{head}...{upstream_sha}").split()
        if len(counts) == 2:
            ahead, behind = int(counts[0]), int(counts[1])
            relation = "equal" if (ahead, behind) == (0, 0) else "divergent" if ahead and behind else "ahead" if ahead else "behind"
    diff = _run(["git", "diff", "--binary", "HEAD"], cwd=repo)
    return {
        "path": str(repo),
        "head_sha": head,
        "clean": not porcelain,
        "status_lines": porcelain,
        "working_diff_sha256": sha256_bytes(diff.stdout.encode("utf-8")),
        "upstream": upstream,
        "upstream_sha": upstream_sha,
        "ahead": ahead,
        "behind": behind,
        "upstream_relation": relation,
    }


def verify_clean_parent(repo: Path, pinned_sha: str) -> dict[str, Any]:
    inspected = inspect_checkout(repo)
    if inspected["head_sha"] != pinned_sha:
        raise SuccessionError("stale parent: checkout HEAD does not match pinned SHA")
    if not inspected["clean"]:
        raise SuccessionError("dirty parent: candidate ancestry is not reproducible")
    if inspected["upstream_relation"] == "divergent":
        raise SuccessionError("divergent parent: upstream ancestry has split")
    return inspected


def materialize_commit(source_repo: Path, pinned_sha: str, destination: Path) -> dict[str, Any]:
    """Materialize a committed source object without copying working-tree changes."""
    if destination.exists():
        raise SuccessionError("candidate checkout destination already exists")
    source = inspect_checkout(source_repo)
    if source["head_sha"] != pinned_sha:
        raise SuccessionError("pinned commit is not active source HEAD")
    exists = _run(["git", "cat-file", "-e", f"{pinned_sha}^{{commit}}"], cwd=source_repo)
    if exists.returncode:
        raise SuccessionError("pinned commit object is unavailable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    cloned = _run(["git", "clone", "--no-hardlinks", "--no-checkout", str(source_repo.resolve()), str(destination.resolve())], cwd=destination.parent, timeout=120)
    if cloned.returncode:
        raise SuccessionError(f"candidate clone failed: {cloned.stderr.strip()[:500]}")
    checkout = _run(["git", "checkout", "--detach", pinned_sha], cwd=destination)
    if checkout.returncode:
        raise SuccessionError(f"candidate checkout failed: {checkout.stderr.strip()[:500]}")
    candidate = inspect_checkout(destination)
    if candidate["head_sha"] != pinned_sha or not candidate["clean"]:
        raise SuccessionError("materialized candidate does not match clean pinned commit")
    return {
        "candidate_checkout": candidate,
        "source_checkout": source,
        "activation_blockers": (["active_source_dirty"] if not source["clean"] else [])
        + (["active_source_divergent"] if source["upstream_relation"] == "divergent" else []),
    }


def create_isolated_profile(profile_root: Path, *, candidate_cwd: Path, python_command: str, mcp_server: Path, skill_dir: Path) -> dict[str, Any]:
    profile_root = profile_root.resolve()
    if profile_root.exists():
        raise SuccessionError("candidate profile already exists")
    for name in ("sessions", "memories", "logs", "tmp", "plugins", "home"):
        (profile_root / name).mkdir(parents=True, exist_ok=True)
    memory_db = profile_root / "memory" / "field.sqlite3"
    memory_db.parent.mkdir(parents=True)
    config = (
        "model:\n  default: gemma4:26b\n  provider: custom\n"
        "agent:\n  reasoning_effort: medium\n"
        "terminal:\n  backend: local\n  home_mode: profile\n  cwd: " + json.dumps(str(candidate_cwd.resolve())) + "\n"
        "context:\n  engine: compressor\n"
        "memory:\n  provider: ''\n"
        "gateway:\n  enabled: false\n"
        "plugins:\n  enabled: [stoe-hermes]\n  entries:\n    stoe-hermes:\n      mcp_allowlist: [stoe_memory]\n"
        "mcp_servers:\n  stoe_memory:\n    command: " + json.dumps(python_command) + "\n"
        "    args: [" + json.dumps(str(mcp_server.resolve())) + "]\n"
        "    env:\n      STOE_MEMORY_DB: " + json.dumps(str(memory_db)) + "\n"
    )
    (profile_root / "config.yaml").write_text(config, encoding="utf-8", newline="\n")
    (profile_root / "SOUL.md").write_text("Candidate Hermes B. No production messaging or credentials.\n", encoding="utf-8", newline="\n")
    if (profile_root / ".env").exists() or (profile_root / "auth.json").exists():
        raise SuccessionError("candidate profile inherited credentials")
    return {
        "profile_root": str(profile_root),
        "config_sha256": sha256_file(profile_root / "config.yaml"),
        "memory_db": str(memory_db),
        "skill_source": str(skill_dir.resolve()),
        "credentials_present": False,
        "gateway_enabled": False,
    }


def expose_integration_plugin(profile_root: Path, integration_root: Path) -> dict[str, Any]:
    """Copy only the integration-owned Hermes loader; canonical code stays external."""
    source = integration_root.resolve() / "hermes_plugin"
    target = profile_root.resolve() / "plugins" / "stoe-hermes"
    if not (source / "plugin.yaml").is_file() or not (source / "__init__.py").is_file():
        raise SuccessionError("integration plugin loader is incomplete")
    if target.exists():
        raise SuccessionError("candidate plugin loader already exposed")
    shutil.copytree(source, target)
    return {
        "loader_path": str(target),
        "manifest_sha256": sha256_file(target / "plugin.yaml"),
        "loader_sha256": sha256_file(target / "__init__.py"),
        "canonical_package_path": str((integration_root.resolve() / "src").resolve()),
    }


def create_isolated_venv(environment_root: Path) -> dict[str, Any]:
    if environment_root.exists():
        raise SuccessionError("candidate environment already exists")
    venv.EnvBuilder(with_pip=False, clear=False, symlinks=False).create(environment_root)
    python_path = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return {"environment_root": str(environment_root.resolve()), "python": str(python_path.resolve()), "python_sha256": sha256_file(python_path)}


def sanitized_candidate_environment(profile_root: Path, venv_root: Path) -> dict[str, str]:
    scripts = venv_root / ("Scripts" if os.name == "nt" else "bin")
    result = {
        "HERMES_HOME": str(profile_root.resolve()),
        "HOME": str((profile_root / "home").resolve()),
        "PYTHONNOUSERSITE": "1",
        "PATH": str(scripts.resolve()),
        "TEMP": str((profile_root / "tmp").resolve()),
        "TMP": str((profile_root / "tmp").resolve()),
    }
    for key in ("SystemRoot", "COMSPEC", "WINDIR"):
        if os.environ.get(key):
            result[key] = os.environ[key]
    return result


def patch_schema(path: str, parent_sha256: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": ["stoe.line_patch"]},
            "version": {"type": "integer", "enum": [3]},
            "path": {"type": "string", "enum": [path]},
            "parent_sha256": {"type": "string", "enum": [parent_sha256]},
            "replacement_lines": {"type": "array", "minItems": 2, "maxItems": MAX_PATCH_LINES, "items": {"type": "string", "maxLength": MAX_LINE_CHARS}},
        },
        "required": ["format", "version", "path", "parent_sha256", "replacement_lines"],
        "additionalProperties": False,
    }


def validate_patch_envelope(value: Any, *, parent_sha256: str, path: str = EDITABLE_PATH) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"format", "version", "path", "parent_sha256", "replacement_lines"}:
        raise SuccessionError("patch fields are missing or unexpected")
    if value["format"] != "stoe.line_patch" or value["version"] != 3:
        raise SuccessionError("unsupported inert patch format")
    candidate_path = str(value["path"]).replace("\\", "/")
    if candidate_path != path or candidate_path.startswith("/") or ".." in Path(candidate_path).parts:
        raise SuccessionError("patch path is outside the single-file allowlist")
    if any(marker in candidate_path.lower() for marker in PROTECTED_MARKERS):
        raise SuccessionError("patch path is protected")
    if value["parent_sha256"] != parent_sha256:
        raise SuccessionError("stale parent hash")
    lines = value["replacement_lines"]
    if not isinstance(lines, list) or not 2 <= len(lines) <= MAX_PATCH_LINES:
        raise SuccessionError("replacement line count is out of bounds")
    if any(not isinstance(line, str) or len(line) > MAX_LINE_CHARS or "\x00" in line for line in lines):
        raise SuccessionError("replacement line is non-text or oversized")
    return value


def reconstruct_candidate(parent: str, patch: dict[str, Any]) -> str:
    lines = parent.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("def render_retrieved_context(")), None)
    if start is None:
        raise SuccessionError("editable function not found")
    candidate = "\n".join(lines[:start] + patch["replacement_lines"]) + "\n"
    if len(candidate.encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise SuccessionError("candidate source is oversized")
    return candidate


def _walk_structural_paths(node: ast.AST, path: tuple[tuple[str, int | None], ...] = ()) -> list[tuple[ast.AST, tuple[tuple[str, int | None], ...]]]:
    result = [(node, path)]
    for field_name, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            result.extend(_walk_structural_paths(value, (*path, (field_name, None))))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, ast.AST):
                    result.extend(_walk_structural_paths(child, (*path, (field_name, index))))
    return result


def _forbidden_occurrences(function: ast.FunctionDef) -> list[dict[str, Any]]:
    """Fingerprint forbidden nodes with their normalized semantic prefix.

    The prefix ends at the top-level statement containing the node. This binds
    the occurrence to all earlier function state and its exact control-flow
    position without depending on source lines or unrelated later changes.
    """
    signature = {
        "name": function.name,
        "args": ast.dump(function.args, include_attributes=False),
        "decorators": [ast.dump(item, include_attributes=False) for item in function.decorator_list],
        "returns": ast.dump(function.returns, include_attributes=False) if function.returns else None,
    }
    occurrences: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    for statement_index, statement in enumerate(function.body):
        prefix = [ast.dump(item, include_attributes=False) for item in function.body[: statement_index + 1]]
        for node, local_path in _walk_structural_paths(statement, (("body", statement_index),)):
            if not isinstance(node, FORBIDDEN_AST_TYPES):
                continue
            node_type = type(node).__name__
            type_counts[node_type] = type_counts.get(node_type, 0) + 1
            material = {
                "function": signature,
                "prefix": prefix,
                "path": [[field, index] for field, index in local_path],
                "node_type": node_type,
            }
            encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            occurrences.append({
                "node": node,
                "node_type": node_type,
                "occurrence": type_counts[node_type],
                "structural_path": material["path"],
                "fingerprint": sha256_bytes(encoded),
            })
    return occurrences


def _is_within(node: ast.AST, roots: set[int], parents: dict[int, ast.AST]) -> bool:
    current: ast.AST | None = node
    while current is not None:
        if id(current) in roots:
            return True
        current = parents.get(id(current))
    return False


def validate_candidate_source(parent: str, candidate: str) -> dict[str, Any]:
    """Legacy v2.1 validator retained for historical action replay."""
    if "\x00" in candidate:
        raise SuccessionError("candidate contains binary NUL data")
    secret_patterns = (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}",
        r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_\-]{20,}\b",
    )
    if any(re.search(pattern, candidate) for pattern in secret_patterns):
        raise SuccessionError("candidate resembles secret material")
    try:
        parent_tree = ast.parse(parent)
        tree = ast.parse(candidate)
    except SyntaxError as exc:
        raise SuccessionError(f"candidate syntax error: {exc}") from exc
    parent_imports = [ast.dump(node) for node in parent_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    imports = [ast.dump(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if imports != parent_imports:
        raise SuccessionError("candidate changed imports")
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "render_retrieved_context":
        raise SuccessionError("candidate must define only the editable function")
    if len(list(ast.walk(tree))) > 500:
        raise SuccessionError("candidate AST is over-complex")
    allowed_calls = {"str", "len", "min", "max", "range", "enumerate", "sorted", "set", "dict", "list"}
    allowed_methods = {
        "get", "append", "add", "join", "setdefault", "items", "values", "replace",
        "encode", "hexdigest", "sha256",
    }
    for node in ast.walk(functions[0]):
        if isinstance(node, FORBIDDEN_AST_TYPES):
            raise SuccessionError(f"candidate uses forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("__") or node.attr not in allowed_methods):
            raise SuccessionError("candidate attribute is outside capability allowlist")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id not in allowed_calls:
                raise SuccessionError("candidate call is outside capability allowlist")
            if not isinstance(node.func, (ast.Name, ast.Attribute)):
                raise SuccessionError("candidate uses indirect call")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise SuccessionError("candidate uses dunder authority")
    digest = sha256_bytes(candidate.encode("utf-8"))
    if candidate == parent:
        raise SuccessionError("candidate is a no-op")
    return {"candidate_sha256": digest, "bytes": len(candidate.encode("utf-8")), "lines": len(candidate.splitlines())}


def validate_candidate_source_v2_2(parent: str, candidate: str) -> dict[str, Any]:
    if "\x00" in candidate:
        raise SuccessionError("candidate contains binary NUL data")
    secret_patterns = (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}",
        r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_\-]{20,}\b",
    )
    if any(re.search(pattern, candidate) for pattern in secret_patterns):
        raise SuccessionError("candidate resembles secret material")
    try:
        parent_tree = ast.parse(parent)
        tree = ast.parse(candidate)
    except SyntaxError as exc:
        raise SuccessionError(f"candidate syntax error: {exc}") from exc
    parent_imports = [ast.dump(node) for node in parent_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    imports = [ast.dump(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if imports != parent_imports:
        raise SuccessionError("candidate changed imports")
    parent_functions = [node for node in parent_tree.body if isinstance(node, ast.FunctionDef)]
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(parent_functions) != 1 or parent_functions[0].name != "render_retrieved_context":
        raise SuccessionError("trusted parent editable function is invalid")
    if len(functions) != 1 or functions[0].name != "render_retrieved_context":
        raise SuccessionError("candidate must define only the editable function")
    if len(list(ast.walk(tree))) > 500:
        raise SuccessionError("candidate AST is over-complex")
    parent_occurrences: dict[str, list[dict[str, Any]]] = {}
    for occurrence in _forbidden_occurrences(parent_functions[0]):
        parent_occurrences.setdefault(occurrence["fingerprint"], []).append(occurrence)
    grandfathered: list[dict[str, Any]] = []
    matched_roots: set[int] = set()
    for candidate_occurrence in _forbidden_occurrences(functions[0]):
        matches = parent_occurrences.get(candidate_occurrence["fingerprint"], [])
        if not matches:
            raise SuccessionError(
                f"candidate introduces or changes forbidden syntax: {candidate_occurrence['node_type']}"
            )
        parent_occurrence = matches.pop(0)
        matched_roots.add(id(candidate_occurrence["node"]))
        grandfathered.append({
            "node_type": candidate_occurrence["node_type"],
            "parent_occurrence": parent_occurrence["occurrence"],
            "candidate_occurrence": candidate_occurrence["occurrence"],
            "structural_path": candidate_occurrence["structural_path"],
            "comparison": "normalized_ast_prefix_and_structural_path",
            "fingerprint": candidate_occurrence["fingerprint"],
        })
    allowed_calls = {"str", "len", "min", "max", "range", "enumerate", "sorted", "set", "dict", "list"}
    allowed_methods = {
        "get", "append", "add", "join", "setdefault", "items", "values", "replace",
        "encode", "hexdigest", "sha256",
    }
    parents = {id(child): node for node in ast.walk(functions[0]) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(functions[0]):
        if _is_within(node, matched_roots, parents):
            continue
        if isinstance(node, ast.Attribute) and (node.attr.startswith("__") or node.attr not in allowed_methods):
            raise SuccessionError("candidate attribute is outside capability allowlist")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id not in allowed_calls:
                raise SuccessionError("candidate call is outside capability allowlist")
            if not isinstance(node.func, (ast.Name, ast.Attribute)):
                raise SuccessionError("candidate uses indirect call")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise SuccessionError("candidate uses dunder authority")
    digest = sha256_bytes(candidate.encode("utf-8"))
    if candidate == parent:
        raise SuccessionError("candidate is a no-op")
    return {
        "candidate_sha256": digest,
        "bytes": len(candidate.encode("utf-8")),
        "lines": len(candidate.splitlines()),
        "grandfathered_forbidden_nodes": grandfathered,
        "grandfathered_count": len(grandfathered),
    }


@dataclass
class ReleaseRecord:
    release_id: str
    source_repository: str
    commit_sha: str
    parent_release: str | None
    hermes_version: str
    integration_plugin_version: str
    model_configuration: dict[str, Any]
    configuration_hash: str
    environment_fingerprint: str
    test_results: list[dict[str, Any]] = field(default_factory=list)
    candidate_status: str = "candidate"
    activation_status: str = "inactive"
    rollback_target: str | None = None
    creation_action_id: str = ""
    stoe_field_ids: list[str] = field(default_factory=list)
    activation_blockers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        if self.candidate_status not in RELEASE_STATES:
            raise SuccessionError("invalid typed release state")
        return asdict(self)


class SuccessionSupervisor:
    """Protected deterministic authority; integration candidates never import it."""

    def __init__(self, pointer_path: Path) -> None:
        self.pointer_path = pointer_path.resolve()

    def read_pointer(self) -> dict[str, Any]:
        return json.loads(self.pointer_path.read_text(encoding="utf-8"))

    @staticmethod
    def approval_token(candidate: ReleaseRecord) -> str:
        return f"approve:{candidate.release_id}:{candidate.environment_fingerprint}"

    def activate(self, candidate: ReleaseRecord, *, approval: str, requested_by: str, health_check: Callable[[], bool]) -> dict[str, Any]:
        if requested_by != "Mykola Voronin" or approval != self.approval_token(candidate):
            raise SuccessionError("explicit Mykola-bound approval is required")
        if candidate.activation_blockers:
            raise SuccessionError("candidate activation is blocked: " + ",".join(candidate.activation_blockers))
        if candidate.candidate_status != "approved":
            raise SuccessionError("candidate must be typed approved before activation")
        previous = self.read_pointer()
        next_pointer = {"release_id": candidate.release_id, "environment_fingerprint": candidate.environment_fingerprint, "rollback_target": previous["release_id"]}
        atomic_json(self.pointer_path, next_pointer)
        try:
            healthy = bool(health_check())
        except Exception:
            healthy = False
        if not healthy:
            atomic_json(self.pointer_path, previous)
            return {"status": "rolled_back", "rolled_back_to": previous["release_id"]}
        return {"status": "active", "activated_as": candidate.release_id, "rollback_target": previous["release_id"]}


def run_bounded(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 30, output_limit: int = 1_000_000) -> dict[str, Any]:
    """Run a candidate process tree with measured host-level resource bounds.

    This is containment by monitoring under the invoking Windows account, not an
    OS security sandbox. Static candidate validation remains the authority bound.
    """
    try:
        import psutil
    except ImportError as exc:
        raise SuccessionError("psutil is required for bounded candidate execution") from exc
    started = time.monotonic()
    before_disk = sum(path.stat().st_size for path in cwd.rglob("*") if path.is_file())
    stdout_path = cwd / f".stoe_stdout_{os.getpid()}.tmp"
    stderr_path = cwd / f".stoe_stderr_{os.getpid()}.tmp"
    violation = None
    peak_ram = 0
    peak_processes = 1
    limits = {"timeout_seconds": timeout, "output_bytes": output_limit, "ram_bytes": 2_000_000_000, "processes": 12, "disk_growth_bytes": 250_000_000}
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr)
        root = psutil.Process(process.pid)
        family: list[Any] = [root]
        while process.poll() is None:
            try:
                family = [root, *root.children(recursive=True)]
                peak_processes = max(peak_processes, len(family))
                peak_ram = max(peak_ram, sum(proc.memory_info().rss for proc in family if proc.is_running()))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                family = []
            output_bytes = stdout_path.stat().st_size + stderr_path.stat().st_size
            disk_growth = sum(path.stat().st_size for path in cwd.rglob("*") if path.is_file()) - before_disk
            if time.monotonic() - started > timeout:
                violation = "timeout"
            elif output_bytes > output_limit:
                violation = "output"
            elif peak_ram > limits["ram_bytes"]:
                violation = "ram"
            elif peak_processes > limits["processes"]:
                violation = "process_count"
            elif disk_growth > limits["disk_growth_bytes"]:
                violation = "disk_growth"
            if violation:
                for member in reversed(family):
                    try:
                        member.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                process.kill()
                psutil.wait_procs(family, timeout=5)
                break
            time.sleep(0.05)
        returncode = process.wait(timeout=10)
    output_bytes = stdout_path.stat().st_size + stderr_path.stat().st_size
    stdout_path.unlink(missing_ok=True)
    stderr_path.unlink(missing_ok=True)
    return {
        "passed": returncode == 0 and violation is None,
        "returncode": returncode,
        "violation": violation,
        "timed_out": violation == "timeout",
        "output_bytes": output_bytes,
        "peak_ram_bytes": peak_ram,
        "peak_process_count": peak_processes,
        "duration_seconds": round(time.monotonic() - started, 3),
        "limits": limits,
        "isolation_note": "Monitored subprocess under caller identity; not an OS sandbox.",
    }
