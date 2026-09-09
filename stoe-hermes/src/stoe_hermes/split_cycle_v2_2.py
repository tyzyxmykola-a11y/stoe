from __future__ import annotations

from typing import Any

from .succession import (
    EDITABLE_PATH,
    SuccessionError,
    reconstruct_candidate,
    sha256_bytes,
    validate_candidate_source_v2_2,
    validate_patch_envelope,
)


def validate_code_v2_2(value: Any, parent: str, path: str = EDITABLE_PATH) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Validate a v2.1 inert proposal through the versioned v2.2 boundary."""
    required = {"format", "version", "path", "parent_sha256", "replacement_lines", "rationale", "expected_tests"}
    if not isinstance(value, dict) or set(value) != required:
        raise SuccessionError("invalid coding artifact envelope")
    if not isinstance(value["rationale"], str) or len(value["rationale"]) > 800 or not isinstance(value["expected_tests"], list):
        raise SuccessionError("invalid bounded coding metadata")
    core = {key: value[key] for key in ("format", "version", "path", "parent_sha256", "replacement_lines")}
    validate_patch_envelope(core, parent_sha256=sha256_bytes(parent.encode("utf-8")), path=path)
    candidate = reconstruct_candidate(parent, core)
    validation = validate_candidate_source_v2_2(parent, candidate)
    return {**value, "candidate_sha256": validation["candidate_sha256"]}, candidate, validation
