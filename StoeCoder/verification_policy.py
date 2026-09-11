"""Single trusted verification policy for standalone StoeCoder.

This module is the source of truth for deterministic verification commands.
Worker-facing workflow controls and the trusted final verifier both derive their
commands from the same repository-aware plan; models do not choose test
frameworks independently.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from types import MethodType
from typing import Any, Iterable


@dataclass(frozen=True)
class VerificationStep:
    key: str
    command: tuple[str, ...]
    worker_required: bool

    def argv(self) -> list[str]:
        return list(self.command)


_TEST_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("stoecoder-tests", "StoeCoder/", ("-m", "unittest", "discover", "-s", "StoeCoder/tests", "-q")),
    ("navigator-v7-tests", "engine/v7/", ("-m", "unittest", "discover", "-s", "engine/v7/tests", "-q")),
    ("agent-tests", "agent/", ("-m", "unittest", "discover", "-s", "agent/tests", "-q")),
    ("stoe-hermes-tests", "stoe-hermes/", ("-m", "unittest", "discover", "-s", "stoe-hermes/tests", "-q")),
)


def _normalize_paths(touched: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in touched:
        path = str(value or "").replace("\\", "/").lstrip("./")
        if path and path not in seen:
            seen.add(path)
            normalized.append(path)
    return normalized


def _matches(path: str, prefix: str) -> bool:
    root = prefix.rstrip("/")
    return path == root or path.startswith(prefix)


def verification_plan(touched: Iterable[Any], *, python_executable: str | None = None) -> list[VerificationStep]:
    """Build the deterministic plan for the current repository diff.

    ``git diff --check`` is always a trusted final-verification gate. Project
    test suites are both worker-visible and final-verification gates. Rule order
    is deterministic so multi-project changes receive a stable command sequence.
    """

    paths = _normalize_paths(touched)
    python = str(python_executable or sys.executable)
    plan = [VerificationStep("diff-check", ("git", "diff", "--check"), False)]
    for key, prefix, args in _TEST_RULES:
        if any(_matches(path, prefix) for path in paths):
            plan.append(VerificationStep(key, (python, *args), True))
    return plan


def worker_verification_commands(touched: Iterable[Any], *, python_executable: str | None = None) -> list[list[str]]:
    return [step.argv() for step in verification_plan(touched, python_executable=python_executable) if step.worker_required]


def final_verification_commands(touched: Iterable[Any], *, python_executable: str | None = None) -> list[list[str]]:
    return [step.argv() for step in verification_plan(touched, python_executable=python_executable)]


def install_verification_policy(coder: Any) -> None:
    """Route the core final verifier through the shared verification plan."""

    if getattr(coder, "_stoe_verification_policy_installed", False):
        return

    def policy_verification_commands(self, touched: list[str]) -> list[list[str]]:
        return final_verification_commands(touched)

    coder._verification_commands = MethodType(policy_verification_commands, coder)
    coder._stoe_verification_policy_installed = True
