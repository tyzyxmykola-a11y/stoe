from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_hermes.promotion import ApprovedRelease, StandingPolicySupervisor  # noqa: E402
from stoe_hermes.split_cycle_v2_2 import validate_code_v2_2  # noqa: E402
from stoe_hermes.succession import EDITABLE_PATH, SuccessionError, atomic_json, run_bounded, sha256_bytes, sha256_file  # noqa: E402


ACTION_ID = "checkpoint:hermes-v2.2-promotion-v2-release-resolver"
PARENT_SHA = "b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155"
CANDIDATE_SHA = "fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff"
PARENT_RELEASE = "hermes-a-bb924730743c"
CANDIDATE_RELEASE = "hermes-b-fc16fd510289"
POLICY_ID = "standing:bounded-qualified-succession-v1"
CANDIDATE_ARTIFACT = f"releases/{CANDIDATE_RELEASE}/context_renderer.py"


def minimal_environment(runtime: Path) -> dict[str, str]:
    temporary = runtime / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    result = {
        "PATH": str(Path(sys.executable).parent.resolve()),
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str((ROOT / "stoe-hermes" / "src").resolve()),
        "TEMP": str(temporary.resolve()),
        "TMP": str(temporary.resolve()),
    }
    for key in ("SystemRoot", "COMSPEC", "WINDIR"):
        if os.environ.get(key):
            result[key] = os.environ[key]
    return result


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
        "assert 'canonical_payloads=1' in r and 'collapsed_duplicates=1' in r;assert len(f(x,120))<=120"
    )


def run(runtime: Path) -> dict:
    runtime = runtime.resolve()
    state_path = runtime / "promotion.json"
    if state_path.exists():
        raise SuccessionError("promotion v2 stable action already completed; never repeat it")
    runtime.mkdir(parents=True, exist_ok=True)
    source = ROOT / EDITABLE_PATH
    pointer = ROOT / "stoe-hermes" / "releases" / "active_release.json"
    artifact = ROOT / "stoe-hermes" / CANDIDATE_ARTIFACT
    rollback = ROOT / "stoe-hermes" / "releases" / PARENT_RELEASE / "context_renderer.py"
    proposal_path = ROOT / "stoe-hermes" / "evidence" / "v2_2" / "v2_1_candidate_patch.json"
    qualification_path = ROOT / "agent" / "runtime" / "hermes_ab_v2_2" / "cycle.json"
    manifest = json.loads((ROOT / "stoe-hermes" / "HERMES_AB_V2_2_MANIFEST.json").read_text(encoding="utf-8"))
    policy_path = ROOT / "stoe-hermes" / "policies" / "bounded_succession_v1.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))

    if sha256_file(source) != PARENT_SHA or sha256_file(rollback) != PARENT_SHA:
        raise SuccessionError("trusted parent or rollback identity mismatch")
    parent = source.read_text(encoding="utf-8")
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    _, candidate, validation = validate_code_v2_2(proposal, parent, EDITABLE_PATH)
    candidate_bytes = candidate.encode("utf-8")
    if validation["candidate_sha256"] != CANDIDATE_SHA or sha256_file(artifact) != CANDIDATE_SHA:
        raise SuccessionError("exact qualified candidate identity mismatch")
    expected_cycle_sha = manifest["files"]["agent/runtime/hermes_ab_v2_2/cycle.json"]
    prior = json.loads(qualification_path.read_text(encoding="utf-8"))
    if sha256_file(qualification_path) != expected_cycle_sha:
        raise SuccessionError("protected qualification artifact changed")
    if prior.get("protected_evaluation", {}).get("passed") is not True:
        raise SuccessionError("protected evaluation prerequisite failed")
    current_pointer = json.loads(pointer.read_text(encoding="utf-8"))
    if current_pointer.get("release_id") != PARENT_RELEASE:
        raise SuccessionError("Hermes A is not active at promotion start")

    record_root = ROOT / "stoe-hermes" / "releases" / CANDIDATE_RELEASE / "promotion_v2"
    if record_root.exists():
        raise SuccessionError("promotion v2 release record already exists")
    record_root.mkdir(parents=True)
    policy_sha = sha256_file(policy_path)
    fingerprint = sha256_bytes(json.dumps({
        "candidate": CANDIDATE_SHA, "parent": PARENT_SHA, "policy": policy_sha,
        "qualification": expected_cycle_sha, "resolver": sha256_file(ROOT / "stoe-hermes" / "src" / "stoe_hermes" / "promotion.py"),
    }, sort_keys=True).encode("utf-8"))
    release = ApprovedRelease(
        release_id=CANDIDATE_RELEASE, parent_release=PARENT_RELEASE,
        hermes_commit="bb924730743cc05934bf0dfd188abdfdb46c03c2", hermes_version="0.20.3 (2026.8.16.2)",
        integration_plugin_version="0.1.0", configuration_hash=current_pointer["configuration_hash"],
        environment_fingerprint=fingerprint, editable_path=EDITABLE_PATH,
        parent_source_sha256=PARENT_SHA, candidate_source_sha256=CANDIDATE_SHA,
        candidate_artifact=CANDIDATE_ARTIFACT, authorization_policy_id=POLICY_ID,
        model_configuration={"planner":"gemma4:26b@08ae7ec1744b", "coder":"qwen3-coder@06c1097efce0"},
        protected_results=prior["protected_evaluation"]["tests"], rollback_target=PARENT_RELEASE,
        creation_action_id=ACTION_ID, stoe_field_ids=["IP_52b9f2678db549e0", "IP_48cf7c158ae24efd", "IP_2444938847dd4fac"],
    )
    approved = record_root / "approved_release.json"
    atomic_json(approved, release.as_dict())
    qualification = {
        "editable_path": EDITABLE_PATH, "parent_source_sha256": PARENT_SHA,
        "candidate_source_sha256": CANDIDATE_SHA, "protected_validation_passed": True,
        "protected_evaluation_passed": True, "authority_expansion": False, "rollback_available": True,
    }
    health: list[dict] = []

    def complete_health() -> bool:
        env = minimal_environment(runtime)
        health.append(run_bounded([sys.executable, "-c", resolver_health(pointer, source, artifact)], cwd=ROOT, env=env, timeout=20, output_limit=100_000))
        health.append(run_bounded([sys.executable, "-m", "unittest", "discover", "-s", "stoe-hermes/tests", "-p", "test_*.py", "-q"], cwd=ROOT, env=env, timeout=60, output_limit=300_000))
        return all(item["passed"] for item in health)

    activation = StandingPolicySupervisor(pointer).activate(
        release, policy=policy, qualification=qualification, source_path=source,
        candidate_source=candidate_bytes, rollback_source_path=rollback, health_check=complete_health,
    )
    result = {
        "action_id": ACTION_ID, "identity": {"parent_sha256": PARENT_SHA, "candidate_sha256": CANDIDATE_SHA},
        "approved_release_sha256": sha256_file(approved), "policy": {"id": POLICY_ID, "sha256": policy_sha},
        "activation": activation, "health": health, "rollback_target": PARENT_RELEASE, "model_calls": 0,
        "status": "active" if activation["status"] == "active" else "rolled_back",
    }
    atomic_json(record_root / "activation_result.json", result)
    atomic_json(state_path, result)
    return result


def main() -> int:
    runtime = ROOT / "agent" / "runtime" / "hermes_ab_promotion_v2"
    try:
        result = run(runtime)
    except Exception as exc:
        runtime.mkdir(parents=True, exist_ok=True)
        failure = {"action_id": ACTION_ID, "status": "failed_closed", "failure": f"{type(exc).__name__}: {exc}", "model_calls": 0}
        atomic_json(runtime / "promotion.json", failure)
        print(json.dumps(failure, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "active" else 2


if __name__ == "__main__":
    raise SystemExit(main())
