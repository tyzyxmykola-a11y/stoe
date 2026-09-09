from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_hermes.bounded_execution import bounded_environment, run_bounded_preserved  # noqa: E402
from stoe_hermes.promotion import ApprovedRelease, StandingPolicySupervisor  # noqa: E402
from stoe_hermes.split_cycle_v2_2 import validate_code_v2_2  # noqa: E402
from stoe_hermes.succession import (  # noqa: E402
    EDITABLE_PATH,
    SuccessionError,
    atomic_json,
    sha256_bytes,
    sha256_file,
)


ACTION_ID = "checkpoint:hermes-v2.2-promotion-v3-preserved-health"
PARENT_SHA = "b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155"
CANDIDATE_SHA = "fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff"
PARENT_RELEASE = "hermes-a-bb924730743c"
CANDIDATE_RELEASE = "hermes-b-fc16fd510289"
POLICY_ID = "standing:bounded-qualified-succession-v1"
CANDIDATE_ARTIFACT = f"releases/{CANDIDATE_RELEASE}/context_renderer.py"


def resolver_health(pointer: Path, source: Path, artifact: Path) -> str:
    return (
        "import hashlib,json;from pathlib import Path;"
        "from stoe_hermes.promotion import resolve_active_renderer;"
        f"p=Path({str(pointer)!r});s=Path({str(source)!r});a=Path({str(artifact)!r});"
        f"assert json.loads(p.read_text(encoding='utf-8'))['release_id']=={CANDIDATE_RELEASE!r};"
        f"assert hashlib.sha256(s.read_bytes()).hexdigest()=={PARENT_SHA!r};"
        f"assert hashlib.sha256(a.read_bytes()).hexdigest()=={CANDIDATE_SHA!r};"
        "f=resolve_active_renderer(p);c='same';h=hashlib.sha256(c.encode()).hexdigest();"
        "x=[{'sha256':h,'content':c,'ref':'A','relation':'evaluates','provenance':'one'},"
        "{'sha256':h,'content':c,'ref':'B','relation':'correction_of','provenance':'two'}];"
        "r=f(x,4000);assert r.count('PAYLOAD |')==1 and r.count('CONNECTION |')==2;"
        "assert 'canonical_payloads=1' in r and 'collapsed_duplicates=1' in r;"
        "assert len(f(x,120))<=120"
    )


def atomic_restore(path: Path, content: bytes) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.rollback.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def run(runtime: Path) -> dict:
    runtime = runtime.resolve()
    state_path = runtime / "promotion.json"
    record_root = ROOT / "stoe-hermes" / "releases" / CANDIDATE_RELEASE / "promotion_v3"
    if state_path.exists() or record_root.exists():
        raise SuccessionError("promotion v3 stable action already started; never repeat it")
    runtime.mkdir(parents=True, exist_ok=True)
    record_root.mkdir(parents=True)

    source = ROOT / EDITABLE_PATH
    pointer = ROOT / "stoe-hermes" / "releases" / "active_release.json"
    artifact = ROOT / "stoe-hermes" / CANDIDATE_ARTIFACT
    rollback = ROOT / "stoe-hermes" / "releases" / PARENT_RELEASE / "context_renderer.py"
    proposal_path = ROOT / "stoe-hermes" / "evidence" / "v2_2" / "v2_1_candidate_patch.json"
    qualification_path = ROOT / "agent" / "runtime" / "hermes_ab_v2_2" / "cycle.json"
    manifest_path = ROOT / "stoe-hermes" / "HERMES_AB_V2_2_MANIFEST.json"
    policy_path = ROOT / "stoe-hermes" / "policies" / "bounded_succession_v1.json"
    pointer_before = pointer.read_bytes()

    if sha256_file(source) != PARENT_SHA or sha256_file(rollback) != PARENT_SHA:
        raise SuccessionError("trusted parent or rollback identity mismatch")
    if json.loads(pointer_before.decode("utf-8")).get("release_id") != PARENT_RELEASE:
        raise SuccessionError("Hermes A is not active at promotion start")
    parent = source.read_text(encoding="utf-8")
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    _, candidate, validation = validate_code_v2_2(proposal, parent, EDITABLE_PATH)
    candidate_bytes = candidate.encode("utf-8")
    if validation["candidate_sha256"] != CANDIDATE_SHA or sha256_file(artifact) != CANDIDATE_SHA:
        raise SuccessionError("exact qualified candidate identity mismatch")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_cycle_sha = manifest["files"]["agent/runtime/hermes_ab_v2_2/cycle.json"]
    prior = json.loads(qualification_path.read_text(encoding="utf-8"))
    if sha256_file(qualification_path) != expected_cycle_sha:
        raise SuccessionError("protected qualification artifact changed")
    if prior.get("status") != "awaiting_author_approval":
        raise SuccessionError("qualified candidate lifecycle status changed")
    if prior.get("protected_evaluation", {}).get("passed") is not True:
        raise SuccessionError("protected evaluation prerequisite failed")
    if prior.get("candidate", {}).get("candidate_sha256") != CANDIDATE_SHA:
        raise SuccessionError("protected qualification candidate differs")

    stored_policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if stored_policy.get("status") != "inactive_after_failed_activation":
        raise SuccessionError("standing policy is not in the expected fail-closed state")
    active_policy = dict(stored_policy)
    active_policy["status"] = "active"
    stored_policy_sha = sha256_file(policy_path)
    active_policy_sha = sha256_bytes(
        (json.dumps(active_policy, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )

    env, resolved_tools = bounded_environment(
        python_executable=sys.executable,
        pythonpath=ROOT / "stoe-hermes" / "src",
        temporary=runtime / "tmp",
        required_tools=("git",),
    )
    fingerprint = sha256_bytes(json.dumps({
        "candidate": CANDIDATE_SHA,
        "parent": PARENT_SHA,
        "authorization_policy": active_policy_sha,
        "qualification": expected_cycle_sha,
        "resolver": sha256_file(ROOT / "stoe-hermes" / "src" / "stoe_hermes" / "promotion.py"),
        "runner": sha256_file(ROOT / "stoe-hermes" / "src" / "stoe_hermes" / "bounded_execution.py"),
        "required_tools": resolved_tools,
    }, sort_keys=True).encode("utf-8"))
    release = ApprovedRelease(
        release_id=CANDIDATE_RELEASE,
        parent_release=PARENT_RELEASE,
        hermes_commit="bb924730743cc05934bf0dfd188abdfdb46c03c2",
        hermes_version="0.20.3 (2026.8.16.2)",
        integration_plugin_version="0.1.0",
        configuration_hash=json.loads(pointer_before.decode("utf-8"))["configuration_hash"],
        environment_fingerprint=fingerprint,
        editable_path=EDITABLE_PATH,
        parent_source_sha256=PARENT_SHA,
        candidate_source_sha256=CANDIDATE_SHA,
        candidate_artifact=CANDIDATE_ARTIFACT,
        authorization_policy_id=POLICY_ID,
        model_configuration={
            "planner": "gemma4:26b@08ae7ec1744b",
            "coder": "qwen3-coder@06c1097efce0",
        },
        protected_results=prior["protected_evaluation"]["tests"],
        rollback_target=PARENT_RELEASE,
        creation_action_id=ACTION_ID,
        stoe_field_ids=["IP_e7ee64b739064c9c", "IP_ad26935618a14c76", "IP_61ad45e8b6844650"],
    )
    approved = record_root / "approved_release.json"
    atomic_json(approved, release.as_dict())
    qualification = {
        "editable_path": EDITABLE_PATH,
        "parent_source_sha256": PARENT_SHA,
        "candidate_source_sha256": CANDIDATE_SHA,
        "protected_validation_passed": True,
        "protected_evaluation_passed": True,
        "authority_expansion": False,
        "rollback_available": True,
    }
    health: list[dict] = []

    def complete_health() -> bool:
        artifacts = record_root / "artifacts"
        health.append(run_bounded_preserved(
            [sys.executable, "-c", resolver_health(pointer, source, artifact)],
            cwd=ROOT,
            env=env,
            artifact_dir=artifacts,
            label="fresh_process_resolver",
            timeout=20,
            output_limit=100_000,
        ))
        if not health[-1]["passed"]:
            return False
        health.append(run_bounded_preserved(
            [sys.executable, "-m", "unittest", "discover", "-s", "stoe-hermes/tests", "-p", "test_*.py", "-q"],
            cwd=ROOT,
            env=env,
            artifact_dir=artifacts,
            label="full_activated_suite",
            timeout=60,
            output_limit=300_000,
        ))
        return health[-1]["passed"]

    activation = StandingPolicySupervisor(pointer).activate(
        release,
        policy=active_policy,
        qualification=qualification,
        source_path=source,
        candidate_source=candidate_bytes,
        rollback_source_path=rollback,
        health_check=complete_health,
    )
    policy_status = stored_policy["status"]
    if activation["status"] == "active":
        try:
            atomic_json(policy_path, active_policy)
            policy_status = "active"
        except Exception:
            atomic_restore(pointer, pointer_before)
            activation = {"status": "rolled_back", "rolled_back_to": PARENT_RELEASE, "reason": "policy_persistence_failed"}
    if activation["status"] != "active" and pointer.read_bytes() != pointer_before:
        atomic_restore(pointer, pointer_before)

    result = {
        "action_id": ACTION_ID,
        "identity": {"parent_sha256": PARENT_SHA, "candidate_sha256": CANDIDATE_SHA},
        "approved_release_sha256": sha256_file(approved),
        "policy": {
            "id": POLICY_ID,
            "before_sha256": stored_policy_sha,
            "authorized_sha256": active_policy_sha,
            "status": policy_status,
        },
        "environment": {"minimal": True, "explicit_required_tools": resolved_tools},
        "activation": activation,
        "health": health,
        "active_pointer_sha256": sha256_file(pointer),
        "active_source_sha256": sha256_file(source),
        "rollback": {"release_id": PARENT_RELEASE, "source_sha256": sha256_file(rollback)},
        "model_calls": 0,
        "status": "active" if activation["status"] == "active" else "rolled_back",
    }
    atomic_json(record_root / "activation_result.json", result)
    atomic_json(state_path, result)
    return result


def main() -> int:
    runtime = ROOT / "agent" / "runtime" / "hermes_ab_promotion_v3"
    try:
        result = run(runtime)
    except Exception as exc:
        runtime.mkdir(parents=True, exist_ok=True)
        failure = {
            "action_id": ACTION_ID,
            "status": "failed_closed",
            "failure": f"{type(exc).__name__}: {exc}",
            "model_calls": 0,
        }
        atomic_json(runtime / "promotion.json", failure)
        print(json.dumps(failure, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "active" else 2


if __name__ == "__main__":
    raise SystemExit(main())
