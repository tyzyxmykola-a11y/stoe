from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_hermes.promotion import ApprovedRelease, StandingPolicySupervisor  # noqa: E402
from stoe_hermes.split_cycle_v2_2 import validate_code_v2_2  # noqa: E402
from stoe_hermes.succession import (  # noqa: E402
    EDITABLE_PATH,
    SuccessionError,
    atomic_json,
    run_bounded,
    sha256_bytes,
    sha256_file,
)


ACTION_ID = "checkpoint:hermes-v2.2-promotion-v1"
PARENT_SHA = "b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155"
CANDIDATE_SHA = "fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff"
PARENT_RELEASE = "hermes-a-bb924730743c"
CANDIDATE_RELEASE = "hermes-b-fc16fd510289"
POLICY_ID = "standing:bounded-qualified-succession-v1"


def minimal_environment(runtime: Path) -> dict[str, str]:
    temp = runtime / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    result = {
        "PATH": str(Path(sys.executable).parent.resolve()),
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str((ROOT / "stoe-hermes" / "src").resolve()),
        "TEMP": str(temp.resolve()),
        "TMP": str(temp.resolve()),
    }
    for key in ("SystemRoot", "COMSPEC", "WINDIR"):
        if os.environ.get(key):
            result[key] = os.environ[key]
    return result


def health_program(pointer: Path, source: Path) -> str:
    return (
        "import hashlib,json;from pathlib import Path;"
        "from stoe_hermes.context_renderer import render_retrieved_context;"
        f"p=Path({str(pointer)!r});s=Path({str(source)!r});"
        "a=json.loads(p.read_text(encoding='utf-8'));"
        f"assert a['release_id']=={CANDIDATE_RELEASE!r};"
        f"assert hashlib.sha256(s.read_bytes()).hexdigest()=={CANDIDATE_SHA!r};"
        "c='same';h=hashlib.sha256(c.encode()).hexdigest();"
        "x=[{'sha256':h,'content':c,'ref':'A','relation':'evaluates','provenance':'one'},"
        "{'sha256':h,'content':c,'ref':'B','relation':'correction_of','provenance':'two'}];"
        "r=render_retrieved_context(x,4000);"
        "assert r.count('PAYLOAD |')==1 and r.count('CONNECTION |')==2;"
        "assert 'canonical_payloads=1' in r and 'collapsed_duplicates=1' in r;"
        "assert len(render_retrieved_context(x,120))<=120"
    )


def run(runtime: Path) -> dict:
    runtime = runtime.resolve()
    state_path = runtime / "promotion.json"
    if state_path.exists():
        raise SuccessionError("promotion stable action already completed; never repeat it")
    runtime.mkdir(parents=True, exist_ok=True)

    source_path = ROOT / EDITABLE_PATH
    pointer_path = ROOT / "stoe-hermes" / "releases" / "active_release.json"
    proposal_path = ROOT / "stoe-hermes" / "evidence" / "v2_2" / "v2_1_candidate_patch.json"
    qualification_path = ROOT / "agent" / "runtime" / "hermes_ab_v2_2" / "cycle.json"
    manifest_path = ROOT / "stoe-hermes" / "HERMES_AB_V2_2_MANIFEST.json"
    policy_path = ROOT / "stoe-hermes" / "policies" / "bounded_succession_v1.json"

    if sha256_file(source_path) != PARENT_SHA:
        raise SuccessionError("active source is not the trusted parent")
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    parent = source_path.read_text(encoding="utf-8")
    _, candidate, validation = validate_code_v2_2(proposal, parent, EDITABLE_PATH)
    candidate_bytes = candidate.encode("utf-8")
    if validation["candidate_sha256"] != CANDIDATE_SHA:
        raise SuccessionError("candidate identity mismatch")

    prior = json.loads(qualification_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_cycle_sha = manifest["files"]["agent/runtime/hermes_ab_v2_2/cycle.json"]
    if sha256_file(qualification_path) != expected_cycle_sha:
        raise SuccessionError("protected qualification artifact changed")
    if prior.get("status") != "awaiting_author_approval" or prior.get("protected_evaluation", {}).get("passed") is not True:
        raise SuccessionError("protected qualification prerequisites did not pass")
    if prior.get("candidate", {}).get("candidate_sha256") != CANDIDATE_SHA:
        raise SuccessionError("protected qualification candidate differs")

    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    pointer_before = json.loads(pointer_path.read_text(encoding="utf-8"))
    if pointer_before.get("release_id") != PARENT_RELEASE:
        raise SuccessionError("active pointer is not Hermes A")

    parent_release_root = ROOT / "stoe-hermes" / "releases" / PARENT_RELEASE
    candidate_release_root = ROOT / "stoe-hermes" / "releases" / CANDIDATE_RELEASE
    if parent_release_root.exists() or candidate_release_root.exists():
        raise SuccessionError("release record destination already exists")
    parent_release_root.mkdir(parents=True)
    candidate_release_root.mkdir(parents=True)
    rollback_source = parent_release_root / "context_renderer.py"
    rollback_source.write_bytes(source_path.read_bytes())
    candidate_artifact = candidate_release_root / "context_renderer.py"
    candidate_artifact.write_bytes(candidate_bytes)
    atomic_json(parent_release_root / "release.json", pointer_before)

    policy_sha = sha256_file(policy_path)
    environment_fingerprint = sha256_bytes(json.dumps({
        "candidate": CANDIDATE_SHA,
        "parent": PARENT_SHA,
        "policy": policy_sha,
        "protected_qualification": expected_cycle_sha,
    }, sort_keys=True).encode("utf-8"))
    release = ApprovedRelease(
        release_id=CANDIDATE_RELEASE,
        parent_release=PARENT_RELEASE,
        hermes_commit="bb924730743cc05934bf0dfd188abdfdb46c03c2",
        hermes_version="0.20.3 (2026.8.16.2)",
        integration_plugin_version="0.1.0",
        model_configuration={
            "planner": {"model": "gemma4:26b", "digest": "08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68"},
            "coder": {"model": "qwen3-coder:latest", "digest": "06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca"},
        },
        configuration_hash=pointer_before["configuration_hash"],
        environment_fingerprint=environment_fingerprint,
        protected_results=prior["protected_evaluation"]["tests"],
        candidate_status="approved",
        activation_status="inactive",
        rollback_target=PARENT_RELEASE,
        creation_action_id=ACTION_ID,
        stoe_field_ids=["IP_52b9f2678db549e0", "IP_f4d2f7b504cd433f", "IP_48cf7c158ae24efd"],
        editable_path=EDITABLE_PATH,
        parent_source_sha256=PARENT_SHA,
        candidate_source_sha256=CANDIDATE_SHA,
        candidate_artifact="releases/hermes-b-fc16fd510289/context_renderer.py",
        authorization_policy_id=POLICY_ID,
    )
    approved_record = candidate_release_root / "approved_release.json"
    atomic_json(approved_record, release.as_dict())

    qualification = {
        "editable_path": EDITABLE_PATH,
        "parent_source_sha256": PARENT_SHA,
        "candidate_source_sha256": CANDIDATE_SHA,
        "protected_validation_passed": True,
        "protected_evaluation_passed": True,
        "authority_expansion": False,
        "rollback_available": True,
    }
    health: dict = {}

    def fresh_health() -> bool:
        nonlocal health
        health = run_bounded(
            [sys.executable, "-c", health_program(pointer_path, source_path)],
            cwd=ROOT,
            env=minimal_environment(runtime),
            timeout=20,
            output_limit=100_000,
        )
        return bool(health["passed"])

    activation = StandingPolicySupervisor(pointer_path).activate(
        release,
        policy=policy,
        qualification=qualification,
        source_path=source_path,
        candidate_source=candidate_bytes,
        rollback_source_path=rollback_source,
        health_check=fresh_health,
    )
    final = {
        "action_id": ACTION_ID,
        "identity": {"parent_sha256": PARENT_SHA, "candidate_sha256": CANDIDATE_SHA},
        "approved_release_sha256": sha256_file(approved_record),
        "authorization_policy": {"policy_id": POLICY_ID, "sha256": policy_sha},
        "activation": activation,
        "health": health,
        "rollback": {"release_id": PARENT_RELEASE, "source_sha256": sha256_file(rollback_source)},
        "model_calls": 0,
        "status": "active" if activation["status"] == "active" else "rolled_back",
    }
    atomic_json(candidate_release_root / "activation_result.json", final)
    atomic_json(state_path, final)
    return final


def main() -> int:
    runtime = ROOT / "agent" / "runtime" / "hermes_ab_promotion_v1"
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
