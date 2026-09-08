from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .response_rehearsal import (
    CONDITIONS,
    HARNESS_VERSION,
    MIN_REMAINING_TOKENS,
    POLICY_MAX_TOKENS,
    POLICY_SEEDS,
    POLICY_SYSTEM,
    POLICY_TABLE_SCHEMA,
    PROPOSAL_MAX_TOKENS,
    PROPOSAL_SEEDS,
    PROPOSAL_SYSTEM,
    compile_policy_tables,
    policy_prompt,
    proposal_prompt,
    proposal_schema,
    qualify_context,
    validate_proposal,
)
from .selection_policy import validate_policy
from .selector_loader import sha256_file
from .structural_experiment import StructuralInputExperiment, validate_unseen_cases


class FrozenV3StructuralExperiment(StructuralInputExperiment):
    """Single prereggistered paired run using the real-model-qualified grammar."""

    def preflight(self, *, require_clean: bool = True) -> dict[str, Any]:
        if self.spec.get("status") != "FROZEN_NOT_RUN" or self.spec.get("condition_order") != list(CONDITIONS):
            raise RuntimeError("v3 specification is not frozen or has wrong condition order")
        expected_generation = {
            "calls_per_condition": 2, "total_call_budget": 4, "retry_count": 0,
            "proposal_seed": PROPOSAL_SEEDS[0], "policy_seed": POLICY_SEEDS[0],
            "proposal_max_output_tokens": PROPOSAL_MAX_TOKENS,
            "policy_max_output_tokens": POLICY_MAX_TOKENS,
            "context_limit_tokens": 8192,
        }
        generation = self.spec.get("generation", {})
        if any(generation.get(key) != value for key, value in expected_generation.items()):
            raise RuntimeError("v3 runner differs from frozen generation settings")
        if getattr(self.supervisor.model_client, "context_limit_tokens", None) != 8192:
            raise RuntimeError("v3 model client context differs from frozen setting")

        cases = json.loads(self.cases_path.read_text(encoding="utf-8"))
        structure = validate_unseen_cases(cases)
        if sha256_file(self.cases_path) != self.spec["benchmark"]["sha256"]:
            raise RuntimeError("v3 frozen case hash mismatch")
        if sha256_file(self.input_bundle_path) != self.spec["input_bundle"]["sha256"]:
            raise RuntimeError("v3 input-bundle hash mismatch")

        harness_path = (self.supervisor.config.repo_root / self.spec["qualified_harness"]["manifest"]).resolve()
        if sha256_file(harness_path) != self.spec["qualified_harness"]["sha256"]:
            raise RuntimeError("qualified harness manifest hash mismatch")
        harness = json.loads(harness_path.read_text(encoding="utf-8"))
        if harness.get("status") != "FROZEN_MODEL_QUALIFIED" or harness.get("harness_version") != HARNESS_VERSION:
            raise RuntimeError("response harness is not frozen and model-qualified")
        for relative, expected in harness["critical_file_sha256"].items():
            if sha256_file(self.supervisor.config.repo_root / relative) != expected:
                raise RuntimeError(f"qualified harness critical hash mismatch: {relative}")

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        for relative, expected in manifest["critical_file_sha256"].items():
            if sha256_file(self.supervisor.config.repo_root / relative) != expected:
                raise RuntimeError(f"v3 critical-file hash mismatch: {relative}")

        identity = self.supervisor.model_client.identity()
        if identity.name != self.spec["model"]["name"] or identity.digest != self.spec["model"]["digest"]:
            raise RuntimeError("v3 local model identity mismatch")
        pointer = self.supervisor.read_active_pointer()
        expected_active = self.spec["active_baseline"]
        if pointer["sha256"] != expected_active["sha256"] or pointer["version"] != expected_active["version"]:
            raise RuntimeError("v3 active baseline mismatch")
        bundle = json.loads(self.input_bundle_path.read_text(encoding="utf-8"))
        qualification = qualify_context(
            self.supervisor.model_client,
            Path(pointer["source_path"]).read_text(encoding="utf-8"),
            bundle,
        )
        if qualification["minimum_observed_remaining_tokens"] < MIN_REMAINING_TOKENS:
            raise RuntimeError("v3 complete-pipeline context qualification failed")
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
                raise RuntimeError("v3 frozen experiment requires a clean worktree")
        return {
            "verified": True, "git_commit": commit, "model": asdict(identity),
            "active_baseline": pointer,
            "benchmark": {"path": str(self.cases_path), "sha256": sha256_file(self.cases_path), **structure},
            "input_bundle_sha256": sha256_file(self.input_bundle_path),
            "qualified_harness_manifest_sha256": sha256_file(harness_path),
            "freeze_manifest_sha256": sha256_file(self.manifest_path),
            "worst_case_budget_qualification": qualification,
        }

    def _generate_condition(
        self, *, condition: str, active_source: str, investigation: dict[str, Any],
        observable: list[dict[str, Any]], unstructured_memory: dict[str, Any],
        structural: dict[str, Any] | None, cycle_id: str,
    ) -> dict[str, Any]:
        bundle = {
            "investigation": investigation, "observable_diagnostics": observable,
            "unstructured_memory": unstructured_memory, "typed_relational_overlay": structural,
        }
        is_structural = condition == "BOUNDED_TYPED_STOE"
        result: dict[str, Any] = {"condition": condition, "status": "generation_started"}
        try:
            proposal, trace = self.supervisor.model_client.generate_json(
                system=PROPOSAL_SYSTEM,
                prompt=proposal_prompt(active_source, bundle, structural=is_structural),
                schema=proposal_schema(investigation), max_output_tokens=PROPOSAL_MAX_TOKENS,
                seed=PROPOSAL_SEEDS[0],
            )
            result.update({"proposal": proposal, "proposal_trace": trace})
            validate_proposal(proposal, investigation)
        except Exception as exc:
            result.update({
                "status": "proposal_failed", "failure_stage": "proposal",
                "error": f"{type(exc).__name__}: {exc}",
            })
            return result
        try:
            response, trace = self.supervisor.model_client.generate_json(
                system=POLICY_SYSTEM,
                prompt=policy_prompt(active_source, bundle, proposal, structural=is_structural),
                schema=POLICY_TABLE_SCHEMA, max_output_tokens=POLICY_MAX_TOKENS,
                seed=POLICY_SEEDS[0],
            )
            result.update({"policy_table_response": response, "generation_trace": trace})
            policy = compile_policy_tables(response)
        except Exception as exc:
            result.update({
                "status": "policy_generation_failed", "failure_stage": "policy_generation",
                "error": f"{type(exc).__name__}: {exc}",
            })
            return result
        gate = validate_policy(policy)
        path = self.supervisor.config.runtime_dir / f"candidate_{cycle_id}_{condition.lower()}.policy.json"
        self.supervisor._atomic_write_json(path, policy)
        result.update({
            "status": "generated", "policy": policy,
            "implementation_note": response["implementation_note"],
            "policy_path": str(path), "policy_sha256": sha256_file(path),
            "policy_validation": {
                "passed": gate.passed, "errors": list(gate.errors),
                "estimated_operations": gate.estimated_operations,
            },
        })
        return result
