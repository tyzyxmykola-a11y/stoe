from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    passed: bool
    errors: tuple[str, ...]


def validate_candidate_source(source: str, *, max_bytes: int = 30_000) -> GateResult:
    """Reject executable candidates; an AST denylist is not a sandbox."""
    errors = [
        "executable Python candidate artifacts are unsupported; provide a declarative selection policy"
    ]
    if len(source.encode("utf-8")) > max_bytes:
        errors.append(f"source exceeds {max_bytes} bytes")
    return GateResult(False, tuple(errors))
