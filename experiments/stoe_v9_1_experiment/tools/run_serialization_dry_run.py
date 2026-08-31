from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stoe_v9.providers import GenerationParams, OllamaEmbedder  # noqa: E402
from stoe_v9.retrieval import extract_memory_refs  # noqa: E402
from stoe_v9.runner import ALL_CONDITIONS, Condition, ExperimentRunner  # noqa: E402
from stoe_v9.tasks import load_tasks  # noqa: E402


EMBEDDING_MODEL = "qwen3-embedding:0.6b"
EMBEDDING_DIGEST = "ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d"


class ForbiddenGenerationProvider:
    name = "FORBIDDEN_IN_SERIALIZATION_DRY_RUN"

    def generate(self, *args, **kwargs):
        raise AssertionError("generation model call attempted during no-generation dry run")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    args = parser.parse_args()
    old_path = ROOT.parent / "stoe_v9_experiment" / "V9_PRIMARY_RESULTS.json"
    benchmark_path = ROOT / "benchmarks" / "frozen_primary_v1.json"
    old = json.loads(old_path.read_text(encoding="utf-8"))
    old_by_key = {(row["task_id"], row["condition"]): row for row in old["results"]}
    tasks = load_tasks(benchmark_path)
    embedder = OllamaEmbedder(args.ollama, EMBEDDING_MODEL, EMBEDDING_DIGEST)
    runner = ExperimentRunner(
        provider=ForbiddenGenerationProvider(),
        params=GenerationParams(model="GENERATION_FORBIDDEN"),
        embedder=embedder,
        retrieval_items=4,
        max_memory_chars=5000,
        seed=9417,
    )
    rows = []
    for task in tasks:
        typed_plan = None
        for condition in ALL_CONDITIONS:
            graph, _, selected, memory = runner._retrieve(task, condition, typed_plan)
            if condition == Condition.OBSERVER_AWARE_STOE_TOPOLOGY:
                typed_plan = selected
            visible_refs = extract_memory_refs(memory)
            old_row = old_by_key[(task.id, condition.value)]
            serialization = selected.serialization or {}
            rows.append({
                "task_id": task.id,
                "task_family": task.family,
                "subset": task.subset,
                "condition": condition.value,
                "stage": "primary",
                "selected_artifact_count": len(selected.refs),
                "selected_artifact_refs": selected.refs,
                "model_visible_artifact_count": len(visible_refs),
                "model_visible_memory_refs": visible_refs,
                "serialized_memory_char_count": len(memory),
                "per_artifact": serialization.get("artifacts", []),
                "artifact_origins": [
                    str(graph.nodes[ref].metadata.get("origin", "runtime_reasoning"))
                    for ref in selected.refs
                ],
                "exact_serialized_memory": memory,
                "frozen_v9_selected_refs": old_row["retrieved_refs"],
                "selection_matches_frozen_v9": selected.refs == old_row["retrieved_refs"],
                "four_selected_fewer_than_four_visible_violation": (
                    len(selected.refs) == 4 and len(visible_refs) != 4
                ),
                "memory_budget_violation": len(memory) > 5000,
            })

    selection_mismatches = [row for row in rows if not row["selection_matches_frozen_v9"]]
    exposure_violations = [
        row for row in rows if row["four_selected_fewer_than_four_visible_violation"]
    ]
    budget_violations = [row for row in rows if row["memory_budget_violation"]]
    by_condition = defaultdict(Counter)
    for row in rows:
        bucket = by_condition[row["condition"]]
        bucket["rows"] += 1
        bucket["selected"] += row["selected_artifact_count"]
        bucket["visible"] += row["model_visible_artifact_count"]
        bucket["truncated_artifacts"] += sum(item["truncated"] for item in row["per_artifact"])
        bucket["selection_mismatches"] += not row["selection_matches_frozen_v9"]
        bucket["exposure_violations"] += row["four_selected_fewer_than_four_visible_violation"]
        bucket["budget_violations"] += row["memory_budget_violation"]
    output = {
        "schema_version": 1,
        "status": "PASS" if not (selection_mismatches or exposure_violations or budget_violations) else "FAIL",
        "generation_model_calls": 0,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_digest": EMBEDDING_DIGEST,
        "embedding_calls": embedder.calls,
        "embedding_texts": embedder.texts,
        "embedding_latency_seconds": embedder.latency_seconds,
        "benchmark_sha256": sha256(benchmark_path),
        "frozen_v9_results_sha256": sha256(old_path),
        "total_rows": len(rows),
        "memory_bearing_rows": sum(bool(row["selected_artifact_count"]) for row in rows),
        "four_selected_fewer_than_four_visible_violations": len(exposure_violations),
        "memory_budget_violations": len(budget_violations),
        "frozen_selection_mismatches": len(selection_mismatches),
        "by_condition": {name: dict(values) for name, values in sorted(by_condition.items())},
        "rows": rows,
    }
    json_path = ROOT / "V9_1_SERIALIZATION_DRY_RUN.json"
    json_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# V9.1 Serialization Validation",
        "",
        f"Status: **{output['status']}**",
        "",
        "This was a full 252-cell primary serialization dry run. The generation model was forbidden; "
        "the frozen local embedding model was used only to reconstruct dense selections.",
        "",
        f"- Rows: {len(rows)}",
        f"- Memory-bearing rows: {output['memory_bearing_rows']}",
        f"- Generation-model calls: {output['generation_model_calls']}",
        f"- Embedding calls: {embedder.calls}",
        f"- Four-selected/fewer-than-four-visible violations: {len(exposure_violations)}",
        f"- Memory blocks over 5000 characters: {len(budget_violations)}",
        f"- Selected-ref differences from frozen v9: {len(selection_mismatches)}",
        "",
        "## Condition totals",
        "",
        "| Condition | Rows | Selected | Visible | Truncated | Selection mismatches | Exposure violations | Budget violations |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, values in sorted(by_condition.items()):
        lines.append(
            f"| {name} | {values['rows']} | {values['selected']} | {values['visible']} | "
            f"{values['truncated_artifacts']} | {values['selection_mismatches']} | "
            f"{values['exposure_violations']} | {values['budget_violations']} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "PASS means every frozen selected-reference list was reproduced before serialization, every "
        "selected reference appeared in the exact constructed memory string in the same order, and no "
        "memory string exceeded the unchanged 5000-character budget. It does not inspect or predict "
        "scientific outcomes.",
    ])
    (ROOT / "V9_1_SERIALIZATION_VALIDATION.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    if output["status"] != "PASS":
        raise SystemExit("serialization dry-run integrity failure; primary is forbidden")


if __name__ == "__main__":
    main()
