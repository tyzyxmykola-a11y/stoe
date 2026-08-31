from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / "stoe_v9_experiment"
EXCLUDED = {"__pycache__", ".pytest_cache"}
EXPLICIT = [
    "pyproject.toml",
    "requirements.txt",
    "V9_1_EXPERIMENT_SPEC.json",
    "V9_1_ENVIRONMENT.json",
    "V9_1_REPRODUCTION_COMMAND.txt",
    "V9_INVALIDATION_REPORT.md",
    "V9_CONTEXT_EXPOSURE_AUDIT.json",
    "V9_CONTEXT_EXPOSURE_AUDIT.md",
    "V9_1_SERIALIZATION_DRY_RUN.json",
    "V9_1_SERIALIZATION_VALIDATION.md",
    "V9_FROZEN_REFERENCE_SPEC.json",
    "V9_ARCHITECTURE_FROZEN.md",
    "V9_NAVIGATOR_SPEC_FROZEN.md",
    "V9_ABLATION_MATRIX_FROZEN.md",
    "data/stoe_seed.json",
    "benchmarks/frozen_primary_v1.json",
    "development_tasks/development_v1.json",
    "pilot_tasks/pilot_v1.json",
]
UNCHANGED_FROM_V9 = [
    "data/stoe_seed.json", "benchmarks/frozen_primary_v1.json",
    "development_tasks/development_v1.json", "pilot_tasks/pilot_v1.json",
    "src/stoe_v9/__init__.py", "src/stoe_v9/__main__.py", "src/stoe_v9/cli.py",
    "src/stoe_v9/graph.py", "src/stoe_v9/navigator.py", "src/stoe_v9/seed.py",
    "src/stoe_v9/tasks.py", "tests/test_ablations.py", "tests/test_navigator.py",
    "tests/test_runner.py", "tests/test_seed.py", "tests/test_tasks.py",
]
INTENDED_CHANGED_SOURCE = [
    "src/stoe_v9/models.py", "src/stoe_v9/retrieval.py",
    "src/stoe_v9/providers.py", "src/stoe_v9/runner.py",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict:
    return {"sha256": digest(path), "bytes": path.stat().st_size}


def main() -> None:
    discovered = sorted(
        path for folder in (ROOT / "src", ROOT / "tests", ROOT / "tools")
        for path in folder.rglob("*")
        if path.is_file() and not (set(path.parts) & EXCLUDED)
    )
    paths = sorted(set([ROOT / name for name in EXPLICIT] + discovered))
    unchanged = {}
    for name in UNCHANGED_FROM_V9:
        new_path, old_path = ROOT / name, OLD / name
        unchanged[name] = {
            "v9_sha256": digest(old_path),
            "v9_1_sha256": digest(new_path),
            "byte_identical": old_path.read_bytes() == new_path.read_bytes(),
        }
    changed = {}
    for name in INTENDED_CHANGED_SOURCE:
        new_path, old_path = ROOT / name, OLD / name
        changed[name] = {
            "v9_sha256": digest(old_path),
            "v9_1_sha256": digest(new_path),
            "intended_reason": "serializer/exposure accounting or exact-final-input assertion support",
        }
    if not all(value["byte_identical"] for value in unchanged.values()):
        raise SystemExit("unintended v9/v9.1 byte difference in frozen component")
    payload = {
        "schema_version": 1,
        "status": "V9_1_PRE_PRIMARY_FROZEN_PRIMARY_NOT_RUN",
        "workspace_git_state": "NO_GIT_REPOSITORY_PRESENT",
        "historical_v9_status": "V9_PRIMARY_INVALID_CONTEXT_BUDGET",
        "scientific_change_boundary": "post-selection serialization and truthful exposure accounting only",
        "unchanged_from_v9": unchanged,
        "intended_changed_source": changed,
        "files": {
            path.relative_to(ROOT).as_posix(): record(path) for path in paths
        },
    }
    output = ROOT / "V9_1_PRE_PRIMARY_MANIFEST.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "files": len(paths), "unchanged_verified": len(unchanged)}))


if __name__ == "__main__":
    main()
