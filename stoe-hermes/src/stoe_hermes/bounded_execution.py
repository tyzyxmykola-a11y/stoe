from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .succession import SuccessionError, sha256_bytes


def bounded_environment(
    *, python_executable: str, pythonpath: Path, temporary: Path,
    required_tools: tuple[str, ...] = (),
) -> tuple[dict[str, str], dict[str, str]]:
    """Build a minimal environment with only explicitly required tool paths."""
    temporary.mkdir(parents=True, exist_ok=True)
    path_entries = [str(Path(python_executable).resolve().parent)]
    resolved_tools: dict[str, str] = {}
    for tool in required_tools:
        resolved = shutil.which(tool)
        if not resolved:
            raise SuccessionError(f"required trusted test tool is unavailable: {tool}")
        resolved_path = str(Path(resolved).resolve())
        resolved_tools[tool] = resolved_path
        parent = str(Path(resolved_path).parent)
        if parent not in path_entries:
            path_entries.append(parent)
    result = {
        "PATH": os.pathsep.join(path_entries),
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(pythonpath.resolve()),
        "TEMP": str(temporary.resolve()),
        "TMP": str(temporary.resolve()),
    }
    for key in ("SystemRoot", "COMSPEC", "WINDIR"):
        if os.environ.get(key):
            result[key] = os.environ[key]
    return result, resolved_tools


def _preservation_limits(stdout_size: int, stderr_size: int, total_cap: int) -> tuple[int, int]:
    if stdout_size + stderr_size <= total_cap:
        return stdout_size, stderr_size
    stdout_cap = min(stdout_size, total_cap // 2)
    stderr_cap = min(stderr_size, total_cap // 2)
    remaining = total_cap - stdout_cap - stderr_cap
    extra_stdout = min(max(0, stdout_size - stdout_cap), remaining)
    stdout_cap += extra_stdout
    remaining -= extra_stdout
    stderr_cap += min(max(0, stderr_size - stderr_cap), remaining)
    return stdout_cap, stderr_cap


def run_bounded_preserved(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    artifact_dir: Path,
    label: str,
    timeout: int = 30,
    output_limit: int = 1_000_000,
) -> dict[str, Any]:
    """Run with existing resource bounds and retain capped diagnostic streams."""
    try:
        import psutil
    except ImportError as exc:
        raise SuccessionError("psutil is required for bounded candidate execution") from exc
    if timeout <= 0 or output_limit <= 0:
        raise SuccessionError("bounded execution limits must be positive")
    safe_label = re.sub(r"[^A-Za-z0-9_.-]", "_", label)[:80]
    if not safe_label:
        raise SuccessionError("bounded execution label is empty")
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    raw_stdout = artifact_dir / f".{safe_label}.stdout.raw"
    raw_stderr = artifact_dir / f".{safe_label}.stderr.raw"
    saved_stdout = artifact_dir / f"{safe_label}.stdout.txt"
    saved_stderr = artifact_dir / f"{safe_label}.stderr.txt"
    for path in (raw_stdout, raw_stderr, saved_stdout, saved_stderr):
        if path.exists():
            raise SuccessionError(f"bounded output artifact already exists: {path.name}")

    started = time.monotonic()
    before_disk = sum(path.stat().st_size for path in cwd.rglob("*") if path.is_file())
    violation = None
    peak_ram = 0
    peak_processes = 1
    limits = {
        "timeout_seconds": timeout,
        "output_bytes": output_limit,
        "ram_bytes": 2_000_000_000,
        "processes": 12,
        "disk_growth_bytes": 250_000_000,
    }
    try:
        with raw_stdout.open("wb") as stdout, raw_stderr.open("wb") as stderr:
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
                output_bytes = raw_stdout.stat().st_size + raw_stderr.stat().st_size
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
    except OSError as exc:
        raw_stdout.write_bytes(b"")
        raw_stderr.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        returncode = -1
        violation = "launch_error"

    stdout_size = raw_stdout.stat().st_size
    stderr_size = raw_stderr.stat().st_size
    if stdout_size + stderr_size > output_limit and violation is None:
        violation = "output"
    stdout_cap, stderr_cap = _preservation_limits(stdout_size, stderr_size, output_limit)
    stdout_bytes = raw_stdout.read_bytes()[:stdout_cap]
    stderr_bytes = raw_stderr.read_bytes()[:stderr_cap]
    saved_stdout.write_bytes(stdout_bytes)
    saved_stderr.write_bytes(stderr_bytes)
    raw_stdout.unlink(missing_ok=True)
    raw_stderr.unlink(missing_ok=True)
    return {
        "passed": returncode == 0 and violation is None,
        "returncode": returncode,
        "violation": violation,
        "timed_out": violation == "timeout",
        "limits": limits,
        "peak_ram_bytes": peak_ram,
        "peak_process_count": peak_processes,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout": {
            "path": str(saved_stdout), "original_bytes": stdout_size,
            "preserved_bytes": len(stdout_bytes), "truncated": len(stdout_bytes) < stdout_size,
            "sha256": sha256_bytes(stdout_bytes),
        },
        "stderr": {
            "path": str(saved_stderr), "original_bytes": stderr_size,
            "preserved_bytes": len(stderr_bytes), "truncated": len(stderr_bytes) < stderr_size,
            "sha256": sha256_bytes(stderr_bytes),
        },
        "preserved_output_bytes": len(stdout_bytes) + len(stderr_bytes),
        "output_truncated": len(stdout_bytes) < stdout_size or len(stderr_bytes) < stderr_size,
        "isolation_note": "Monitored subprocess under caller identity; not an OS sandbox.",
    }
