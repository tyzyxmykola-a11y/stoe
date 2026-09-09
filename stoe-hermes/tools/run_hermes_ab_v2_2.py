from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.self_code_cycle_v2 import atomic_json  # noqa: E402
from stoe_hermes.split_cycle import diff_text  # noqa: E402
from stoe_hermes.split_cycle_v2_2 import validate_code_v2_2  # noqa: E402
from stoe_hermes.succession import EDITABLE_PATH, SuccessionError, run_bounded, sha256_bytes, sha256_file  # noqa: E402


ACTION_ID = "self-code-cycle:hermes-ab-v2-2:parent-relative-validation"
EXPECTED_PARENT_SHA256 = "b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155"
EXPECTED_CANDIDATE_SHA256 = "fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff"


def protected_check() -> str:
    """Return the established v2.1 withheld focused-evaluation program unchanged."""
    return (
        "from stoe_hermes.context_renderer import render_retrieved_context;import hashlib;"
        "c='same';h=hashlib.sha256(c.encode()).hexdigest();"
        "x=[{'sha256':h,'content':c,'ref':'A','origin':'failure_history','kind':'failure','outcome':'failed','path':'p1','relation':'correction_of','direction':'incoming','provenance':'one'},"
        "{'sha256':h,'content':c,'ref':'B','origin':'runtime_reasoning','kind':'correction','outcome':'supported','path':'p2','relation':'successor','direction':'outgoing','provenance':'two'}];"
        "before=[dict(i) for i in x];r=render_retrieved_context(x,4000);"
        "assert x==before and r.count('PAYLOAD |')==1 and r.count('CONNECTION |')==2 and r.count('same')==1;"
        "assert 'payloads=1' in r and 'collapsed=1' in r and 'canonical_payloads=1' in r and 'collapsed_duplicates=1' in r;"
        "assert len(render_retrieved_context(x,120))<=120"
    )


def minimal_environment(runtime: Path, source_root: Path) -> dict[str, str]:
    temp = runtime / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    result = {
        "PATH": str(Path(sys.executable).parent.resolve()),
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(source_root.resolve()),
        "TEMP": str(temp.resolve()),
        "TMP": str(temp.resolve()),
    }
    for key in ("SystemRoot", "COMSPEC", "WINDIR"):
        if os.environ.get(key):
            result[key] = os.environ[key]
    return result


def run(runtime: Path) -> dict:
    runtime = runtime.resolve()
    state_path = runtime / "cycle.json"
    if state_path.exists():
        raise SuccessionError("v2.2 stable action already completed; never repeat it")
    runtime.mkdir(parents=True, exist_ok=True)
    parent_path = ROOT / EDITABLE_PATH
    active_pointer = ROOT / "stoe-hermes" / "releases" / "active_release.json"
    parent = parent_path.read_text(encoding="utf-8")
    if sha256_bytes(parent.encode("utf-8")) != EXPECTED_PARENT_SHA256:
        raise SuccessionError("trusted parent identity changed")
    proposal_path = ROOT / "stoe-hermes" / "evidence" / "v2_2" / "v2_1_candidate_patch.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    sealed, candidate, validation = validate_code_v2_2(proposal, parent, EDITABLE_PATH)
    if validation["candidate_sha256"] != EXPECTED_CANDIDATE_SHA256:
        raise SuccessionError("reproduced candidate identity changed")
    if validation["grandfathered_count"] != 1:
        raise SuccessionError("unexpected inherited forbidden-node count")

    artifact_root = runtime / "artifacts"
    artifact_root.mkdir(parents=True)
    candidate_artifact = artifact_root / "context_renderer.py"
    candidate_artifact.write_text(candidate, encoding="utf-8", newline="\n")
    atomic_json(artifact_root / "sealed_patch.json", sealed)
    atomic_json(artifact_root / "validation.json", validation)

    candidate_source = runtime / "candidate" / "src"
    package = candidate_source / "stoe_hermes"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("\"\"\"Inactive v2.2 evaluation package.\"\"\"\n", encoding="utf-8", newline="\n")
    evaluation_target = package / "context_renderer.py"
    evaluation_target.write_text(candidate, encoding="utf-8", newline="\n")
    env = minimal_environment(runtime, candidate_source)
    tests = [
        {"name": "syntax", **run_bounded([sys.executable, "-m", "py_compile", str(evaluation_target)], cwd=candidate_source, env=env, timeout=20, output_limit=100_000)},
        {"name": "established_protected_behavior", **run_bounded([sys.executable, "-c", protected_check()], cwd=candidate_source, env=env, timeout=20, output_limit=100_000)},
    ]
    passed = all(item["passed"] for item in tests)
    pointer_hash = sha256_file(active_pointer)
    if sha256_file(parent_path) != EXPECTED_PARENT_SHA256:
        raise SuccessionError("active adapter changed during candidate evaluation")
    if sha256_file(active_pointer) != pointer_hash:
        raise SuccessionError("active release pointer changed during candidate evaluation")
    state = {
        "action_id": ACTION_ID,
        "status": "awaiting_author_approval" if passed else "failed_conserved",
        "validator": {
            "method": "normalized_ast_prefix_and_structural_path",
            "grandfathered": validation["grandfathered_forbidden_nodes"],
        },
        "candidate": {
            "source": "exact_v2_1_inert_patch",
            "proposal_path": str(proposal_path),
            "proposal_sha256": sha256_file(proposal_path),
            "parent_sha256": EXPECTED_PARENT_SHA256,
            "candidate_sha256": EXPECTED_CANDIDATE_SHA256,
            "artifact_path": str(candidate_artifact),
            "artifact_sha256": sha256_file(candidate_artifact),
            "diff_sha256": sha256_bytes(diff_text(parent, candidate).encode("utf-8")),
        },
        "protected_evaluation": {
            "protocol": "unchanged_v2_1_withheld_focused_check",
            "passed": passed,
            "tests": tests,
            "candidate_executed_after_static_validation": True,
            "isolation": "monitored subprocess under caller identity; not an OS sandbox",
        },
        "active_release": {
            "pointer_sha256": pointer_hash,
            "context_renderer_sha256": EXPECTED_PARENT_SHA256,
            "activation_status": "unchanged_inactive_candidate",
            "rollback_target": "hermes-a-bb924730743c",
        },
        "model_calls": 0,
    }
    atomic_json(state_path, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=ROOT / "agent" / "runtime" / "hermes_ab_v2_2")
    args = parser.parse_args()
    state = run(args.runtime)
    print(json.dumps({
        "status": state["status"],
        "candidate_sha256": state["candidate"]["candidate_sha256"],
        "grandfathered": state["validator"]["grandfathered"],
        "protected_evaluation": state["protected_evaluation"],
        "activation_status": state["active_release"]["activation_status"],
        "model_calls": state["model_calls"],
    }, indent=2))
    return 0 if state["status"] == "awaiting_author_approval" else 2


if __name__ == "__main__":
    raise SystemExit(main())
