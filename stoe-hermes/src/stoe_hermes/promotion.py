from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .succession import EDITABLE_PATH, SuccessionError, atomic_json, sha256_bytes


@dataclass
class ApprovedRelease:
    release_id: str
    parent_release: str
    hermes_commit: str
    hermes_version: str
    integration_plugin_version: str
    configuration_hash: str
    environment_fingerprint: str
    editable_path: str
    parent_source_sha256: str
    candidate_source_sha256: str
    candidate_artifact: str
    authorization_policy_id: str
    model_configuration: dict[str, Any]
    protected_results: list[dict[str, Any]] = field(default_factory=list)
    candidate_status: str = "approved"
    activation_status: str = "inactive"
    rollback_target: str = ""
    creation_action_id: str = ""
    stoe_field_ids: list[str] = field(default_factory=list)
    activation_blockers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_active_renderer(pointer_path: Path | None = None) -> Callable[[list[dict[str, Any]], int], str]:
    """Resolve a hash-bound release artifact without changing replay fixtures."""
    package_root = Path(__file__).resolve().parents[2]
    pointer = (pointer_path or package_root / "releases" / "active_release.json").resolve()
    integration_root = pointer.parent.parent if pointer_path is not None else package_root
    active = json.loads(pointer.read_text(encoding="utf-8"))
    artifact_name = active.get("artifact_path")
    if not artifact_name:
        from .context_renderer import render_retrieved_context

        return render_retrieved_context
    artifact = (integration_root / str(artifact_name)).resolve()
    releases_root = (integration_root / "releases").resolve()
    if not artifact.is_relative_to(releases_root) or not artifact.is_file():
        raise SuccessionError("active release artifact is outside the protected release store")
    expected_sha = str(active.get("source_sha256") or "")
    if sha256_bytes(artifact.read_bytes()) != expected_sha:
        raise SuccessionError("active release artifact identity mismatch")
    module_name = "_stoe_hermes_release_" + expected_sha[:16]
    specification = importlib.util.spec_from_file_location(module_name, artifact)
    if specification is None or specification.loader is None:
        raise SuccessionError("active release artifact cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    renderer = getattr(module, "render_retrieved_context", None)
    if not callable(renderer):
        raise SuccessionError("active release artifact has no renderer")
    return renderer


def render_active_context(items: list[dict[str, Any]], max_chars: int, *, pointer_path: Path | None = None) -> str:
    return resolve_active_renderer(pointer_path)(items, max_chars)


class StandingPolicySupervisor:
    """Trusted transaction for bounded qualified source succession."""

    def __init__(self, pointer_path: Path) -> None:
        self.pointer_path = pointer_path.resolve()

    def read_pointer(self) -> dict[str, Any]:
        return json.loads(self.pointer_path.read_text(encoding="utf-8"))

    @staticmethod
    def _atomic_bytes(path: Path, content: bytes, label: str) -> None:
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.{label}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, path)

    def activate(
        self,
        candidate: ApprovedRelease,
        *,
        policy: dict[str, Any],
        qualification: dict[str, Any],
        source_path: Path,
        candidate_source: bytes,
        rollback_source_path: Path,
        health_check: Callable[[], bool],
    ) -> dict[str, Any]:
        required_flags = (
            "exact_candidate_identity",
            "trusted_parent_identity",
            "protected_validation_passed",
            "protected_evaluation_passed",
            "no_authority_expansion",
            "rollback_available",
        )
        if policy.get("schema_version") != 1 or policy.get("status") != "active":
            raise SuccessionError("standing succession policy is not active schema v1")
        if policy.get("authorized_by") != "Mykola Voronin" or policy.get("decision_rule") != "all_required":
            raise SuccessionError("standing succession policy authority changed")
        requirements = policy.get("requirements")
        if not isinstance(requirements, dict) or any(requirements.get(key) is not True for key in required_flags):
            raise SuccessionError("standing succession policy prerequisites are incomplete")
        if candidate.candidate_status != "approved" or candidate.activation_blockers:
            raise SuccessionError("candidate is not an unblocked approved successor")
        if candidate.authorization_policy_id != policy.get("policy_id"):
            raise SuccessionError("candidate is not bound to this standing policy")
        if candidate.editable_path != EDITABLE_PATH or policy.get("allowed_editable_paths") != [EDITABLE_PATH]:
            raise SuccessionError("editable boundary differs from the standing policy")

        previous_bytes = self.pointer_path.read_bytes()
        previous = json.loads(previous_bytes.decode("utf-8"))
        if previous.get("release_id") != candidate.parent_release:
            raise SuccessionError("active release is not the candidate's trusted parent")
        source_path = source_path.resolve()
        rollback_source_path = rollback_source_path.resolve()
        parent_bytes = source_path.read_bytes()
        rollback_bytes = rollback_source_path.read_bytes()
        parent_sha = sha256_bytes(parent_bytes)
        candidate_sha = sha256_bytes(candidate_source)
        if parent_sha != candidate.parent_source_sha256:
            raise SuccessionError("active parent source identity mismatch")
        if sha256_bytes(rollback_bytes) != parent_sha:
            raise SuccessionError("rollback source identity mismatch")
        if candidate_sha != candidate.candidate_source_sha256:
            raise SuccessionError("candidate source identity mismatch")
        integration_root = self.pointer_path.parent.parent
        candidate_artifact = (integration_root / candidate.candidate_artifact).resolve()
        releases_root = (integration_root / "releases").resolve()
        if not candidate_artifact.is_relative_to(releases_root) or not candidate_artifact.is_file():
            raise SuccessionError("candidate artifact is outside the protected release store")
        if candidate_artifact.read_bytes() != candidate_source:
            raise SuccessionError("candidate artifact bytes differ from the approved successor")
        expected_qualification = {
            "editable_path": candidate.editable_path,
            "parent_source_sha256": parent_sha,
            "candidate_source_sha256": candidate_sha,
            "protected_validation_passed": True,
            "protected_evaluation_passed": True,
            "authority_expansion": False,
            "rollback_available": True,
        }
        if qualification != expected_qualification:
            raise SuccessionError("qualification does not satisfy exact standing-policy invariants")

        next_pointer = {
            "release_id": candidate.release_id,
            "environment_fingerprint": candidate.environment_fingerprint,
            "rollback_target": previous["release_id"],
            "editable_path": candidate.editable_path,
            "artifact_path": candidate.candidate_artifact,
            "source_sha256": candidate_sha,
            "authorization_policy_id": candidate.authorization_policy_id,
        }
        atomic_json(self.pointer_path, next_pointer)
        try:
            healthy = bool(health_check())
        except Exception:
            healthy = False
        if not healthy:
            self._atomic_bytes(self.pointer_path, previous_bytes, "rollback")
            return {"status": "rolled_back", "rolled_back_to": previous["release_id"]}
        return {
            "status": "active",
            "activated_as": candidate.release_id,
            "source_sha256": candidate_sha,
            "artifact_path": candidate.candidate_artifact,
            "rollback_target": previous["release_id"],
            "authorization_policy_id": candidate.authorization_policy_id,
        }
