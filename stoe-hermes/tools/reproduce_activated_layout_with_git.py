from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_hermes.bounded_execution import bounded_environment, run_bounded_preserved  # noqa: E402
from stoe_hermes.succession import SuccessionError, atomic_json, sha256_file  # noqa: E402


ACTION_ID = "diagnostic:hermes-v2.2-activated-layout-git-qualified-v3"
PARENT_SHA = "b1d11d98c8797c11fcd5ff7f8e337764580ca8c4a6c9ca66a32c336158041155"
PARENT_POINTER_SHA = "b6a1e4f89ea85a845eda7a8aa821135fa152cbbb126f3c294a6dc0a10e7c82c3"


def main() -> int:
    runtime = ROOT / "agent" / "runtime" / "hermes_activation_diagnostic_v3"
    state = runtime / "diagnostic.json"
    if state.exists():
        raise SuccessionError("Git-qualified diagnostic stable action already completed")
    runtime.mkdir(parents=True, exist_ok=True)
    fixture = ROOT / "agent" / "runtime" / "hermes_activation_diagnostic_v1" / "fixture"
    pointer = fixture / "stoe-hermes" / "releases" / "active_release.json"
    if json.loads(pointer.read_text(encoding="utf-8"))["release_id"] != "hermes-b-fc16fd510289":
        raise SuccessionError("disposable candidate pointer is not active")
    env, resolved_tools = bounded_environment(
        python_executable=sys.executable,
        pythonpath=fixture / "stoe-hermes" / "src",
        temporary=runtime / "tmp",
        required_tools=("git",),
    )
    execution = run_bounded_preserved(
        [sys.executable, "-m", "unittest", "discover", "-s", "stoe-hermes/tests", "-p", "test_*.py", "-v"],
        cwd=fixture, env=env, artifact_dir=runtime / "artifacts", label="activated_git_qualified",
        timeout=60, output_limit=300_000,
    )
    production = {
        "source_sha256": sha256_file(ROOT / "stoe-hermes" / "src" / "stoe_hermes" / "context_renderer.py"),
        "pointer_sha256": sha256_file(ROOT / "stoe-hermes" / "releases" / "active_release.json"),
    }
    if production != {"source_sha256": PARENT_SHA, "pointer_sha256": PARENT_POINTER_SHA}:
        raise SuccessionError("diagnostic changed production Hermes A")
    result = {
        "action_id": ACTION_ID,
        "status": "qualified" if execution["passed"] else "failed",
        "environment": {"minimal": True, "explicit_required_tools": resolved_tools},
        "layout": {"disposable_pointer_release": "hermes-b-fc16fd510289", "production_release": "hermes-a-bb924730743c"},
        "execution": execution,
        "production": production,
        "model_calls": 0,
    }
    atomic_json(state, result)
    print(json.dumps(result, indent=2))
    return 0 if execution["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
