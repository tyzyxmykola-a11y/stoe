from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SEED = "b327db6dbce9981ed21561b9d1a857e2e3786f1391d41edc0381fead79e59868"
EXPECTED_BENCHMARK = "8c74a2af83c98d79ff33db99180052a5e54566ec9f555c19093bade4a8a43b62"
EXPECTED_GENERATION = "5571076f3d70050487b26b341705799e0ab29b808164f90d20d4cf84f699d251"
EXPECTED_EMBEDDING = "ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def api(path: str) -> dict:
    with urllib.request.urlopen("http://127.0.0.1:11434" + path, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    checks: dict[str, bool] = {}
    details: dict[str, object] = {}
    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True, capture_output=True,
    )
    test_text = tests.stdout + tests.stderr
    checks["full_test_suite_50_of_50"] = tests.returncode == 0 and "Ran 50 tests" in test_text and "OK" in test_text
    details["test_summary"] = "50 passed, 0 failed" if checks["full_test_suite_50_of_50"] else test_text[-2000:]

    checks["canonical_seed_hash"] = digest(ROOT / "data/stoe_seed.json") == EXPECTED_SEED
    checks["benchmark_hash"] = digest(ROOT / "benchmarks/frozen_primary_v1.json") == EXPECTED_BENCHMARK
    old = ROOT.parent / "stoe_v9_experiment"
    checks["seed_byte_identical_to_v9"] = (ROOT / "data/stoe_seed.json").read_bytes() == (old / "data/stoe_seed.json").read_bytes()
    checks["benchmark_byte_identical_to_v9"] = (ROOT / "benchmarks/frozen_primary_v1.json").read_bytes() == (old / "benchmarks/frozen_primary_v1.json").read_bytes()
    checks["navigator_byte_identical_to_v9"] = (ROOT / "src/stoe_v9/navigator.py").read_bytes() == (old / "src/stoe_v9/navigator.py").read_bytes()
    checks["graph_seed_task_construction_identical"] = all(
        (ROOT / f"src/stoe_v9/{name}").read_bytes() == (old / f"src/stoe_v9/{name}").read_bytes()
        for name in ("graph.py", "seed.py", "tasks.py")
    )

    spec = json.loads((ROOT / "V9_1_EXPERIMENT_SPEC.json").read_text(encoding="utf-8"))
    old_spec = json.loads((ROOT / "V9_FROZEN_REFERENCE_SPEC.json").read_text(encoding="utf-8"))
    checks["condition_list_exact"] = spec["conditions"] == old_spec["conditions"] and len(spec["conditions"]) == 14
    checks["retrieval_k_exact"] = spec["information_budget"]["selected_artifacts_per_memory_condition"] == 4
    checks["memory_budget_exact"] = spec["information_budget"]["max_model_visible_memory_characters"] == 5000
    checks["generation_parameters_exact"] = spec["generation_parameters"] == {
        "temperature": 0.0, "top_p": 0.9, "top_k": 40, "seed": 9417,
        "num_ctx": 8192, "max_output_tokens": 192,
        "transport_retries_after_initial_attempt": 1,
        "model_calls_per_task_condition": 1, "think": False, "response_format": "json",
    }

    dry = json.loads((ROOT / "V9_1_SERIALIZATION_DRY_RUN.json").read_text(encoding="utf-8"))
    checks["dry_run_252_cells"] = dry["total_rows"] == 252
    checks["dry_run_zero_exposure_violations"] = dry["four_selected_fewer_than_four_visible_violations"] == 0
    checks["dry_run_zero_budget_violations"] = dry["memory_budget_violations"] == 0
    checks["dry_run_zero_selection_mismatches"] = dry["frozen_selection_mismatches"] == 0
    checks["dry_run_no_generation_calls"] = dry["generation_model_calls"] == 0

    tags = api("/api/tags")
    tag_map = {item.get("name"): item for item in tags.get("models", [])}
    checks["generation_model_digest_exact"] = tag_map.get("gemma4:26b", {}).get("digest") == EXPECTED_GENERATION
    checks["embedding_model_digest_exact"] = tag_map.get("qwen3-embedding:0.6b", {}).get("digest") == EXPECTED_EMBEDDING
    details["ollama_version"] = api("/api/version").get("version")
    details["generation_digest"] = tag_map.get("gemma4:26b", {}).get("digest")
    details["embedding_digest"] = tag_map.get("qwen3-embedding:0.6b", {}).get("digest")

    manifest_path = ROOT / "V9_1_PRE_PRIMARY_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_failures = [
        name for name, record in manifest["files"].items()
        if digest(ROOT / name) != record["sha256"] or (ROOT / name).stat().st_size != record["bytes"]
    ]
    checks["manifest_all_hashes_match"] = not manifest_failures
    details["manifest_sha256"] = digest(manifest_path)
    details["manifest_files"] = len(manifest["files"])
    details["manifest_failures"] = manifest_failures
    checks["frozen_components_byte_identical"] = all(
        value["byte_identical"] for value in manifest["unchanged_from_v9"].values()
    )
    checks["no_partial_primary_result"] = not (ROOT / "V9_1_PRIMARY_RESULTS.json").exists()
    checks["fresh_primary_state"] = not any(ROOT.glob("V9_1_PRIMARY_RESULTS*.partial*"))

    status = "PASS" if all(checks.values()) else "FAIL"
    lines = [
        "# V9.1 Final Preflight",
        "",
        f"Status: **{status}**",
        "",
        "V9.1 is a corrective replication. No primary generation call had occurred when this record was written.",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    lines += [f"| {name} | {'PASS' if value else 'FAIL'} |" for name, value in checks.items()]
    lines += [
        "", "## Recorded details", "",
        f"- Tests: {details['test_summary']}",
        f"- Ollama: {details['ollama_version']}",
        f"- Generation digest: `{details['generation_digest']}`",
        f"- Embedding digest: `{details['embedding_digest']}`",
        f"- Pre-primary manifest: `{details['manifest_sha256']}` ({details['manifest_files']} files)",
        f"- Manifest failures: {details['manifest_failures']}",
        "- Dry run: 252 cells; zero exposure violations; zero budget violations; zero frozen-selection mismatches; zero generation calls.",
        "", "If this file says FAIL, primary generation is forbidden.",
    ]
    (ROOT / "V9_1_PREFLIGHT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if status != "PASS":
        raise SystemExit("v9.1 preflight failed; primary generation forbidden")
    print(json.dumps({"status": status, "checks": len(checks), "manifest_sha256": details["manifest_sha256"]}))


if __name__ == "__main__":
    main()
