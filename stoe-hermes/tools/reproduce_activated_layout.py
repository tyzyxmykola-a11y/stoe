from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_hermes.bounded_execution import run_bounded_preserved  # noqa: E402
from stoe_hermes.succession import SuccessionError, atomic_json, sha256_file  # noqa: E402


ACTION_ID = "diagnostic:hermes-v2.2-activated-layout-v1"
PARENT_SHA = "b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155"
CANDIDATE_SHA = "fc16fd51028967cd9972332ec671f8a3bb0c72815343a495df502cafd5d052ff"
PARENT_RELEASE = "hermes-a-bb924730743c"
CANDIDATE_RELEASE = "hermes-b-fc16fd510289"


def run(runtime: Path) -> dict:
    runtime = runtime.resolve()
    state_path = runtime / "diagnostic.json"
    if state_path.exists():
        raise SuccessionError("activated-layout diagnostic stable action already completed")
    runtime.mkdir(parents=True, exist_ok=True)
    production_source = ROOT / "stoe-hermes" / "src" / "stoe_hermes" / "context_renderer.py"
    production_pointer = ROOT / "stoe-hermes" / "releases" / "active_release.json"
    source_before = sha256_file(production_source)
    pointer_before = sha256_file(production_pointer)
    if source_before != PARENT_SHA or json.loads(production_pointer.read_text(encoding="utf-8"))["release_id"] != PARENT_RELEASE:
        raise SuccessionError("production Hermes A identity is not intact")

    fixture = runtime / "fixture"
    if fixture.exists():
        raise SuccessionError("disposable fixture already exists")
    ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc")
    shutil.copytree(ROOT / "stoe-hermes", fixture / "stoe-hermes", ignore=ignore)
    shutil.copytree(ROOT / "plugins" / "stoe-memory", fixture / "plugins" / "stoe-memory", ignore=ignore)
    shutil.copytree(ROOT / "agent" / "src", fixture / "agent" / "src", ignore=ignore)
    fixture_source = fixture / "stoe-hermes" / "src" / "stoe_hermes" / "context_renderer.py"
    fixture_artifact = fixture / "stoe-hermes" / "releases" / CANDIDATE_RELEASE / "context_renderer.py"
    fixture_pointer = fixture / "stoe-hermes" / "releases" / "active_release.json"
    if sha256_file(fixture_source) != PARENT_SHA or sha256_file(fixture_artifact) != CANDIDATE_SHA:
        raise SuccessionError("disposable source or candidate identity mismatch")
    atomic_json(fixture_pointer, {
        "release_id": CANDIDATE_RELEASE,
        "environment_fingerprint": "disposable-diagnostic-only",
        "rollback_target": PARENT_RELEASE,
        "editable_path": "stoe-hermes/src/stoe_hermes/context_renderer.py",
        "artifact_path": f"releases/{CANDIDATE_RELEASE}/context_renderer.py",
        "source_sha256": CANDIDATE_SHA,
        "authorization_policy_id": "standing:bounded-qualified-succession-v1",
    })
    temporary = runtime / "tmp"
    temporary.mkdir()
    env = dict(os.environ)
    env.update({
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str((fixture / "stoe-hermes" / "src").resolve()),
        "TEMP": str(temporary.resolve()),
        "TMP": str(temporary.resolve()),
    })
    execution = run_bounded_preserved(
        [sys.executable, "-m", "unittest", "discover", "-s", "stoe-hermes/tests", "-p", "test_*.py", "-v"],
        cwd=fixture,
        env=env,
        artifact_dir=runtime / "artifacts",
        label="activated_full_suite",
        timeout=60,
        output_limit=300_000,
    )
    production_after = {"source_sha256": sha256_file(production_source), "pointer_sha256": sha256_file(production_pointer)}
    if production_after != {"source_sha256": source_before, "pointer_sha256": pointer_before}:
        raise SuccessionError("disposable diagnostic changed production Hermes state")
    result = {
        "action_id": ACTION_ID,
        "status": "reproduced_pass" if execution["passed"] else "reproduced_failure",
        "identity": {"parent_sha256": PARENT_SHA, "candidate_sha256": CANDIDATE_SHA},
        "layout": {
            "fixture_root": str(fixture),
            "root_parent_immutable": sha256_file(fixture_source) == PARENT_SHA,
            "candidate_artifact_hash_bound": sha256_file(fixture_artifact) == CANDIDATE_SHA,
            "disposable_pointer_release": CANDIDATE_RELEASE,
            "production_release": PARENT_RELEASE,
        },
        "execution": execution,
        "production_before": {"source_sha256": source_before, "pointer_sha256": pointer_before},
        "production_after": production_after,
        "model_calls": 0,
    }
    atomic_json(state_path, result)
    return result


def main() -> int:
    runtime = ROOT / "agent" / "runtime" / "hermes_activation_diagnostic_v1"
    result = run(runtime)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
