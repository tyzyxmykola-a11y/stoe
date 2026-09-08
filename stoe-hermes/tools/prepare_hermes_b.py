from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_hermes.succession import (
    ReleaseRecord,
    atomic_json,
    create_isolated_profile,
    expose_integration_plugin,
    sha256_bytes,
    sha256_file,
    inspect_checkout,
)


ACTION_ID = "checkpoint:hermes-ab-v2-clean-base"
HERMES_SHA = "bb924730743cc05934bf0dfd188abdfdb46c03c2"
SPARSE_PATHS = (
    "acp_adapter", "agent", "assets", "cron", "gateway", "hermes_cli", "locales",
    "native", "optional-mcps", "optional-skills", "plugins", "providers", "skills",
    "tools", "tui_gateway",
)


def materialize_sparse_commit(source_repo: Path, destination: Path) -> dict:
    """Build B from the pinned object without changing the immutable v1 supervisor."""
    source = inspect_checkout(source_repo)
    if source["head_sha"] != HERMES_SHA:
        raise RuntimeError("active source HEAD does not match the pinned Hermes A commit")
    destination.parent.mkdir(parents=True, exist_ok=True)
    commands = (
        ["git", "clone", "--no-hardlinks", "--no-checkout", str(source_repo), str(destination)],
        ["git", "sparse-checkout", "init", "--cone"],
        ["git", "sparse-checkout", "set", *SPARSE_PATHS],
        ["git", "-c", "core.longpaths=true", "checkout", "--force", "--detach", HERMES_SHA],
    )
    for index, command in enumerate(commands):
        cwd = destination.parent if index == 0 else destination
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120, check=False)
        if result.returncode:
            raise RuntimeError(f"clean B construction failed at stage {index}: {result.stderr[:500]}")
    candidate = inspect_checkout(destination)
    if candidate["head_sha"] != HERMES_SHA or not candidate["clean"]:
        raise RuntimeError("sparse candidate B is not a clean pinned checkout")
    return {
        "candidate_checkout": candidate,
        "sparse_paths": list(SPARSE_PATHS),
        "source_checkout": source,
        "activation_blockers": (["active_source_dirty"] if not source["clean"] else [])
        + (["active_source_divergent"] if source["upstream_relation"] == "divergent" else []),
    }


def create_b_venv(environment_root: Path) -> dict:
    if environment_root.exists():
        raise RuntimeError("candidate environment already exists")
    venv.EnvBuilder(with_pip=False, clear=False, symlinks=False, system_site_packages=True).create(environment_root)
    python_path = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return {
        "environment_root": str(environment_root.resolve()),
        "python": str(python_path.resolve()),
        "python_sha256": sha256_file(python_path),
        "system_site_packages": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-repo", type=Path, required=True)
    parser.add_argument("--skill-dir", type=Path, required=True)
    args = parser.parse_args()
    runtime = ROOT / "agent" / "runtime" / "hermes_ab_v2"
    manifest_path = runtime / "clean_base.json"
    if manifest_path.exists():
        print(manifest_path.read_text(encoding="utf-8"))
        return 0
    allowed_preserved = {"failed_partial_checkout_longpaths", "failed_partial_case_collision"}
    if runtime.exists() and any(path.name not in allowed_preserved for path in runtime.iterdir()):
        raise RuntimeError("partial clean-base construction requires explicit forensic recovery")
    runtime.mkdir(parents=True, exist_ok=True)
    b_root = runtime / "candidate_B"
    b_root.mkdir()
    assembly = materialize_sparse_commit(args.hermes_repo.resolve(), b_root / "hermes-agent")
    integration = b_root / "stoe-integration"
    shutil.copytree(ROOT / "stoe-hermes", integration, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    environment = create_b_venv(b_root / "venv")
    profile = create_isolated_profile(
        b_root / "profile", candidate_cwd=b_root / "hermes-agent",
        python_command=environment["python"],
        mcp_server=ROOT / "plugins" / "stoe-memory" / "server.py",
        skill_dir=args.skill_dir.resolve(),
    )
    loader = expose_integration_plugin(Path(profile["profile_root"]), integration)
    fingerprint_input = {"assembly": assembly, "environment": environment, "profile": profile, "loader": loader}
    fingerprint = sha256_bytes(json.dumps(fingerprint_input, sort_keys=True).encode("utf-8"))
    release = ReleaseRecord(
        release_id="hermes-b-base-bb924730743c", source_repository=str(args.hermes_repo.resolve()),
        commit_sha=HERMES_SHA, parent_release="hermes-a-bb924730743c",
        hermes_version="0.20.3", integration_plugin_version="0.1.0",
        model_configuration={}, configuration_hash=profile["config_sha256"],
        environment_fingerprint=fingerprint, candidate_status="candidate", activation_status="inactive",
        rollback_target="hermes-a-bb924730743c", creation_action_id=ACTION_ID,
        activation_blockers=assembly["activation_blockers"],
    )
    value = {"action_id": ACTION_ID, "release": release.as_dict(), "assembly": assembly, "profile": profile, "environment": environment, "loader": loader}
    atomic_json(manifest_path, value)
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
