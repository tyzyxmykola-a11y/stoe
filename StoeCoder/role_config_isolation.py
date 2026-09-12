"""Trusted isolation for mutable StoeCoder role configuration.

Role choices are operator/runtime configuration, not candidate source changes.
Historically the live registry was stored in tracked ``StoeCoder/roles.json``
and copied into every candidate worktree, which could make a pure UI role
change appear as a worker-authored diff. This adapter migrates the live registry
to the ignored runtime area and restores the candidate copy to its committed
HEAD state before model work or candidate evidence can observe it.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from types import MethodType
from typing import Any

from roles import RoleRegistry


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".roles-runtime-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _restore_candidate_registry(worktree: Any) -> None:
    root = Path(worktree).resolve()
    target = root / "StoeCoder" / "roles.json"
    result = subprocess.run(
        ["git", "show", "HEAD:StoeCoder/roles.json"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        _atomic_bytes(target, result.stdout)
    elif target.exists():
        target.unlink()


def install_role_config_isolation(coder: Any) -> None:
    """Move live roles to runtime storage and keep them out of candidate diffs."""

    if getattr(coder, "_stoe_role_config_isolation_installed", False):
        return

    legacy_path = Path(coder.repo_root) / "StoeCoder" / "roles.json"
    runtime_path = Path(coder.runtime_root) / "roles.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)

    if not runtime_path.exists() and legacy_path.is_file():
        _atomic_bytes(runtime_path, legacy_path.read_bytes())

    coder.roles = RoleRegistry(runtime_path, coder.ollama.models, coder._role_transition)
    coder.roles.initialize()

    original_execute_tool = coder._execute_tool
    original_memory_context = getattr(coder, "_memory_context", None)
    normalized_tasks: set[str] = set()

    def normalize_task_candidate(self, task_id: str, worktree: Any) -> None:
        if task_id in normalized_tasks:
            return
        root = Path(worktree)
        if root.exists():
            _restore_candidate_registry(root)
            normalized_tasks.add(task_id)

    def isolated_execute_tool(self, task_id: str, step: int, worktree, request: dict[str, Any], allowed_paths):
        normalize_task_candidate(self, task_id, worktree)
        return original_execute_tool(task_id, step, worktree, request, allowed_paths)

    coder._execute_tool = MethodType(isolated_execute_tool, coder)

    if callable(original_memory_context):
        def isolated_memory_context(self, task_id: str, objective: str):
            normalize_task_candidate(self, task_id, Path(self.worktree_root) / task_id)
            return original_memory_context(task_id, objective)
        coder._memory_context = MethodType(isolated_memory_context, coder)

    coder._stoe_role_config_isolation_installed = True
    coder._stoe_runtime_roles_path = str(runtime_path)
    coder._stoe_legacy_roles_path = str(legacy_path)
