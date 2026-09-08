from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .qualified_harness import (
    CONDITIONS,
    MIN_REMAINING_TOKENS,
    POLICY_MAX_TOKENS,
    POLICY_SEED,
    POLICY_SYSTEM,
    PROPOSAL_MAX_TOKENS,
    PROPOSAL_SEED,
    PROPOSAL_SYSTEM,
    QUALIFIED_PROPOSAL_SCHEMA,
    policy_prompt,
    proposal_prompt,
    qualify_context_budget,
    validate_qualified_proposal,
)
from .selection_policy import validate_policy
from .selector_loader import sha256_file
from .structural_experiment import StructuralInputExperiment, validate_unseen_cases


class QualifiedStructuralExperiment(StructuralInputExperiment):
    def preflight(self, *, require_clean: bool = True) -> dict[str, Any]:
        if self.spec.get("status") != "FROZEN_NOT_RUN" or self.spec.get("condition_order") != list(CONDITIONS):
            raise RuntimeError("v2 specification is not frozen or has wrong condition order")
        expected_generation = {
            "calls_per_condition": 2, "total_call_budget": 4, "retry_count": 0,
            "proposal_seed": PROPOSAL_SEED, "policy_seed": POLICY_SEED,
            "proposal_max_output_tokens": PROPOSAL_MAX_TOKENS,
            "policy_max_output_tokens": POLICY_MAX_TOKENS,
            "context_limit_tokens": 8192,
        }
        generation = self.spec.get("generation", {})
        if any(generation.get(key) != value for key, value in expected_generation.items()):
            raise RuntimeError("v2 runner differs from frozen generation settings")
        cases = json.loads(self.cases_path.read_text(encoding="utf-8"))
        structure = validate_unseen_cases(cases)
        if sha256_file(self.cases_path) != self.spec["benchmark"]["sha256"]:
            raise RuntimeError("v2 case hash mismatch")
        if sha256_file(self.input_bundle_path) != self.spec["input_bundle"]["sha256"]:
            raise RuntimeError("v2 input-bundle hash mismatch")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        for relative, expected in manifest["critical_file_sha256"].items():
            if sha256_file(self.supervisor.config.repo_root / relative) != expected:
                raise RuntimeError(f"v2 critical-file hash mismatch: {relative}")
        identity = self.supervisor.model_client.identity()
        if identity.name != self.spec["model"]["name"] or identity.digest != self.spec["model"]["digest"]:
            raise RuntimeError("v2 model identity mismatch")
        pointer = self.supervisor.read_active_pointer()
        if pointer["sha256"] != self.spec["active_baseline"]["sha256"]:
            raise RuntimeError("v2 active baseline mismatch")
        bundle = json.loads(self.input_bundle_path.read_text(encoding="utf-8"))
        active_source = Path(pointer["source_path"]).read_text(encoding="utf-8")
        qualification = qualify_context_budget(self.supervisor.model_client, active_source, bundle)
        if qualification["minimum_observed_remaining_tokens"] < MIN_REMAINING_TOKENS:
            raise RuntimeError("v2 worst-case budget qualification failed")
        commit = subprocess.run(
            ["git", "-C", str(self.supervisor.config.repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        if require_clean:
            dirty = subprocess.run(
                ["git", "-C", str(self.supervisor.config.repo_root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
            if dirty:
                raise RuntimeError("v2 requires a clean frozen worktree")
        return {
            "verified": True, "git_commit": commit, "model": asdict(identity),
            "active_baseline": pointer,
            "benchmark": {"path": str(self.cases_path), "sha256": sha256_file(self.cases_path), **structure},
            "input_bundle_sha256": sha256_file(self.input_bundle_path),
            "freeze_manifest_sha256": sha256_file(self.manifest_path),
            "worst_case_budget_qualification": qualification,
        }

    def _generate_condition(
        self, *, condition: str, active_source: str, investigation: dict[str, Any],
        observable: list[dict[str, Any]], unstructured_memory: dict[str, Any],
        structural: dict[str, Any] | None, cycle_id: str,
    ) -> dict[str, Any]:
        bundle = {
            "investigation": investigation,
            "observable_diagnostics": observable,
            "unstructured_memory": unstructured_memory,
            "typed_relational_overlay": structural,
        }
        is_structural = condition == "BOUNDED_TYPED_STOE"
        result: dict[str, Any] = {"condition": condition, "status": "generation_started"}
        try:
            proposal, trace = self.supervisor.model_client.generate_json(
                system=PROPOSAL_SYSTEM,
                prompt=proposal_prompt(active_source, bundle, structural=is_structural),
                schema=QUALIFIED_PROPOSAL_SCHEMA,
                max_output_tokens=PROPOSAL_MAX_TOKENS, seed=PROPOSAL_SEED,
            )
            result.update({"proposal": proposal, "proposal_trace": trace})
            validate_qualified_proposal(proposal, investigation)
        except Exception as exc:
            result.update({"status": "proposal_failed", "failure_stage": "proposal", "error": f"{type(exc).__name__}: {exc}"})
            return result
        try:
            generated, trace = self.supervisor.model_client.generate_json(
                system=POLICY_SYSTEM,
                prompt=policy_prompt(active_source, bundle, proposal, structural=is_structural),
                schema=self.supervisor.candidate_policy_schema,
                max_output_tokens=POLICY_MAX_TOKENS, seed=POLICY_SEED,
            )
            result["generation_trace"] = trace
        except Exception as exc:
            result.update({"status": "policy_generation_failed", "failure_stage": "policy_generation", "error": f"{type(exc).__name__}: {exc}"})
            return result
        policy = generated.get("policy")
        gate = validate_policy(policy)
        path = self.supervisor.config.runtime_dir / f"candidate_{cycle_id}_{condition.lower()}.policy.json"
        self.supervisor._atomic_write_json(path, policy if isinstance(policy, dict) else {"invalid": repr(policy)[:1000]})
        result.update({
            "status": "generated", "policy": policy,
            "implementation_note": generated.get("implementation_note", ""),
            "policy_path": str(path), "policy_sha256": sha256_file(path),
            "policy_validation": {"passed": gate.passed, "errors": list(gate.errors), "estimated_operations": gate.estimated_operations},
        })
        return result
