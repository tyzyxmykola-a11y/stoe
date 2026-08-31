from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "V9_PRIMARY_RESULTS.json"
SPEC_PATH = ROOT / "V9_EXPERIMENT_SPEC.json"
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 9417
OA = "OBSERVER_AWARE_STOE_TOPOLOGY"
QB = "QUERY_BLIND_TOPOLOGY"
DENSE = "DENSE_SEMANTIC_MEMORY"
BM25 = "BM25_MEMORY"
NO_SEED = "OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED"
CHIMERA = "OBSERVER_AWARE_STOE_CHIMERA_SEED"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def rows_for(rows: list[dict], condition: str, subset: str = "all") -> list[dict]:
    selected = [row for row in rows if row["condition"] == condition]
    if subset != "all":
        selected = [row for row in selected if row["subset"] == subset]
    return selected


def paired(rows: list[dict], left: str, right: str, subset: str = "all") -> list[tuple[dict, dict]]:
    a = {row["task_id"]: row for row in rows_for(rows, left, subset)}
    b = {row["task_id"]: row for row in rows_for(rows, right, subset)}
    if set(a) != set(b):
        raise ValueError((left, right, subset, set(a) ^ set(b)))
    return [(a[task_id], b[task_id]) for task_id in a]


def exact_paired_p(left_only: int, right_only: int) -> float:
    n = left_only + right_only
    if n == 0:
        return 1.0
    lower = min(left_only, right_only)
    tail = sum(math.comb(n, k) for k in range(lower + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def cluster_bootstrap_ci(pairs: list[tuple[dict, dict]]) -> tuple[float, float]:
    clusters: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for pair in pairs:
        clusters[pair[0]["family"]].append(pair)
    names = sorted(clusters)
    rng = random.Random(BOOTSTRAP_SEED)
    values = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sampled = [rng.choice(names) for _ in names]
        observations = [pair for name in sampled for pair in clusters[name]]
        values.append(sum(int(a["exact_success"]) - int(b["exact_success"]) for a, b in observations) / len(observations))
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def comparison(rows: list[dict], left: str, right: str, subset: str) -> dict:
    pairs = paired(rows, left, right, subset)
    left_success = sum(a["exact_success"] for a, _ in pairs)
    right_success = sum(b["exact_success"] for _, b in pairs)
    left_only = sum(a["exact_success"] and not b["exact_success"] for a, b in pairs)
    right_only = sum(b["exact_success"] and not a["exact_success"] for a, b in pairs)
    ci_low, ci_high = cluster_bootstrap_ci(pairs)
    return {
        "left": left,
        "right": right,
        "subset": subset,
        "n": len(pairs),
        "left_success": left_success,
        "right_success": right_success,
        "left_rate": left_success / len(pairs),
        "right_rate": right_success / len(pairs),
        "absolute_difference": (left_success - right_success) / len(pairs),
        "left_only": left_only,
        "right_only": right_only,
        "discordant_pairs": left_only + right_only,
        "exact_paired_p_two_sided": exact_paired_p(left_only, right_only),
        "family_cluster_bootstrap_95_ci": [ci_low, ci_high],
    }


def condition_metrics(rows: list[dict], condition: str) -> dict:
    selected = rows_for(rows, condition)
    attempts = [int(row.get("provider_metadata", {}).get("attempt", 1)) for row in selected]
    focal_ranks = [row["focal_ip_rank"] for row in selected if row["focal_ip_rank"] is not None]
    return {
        "condition": condition,
        "n": len(selected),
        "successes": sum(row["exact_success"] for row in selected),
        "success_rate": sum(row["exact_success"] for row in selected) / len(selected),
        "targeted_successes": sum(row["exact_success"] for row in selected if row["subset"] == "topology_targeted"),
        "targeted_n": sum(row["subset"] == "topology_targeted" for row in selected),
        "control_successes": sum(row["exact_success"] for row in selected if row["subset"] == "negative_control"),
        "control_n": sum(row["subset"] == "negative_control" for row in selected),
        "input_tokens": sum(row["input_tokens"] for row in selected),
        "output_tokens": sum(row["output_tokens"] for row in selected),
        "total_tokens": sum(row["input_tokens"] + row["output_tokens"] for row in selected),
        "solved_per_1k_tokens": 1000 * sum(row["exact_success"] for row in selected) / max(1, sum(row["input_tokens"] + row["output_tokens"] for row in selected)),
        "latency_seconds": sum(row["latency_seconds"] for row in selected),
        "mean_latency_seconds": sum(row["latency_seconds"] for row in selected) / len(selected),
        "provider_errors": sum(bool(row["provider_error"]) for row in selected),
        "parse_errors": sum(bool(row["parse_error"]) for row in selected),
        "internal_id_contamination": sum(row["internal_id_contamination"] for row in selected),
        "transport_retries": sum(max(0, attempt - 1) for attempt in attempts),
        "model_calls": len(selected),
        "realized_artifact_counts": dict(sorted(Counter(row["realized_artifact_count"] for row in selected).items())),
        "focal_retrieval_count": len(focal_ranks),
        "focal_retrieval_rate": len(focal_ranks) / len(selected),
        "mean_focal_rank_when_retrieved": sum(focal_ranks) / len(focal_ranks) if focal_ranks else None,
        "seed_artifacts_selected": sum(origin == "canonical_seed" for row in selected for origin in row["retrieved_origins"]),
    }


def selected_traces(row: dict) -> list[dict]:
    return [trace for trace in row["navigation_trace"] if trace["selected"]]


def navigation_metrics(rows: list[dict]) -> dict:
    oa_rows = rows_for(rows, OA)
    qb_rows = {row["task_id"]: row for row in rows_for(rows, QB)}
    changed = []
    improved = []
    hurt = []
    neutral = []
    state_paths = 0
    critical_paths = 0
    for row in oa_rows:
        other = qb_rows[row["task_id"]]
        if row["retrieved_refs"] != other["retrieved_refs"]:
            changed.append(row["task_id"])
            delta = int(row["exact_success"]) - int(other["exact_success"])
            (improved if delta > 0 else hurt if delta < 0 else neutral).append(row["task_id"])
        traces = selected_traces(row)
        if any("invalidates" in trace["edge_types"] for trace in traces):
            state_paths += 1
        if any("invalidates" in trace["edge_types"] and "rejected_by" in trace["edge_types"] for trace in traces):
            critical_paths += 1
    return {
        "observer_context_changed_vs_query_blind": len(changed),
        "changed_task_ids": changed,
        "changes_improved_answer": len(improved),
        "improved_task_ids": improved,
        "changes_hurt_answer": len(hurt),
        "hurt_task_ids": hurt,
        "changes_same_correctness": len(neutral),
        "neutral_task_ids": neutral,
        "observer_selected_state_change_path_tasks": state_paths,
        "observer_selected_critical_invalidation_rejection_path_tasks": critical_paths,
    }


def seed_metrics(rows: list[dict], seed_raw: dict) -> dict:
    names = {f"SEED_{node_id}": node.get("name", node.get("content", node_id)) for node_id, node in seed_raw["nodes"].items()}
    native = rows_for(rows, OA)
    absent = {row["task_id"]: row for row in rows_for(rows, NO_SEED)}
    counts = Counter(ref for row in native for ref, origin in zip(row["retrieved_refs"], row["retrieved_origins"]) if origin == "canonical_seed")
    exposed_rows = [row for row in native if "canonical_seed" in row["retrieved_origins"]]
    unexposed_rows = [row for row in native if "canonical_seed" not in row["retrieved_origins"]]
    displacement = {}
    bridge_events = []
    for row in native:
        no_seed_row = absent[row["task_id"]]
        native_runtime = {ref for ref, origin in zip(row["retrieved_refs"], row["retrieved_origins"]) if origin != "canonical_seed"}
        missing = [ref for ref in no_seed_row["retrieved_refs"] if ref not in native_runtime]
        if missing:
            displacement[row["task_id"]] = missing
        exposed_seed_refs = {ref for ref, origin in zip(row["retrieved_refs"], row["retrieved_origins"]) if origin == "canonical_seed"}
        for trace in selected_traces(row):
            if trace["origin"] == "canonical_seed":
                continue
            seed_path_refs = {
                step["from"] for step in trace["path"] if str(step["from"]).startswith("SEED_")
            } | {
                step["to"] for step in trace["path"] if str(step["to"]).startswith("SEED_")
            }
            hidden_bridges = sorted(seed_path_refs - exposed_seed_refs)
            if hidden_bridges:
                bridge_events.append({"task_id": row["task_id"], "candidate_ip": trace["candidate_ip"], "unexposed_seed_bridges": hidden_bridges})
    return {
        "native_seed_artifacts_selected": sum(counts.values()),
        "native_tasks_with_seed_exposure": len(exposed_rows),
        "native_tasks_without_seed_exposure": len(unexposed_rows),
        "success_with_seed_exposure": sum(row["exact_success"] for row in exposed_rows),
        "success_rate_with_seed_exposure": sum(row["exact_success"] for row in exposed_rows) / len(exposed_rows) if exposed_rows else None,
        "success_without_seed_exposure": sum(row["exact_success"] for row in unexposed_rows),
        "success_rate_without_seed_exposure": sum(row["exact_success"] for row in unexposed_rows) / len(unexposed_rows) if unexposed_rows else None,
        "selected_core_ips": [
            {"ref": ref, "name": names.get(ref, ref), "count": count}
            for ref, count in counts.most_common()
        ],
        "runtime_artifacts_displaced_vs_no_seed": sum(len(items) for items in displacement.values()),
        "displacement_by_task": displacement,
        "unexposed_seed_bridge_events": bridge_events,
        "single_stage_label": "final_decision",
    }


def counterfactual_metrics(data: dict, rows: list[dict]) -> dict:
    replays = data["counterfactual_replays"]
    intervention_rows = [item for replay in replays for item in replay["interventions"]]
    control_metadata = [replay.get("control_provider_metadata", {}) for replay in replays]
    result = {
        "successful_observer_cases_replayed": len(replays),
        "generation_calls": len(replays) + len(intervention_rows),
        "control_calls": len(replays),
        "intervention_calls": len(intervention_rows),
        "input_tokens": sum(int(meta.get("prompt_eval_count", 0)) for meta in control_metadata) + sum(item["input_tokens"] for item in intervention_rows),
        "output_tokens": sum(int(meta.get("eval_count", 0)) for meta in control_metadata) + sum(item["output_tokens"] for item in intervention_rows),
        "latency_seconds": sum(float(meta.get("total_duration_ns", 0)) / 1_000_000_000 for meta in control_metadata) + sum(item["latency_seconds"] for item in intervention_rows),
        "parse_errors": sum(bool(replay.get("control_parse_error")) for replay in replays) + sum(bool(item.get("parse_error")) for item in intervention_rows),
        "transport_retries": sum(max(0, int(meta.get("attempt", 1)) - 1) for meta in control_metadata) + sum(max(0, int(item.get("provider_metadata", {}).get("attempt", 1)) - 1) for item in intervention_rows),
        "classifications_by_intervention": {},
        "targeted_classifications_by_intervention": {},
        "replay_task_ids": [item["task_id"] for item in replays],
    }
    subset = {row["task_id"]: row["subset"] for row in rows_for(rows, OA)}
    names = sorted({item["intervention"] for replay in replays for item in replay["interventions"]})
    for name in names:
        result["classifications_by_intervention"][name] = dict(Counter(
            item["classification"] for replay in replays for item in replay["interventions"] if item["intervention"] == name
        ))
        result["targeted_classifications_by_intervention"][name] = dict(Counter(
            item["classification"] for replay in replays if subset[replay["task_id"]] == "topology_targeted"
            for item in replay["interventions"] if item["intervention"] == name
        ))
    return result


def success_criterion(rows: list[dict], data: dict) -> dict:
    observer_query = comparison(rows, OA, QB, "topology_targeted")
    observer_dense = comparison(rows, OA, DENSE, "topology_targeted")
    observer_dense_controls = comparison(rows, OA, DENSE, "negative_control")
    dense_by_task = {row["task_id"]: row for row in rows_for(rows, DENSE, "topology_targeted")}
    topology_only = [
        row["task_id"] for row in rows_for(rows, OA, "topology_targeted")
        if row["exact_success"] and not dense_by_task[row["task_id"]]["exact_success"]
    ]
    cf = {item["task_id"]: item for item in data["counterfactual_replays"]}
    supported = []
    for task_id in topology_only:
        replay = cf.get(task_id)
        if replay and any(
            item["classification"] in {"NECESSARY_FOR_SUCCESS", "CONTRIBUTORY"}
            for item in replay["interventions"]
        ):
            supported.append(task_id)
    mechanism_fraction = len(supported) / len(topology_only) if topology_only else 0.0
    checks = {
        "observer_over_query_blind_targeted": observer_query["absolute_difference"] > 0,
        "observer_over_dense_by_at_least_one_of_nine_targeted": observer_dense["left_success"] - observer_dense["right_success"] >= 1,
        "counterfactual_mechanism_fraction_at_least_25_percent": mechanism_fraction >= 0.25,
        "negative_control_guard_no_more_than_two_tasks_worse_than_dense": observer_dense_controls["right_success"] - observer_dense_controls["left_success"] <= 2,
    }
    return {
        "checks": checks,
        "all_required_met": all(checks.values()),
        "topology_only_targeted_task_ids": topology_only,
        "counterfactually_supported_topology_only_task_ids": supported,
        "counterfactual_mechanism_fraction": mechanism_fraction,
        "verdict": "SUPPORTED" if all(checks.values()) else "NOT SUPPORTED",
    }


def metric_table(metrics: list[dict]) -> str:
    lines = [
        "| Condition | Success | Targeted | Controls | Tokens | Solved/1k | Mean latency | Parse/provider/retries | Focal retrieved | Seed selected |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in metrics:
        lines.append(
            f"| {item['condition']} | {item['successes']}/{item['n']} ({pct(item['success_rate'])}) "
            f"| {item['targeted_successes']}/{item['targeted_n']} | {item['control_successes']}/{item['control_n']} "
            f"| {item['total_tokens']} | {item['solved_per_1k_tokens']:.3f} | {item['mean_latency_seconds']:.3f}s "
            f"| {item['parse_errors']}/{item['provider_errors']}/{item['transport_retries']} "
            f"| {item['focal_retrieval_count']}/{item['n']} | {item['seed_artifacts_selected']} |"
        )
    return "\n".join(lines)


def comparison_table(items: list[dict]) -> str:
    lines = [
        "| Comparison | Subset | Left | Right | Difference | 95% family-cluster CI | Discordant L:R | Exact p |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in items:
        low, high = item["family_cluster_bootstrap_95_ci"]
        lines.append(
            f"| {item['left']} vs {item['right']} | {item['subset']} | {item['left_success']}/{item['n']} "
            f"| {item['right_success']}/{item['n']} | {pct(item['absolute_difference'])} "
            f"| [{pct(low)}, {pct(high)}] | {item['left_only']}:{item['right_only']} "
            f"| {item['exact_paired_p_two_sided']:.6f} |"
        )
    return "\n".join(lines)


def main() -> None:
    data = read_json(RESULT_PATH)
    spec = read_json(SPEC_PATH)
    rows = data["results"]
    conditions = data["conditions"]
    metrics = [condition_metrics(rows, condition) for condition in conditions]
    comparisons = [
        comparison(rows, OA, DENSE, "topology_targeted"),
        comparison(rows, OA, QB, "all"),
        comparison(rows, OA, QB, "topology_targeted"),
        comparison(rows, OA, QB, "negative_control"),
        comparison(rows, OA, DENSE, "all"),
        comparison(rows, OA, DENSE, "negative_control"),
        comparison(rows, OA, BM25, "all"),
        comparison(rows, OA, BM25, "topology_targeted"),
        comparison(rows, OA, NO_SEED, "all"),
        comparison(rows, OA, NO_SEED, "topology_targeted"),
        comparison(rows, OA, CHIMERA, "all"),
        comparison(rows, OA, CHIMERA, "topology_targeted"),
    ]
    for ablation in [
        "OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES",
        "OBSERVER_AWARE_TOPOLOGY_UNTYPED",
        "OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES",
        "OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL",
        "OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE",
    ]:
        comparisons.append(comparison(rows, OA, ablation, "all"))

    navigation = navigation_metrics(rows)
    seed = seed_metrics(rows, read_json(ROOT / "data/stoe_seed.json"))
    counterfactual = counterfactual_metrics(data, rows)
    criterion = success_criterion(rows, data)

    family_rows = []
    for family in sorted({row["family"] for row in rows}):
        for condition in [OA, QB, DENSE, BM25, NO_SEED, CHIMERA]:
            selected = [row for row in rows if row["family"] == family and row["condition"] == condition]
            family_rows.append({
                "family": family,
                "condition": condition,
                "successes": sum(row["exact_success"] for row in selected),
                "n": len(selected),
                "targeted_success": next((row["exact_success"] for row in selected if row["subset"] == "topology_targeted"), None),
                "control_success": next((row["exact_success"] for row in selected if row["subset"] == "negative_control"), None),
            })

    stats = {
        "schema_version": 1,
        "analysis_status": "FROZEN_PRIMARY_COMPLETE",
        "raw_result_sha256": hashlib.sha256(RESULT_PATH.read_bytes()).hexdigest(),
        "conditions": metrics,
        "comparisons": comparisons,
        "navigation": navigation,
        "seed": seed,
        "counterfactual": counterfactual,
        "success_criterion": criterion,
        "family_results": family_rows,
    }
    write_json(ROOT / "V9_PRIMARY_ANALYSIS_DATA.json", stats)

    task_by_id = {task_id: index for index, task_id in enumerate(data["task_ids"])}
    raw_traces = []
    for row in rows:
        condition = row["condition"]
        seed_mode = row["field_seed_mode"]
        if condition == "NO_MEMORY":
            candidates = []
        elif row["navigation_trace"]:
            candidates = [trace["candidate_ip"] for trace in row["navigation_trace"]]
        else:
            candidates = list(row["retrieved_refs"])
        raw_traces.append({
            "task_order_index": task_by_id[row["task_id"]],
            "task_id": row["task_id"],
            "family": row["family"],
            "subset": row["subset"],
            "condition": condition,
            "stage": "final_decision",
            "prompt_sha256": hashlib.sha256(row["prompt"].encode("utf-8")).hexdigest(),
            "current_observer_state_ip": row["current_state_ip"],
            "current_goal": row["goal"],
            "candidate_ips_recorded": candidates,
            "candidate_origins": {trace["candidate_ip"]: trace["origin"] for trace in row["navigation_trace"]},
            "selected_ips": row["retrieved_refs"],
            "selected_origins": row["retrieved_origins"],
            "realized_artifact_count": row["realized_artifact_count"],
            "model_visible_memory_text": row["memory_context"],
            "navigation_trace": row["navigation_trace"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "latency_seconds": row["latency_seconds"],
            "retry_attempt": row["provider_metadata"].get("attempt", 1),
            "provider_error": row["provider_error"],
            "parse_error": row["parse_error"],
            "model_response": row["model_response_raw"],
            "parsed_answer": row["answer"],
            "correct": row["exact_success"],
            "used_memory_refs": row["used_memory_refs"],
            "seed_mode": seed_mode,
        })
    write_json(ROOT / "V9_PRIMARY_RAW_TRACES.json", {
        "schema_version": 1,
        "status": "FROZEN_PRIMARY_COMPLETE",
        "source_result": "V9_PRIMARY_RESULTS.json",
        "source_result_sha256": stats["raw_result_sha256"],
        "single_stage_protocol": "final_decision",
        "traces": raw_traces,
    })
    write_json(ROOT / "V9_PRIMARY_COUNTERFACTUAL_RESULTS.json", {
        "schema_version": 1,
        "status": "PREREGISTERED_COUNTERFACTUALS_COMPLETE",
        "source_result_sha256": stats["raw_result_sha256"],
        "replays": data["counterfactual_replays"],
        "summary": counterfactual,
    })

    family_lookup = {(item["family"], item["condition"]): item for item in family_rows}
    family_table_lines = []
    for family in sorted({item["family"] for item in family_rows}):
        values = []
        for condition in [OA, QB, DENSE, BM25, NO_SEED, CHIMERA]:
            item = family_lookup[(family, condition)]
            values.append(f"{item['successes']}/{item['n']} (T{'✓' if item['targeted_success'] else '✗'}, C{'✓' if item['control_success'] else '✗'})")
        family_table_lines.append(f"| {family} | " + " | ".join(values) + " |")

    statistical_md = f"""# V9 Primary Statistical Analysis

## Frozen primary results

The raw frozen run contains 18 distinct tasks in nine family clusters and 14 conditions (252 primary generation calls). The runner automatically completed counterfactuals after all primary rows. The raw file's inherited `status` string says `PILOT_ONLY_PRIMARY_NOT_RUN`; this is a frozen metadata-label defect. The file name, 18 frozen primary task IDs, 252 rows, exact Gemma digest, and invocation establish that it is the primary result. The raw file was not rewritten.

{metric_table(metrics)}

## Preregistered paired comparisons

{comparison_table(comparisons)}

The confirmatory strong comparator is dense semantic retrieval, fixed before the seed-aware pilot. On topology-targeted tasks observer-aware topology scored 9/9 versus dense 6/9: +33.3 percentage points, exact paired p={comparisons[0]['exact_paired_p_two_sided']:.3f}. Its family-cluster interval is [{pct(comparisons[0]['family_cluster_bootstrap_95_ci'][0])}, {pct(comparisons[0]['family_cluster_bootstrap_95_ci'][1])}]. This interval includes zero; the small clustered sample is inconclusive by conventional interval standards despite the positive point estimate.

Against query-blind topology, observer-aware scored 13/18 versus 3/18 overall and 9/9 versus 0/9 targeted. The targeted exact paired p is {comparisons[2]['exact_paired_p_two_sided']:.6f}. On negative controls, however, observer-aware scored 4/9 versus dense 9/9.

## Per-family results

Each family contributes one targeted task (T) and one negative control (C).

| Family | Observer | Query-blind | Dense | BM25 | No seed | Chimera |
|---|---|---|---|---|---|---|
{chr(10).join(family_table_lines)}

## Preregistered success criterion

- Observer-aware > query-blind on targeted: **{criterion['checks']['observer_over_query_blind_targeted']}**.
- Observer-aware exceeds dense by at least one targeted task: **{criterion['checks']['observer_over_dense_by_at_least_one_of_nine_targeted']}**.
- Counterfactual mechanism support ≥25% of topology-only targeted wins: **{criterion['checks']['counterfactual_mechanism_fraction_at_least_25_percent']}** ({pct(criterion['counterfactual_mechanism_fraction'])}).
- Negative-control guard, no more than two tasks worse than dense: **{criterion['checks']['negative_control_guard_no_more_than_two_tasks_worse_than_dense']}** (observer 4/9, dense 9/9; five-task deficit).

Because all four are required, the preregistered criterion is **NOT MET**. Frozen verdict: **{criterion['verdict']}**.

## Error and resource accounting

Across 252 primary rows there were {sum(item['provider_errors'] for item in metrics)} provider errors, {sum(item['parse_errors'] for item in metrics)} parse errors, and {sum(item['transport_retries'] for item in metrics)} transport retries. Every memory row exposed exactly four artifacts; NO_MEMORY exposed zero. Primary input plus output tokens totaled {sum(item['total_tokens'] for item in metrics):,}. Primary recorded generation latency totaled {sum(item['latency_seconds'] for item in metrics):.3f} seconds. Counterfactual calls are reported separately.

Family-cluster intervals use 10,000 percentile bootstrap resamples with frozen seed 9417. Exact paired p-values are two-sided binomial/McNemar tests over discordant task pairs. Nonsignificant results are not interpreted as equivalence.
"""
    (ROOT / "V9_PRIMARY_STATISTICAL_ANALYSIS.md").write_text(statistical_md, encoding="utf-8")

    cf_lines = []
    for name, counts in counterfactual["classifications_by_intervention"].items():
        cf_lines.append(f"| {name} | " + " | ".join(str(counts.get(label, 0)) for label in ["NECESSARY_FOR_SUCCESS", "CONTRIBUTORY", "NO_DETECTABLE_EFFECT", "COUNTERFACTUAL_IMPROVED", "INVALID_REPLAY"]) + " |")
    cf_report = f"""# V9 Primary Counterfactual Report

The preregistered replay system ran only after all 252 frozen primary rows completed. It replayed {counterfactual['successful_observer_cases_replayed']} successful observer-aware cases. Self-reported citations are not treated as causal evidence.

It made {counterfactual['generation_calls']} generation calls: {counterfactual['control_calls']} same-context controls and {counterfactual['intervention_calls']} interventions. These used {counterfactual['input_tokens'] + counterfactual['output_tokens']:,} total tokens and {counterfactual['latency_seconds']:.3f} recorded seconds, with {counterfactual['parse_errors']} parse errors and {counterfactual['transport_retries']} transport retries.

| Intervention | Necessary | Contributory | No effect | Improved | Invalid |
|---|---:|---:|---:|---:|---:|
{chr(10).join(cf_lines)}

All nine targeted observer-aware successes were replayed. The three topology-only targeted wins over dense were: {', '.join(criterion['topology_only_targeted_task_ids'])}. All three had at least one NECESSARY_FOR_SUCCESS or CONTRIBUTORY intervention, yielding mechanism support of {pct(criterion['counterfactual_mechanism_fraction'])} for this preregistered criterion.

These are pipeline interventions: removing a node or edge changes downstream retrieval and replacement context. They support dependence on the implemented graph/state-change mechanism but are not byte-identical single-sentence causal interventions.
"""
    (ROOT / "V9_PRIMARY_COUNTERFACTUAL_REPORT.md").write_text(cf_report, encoding="utf-8")

    core_lines = "\n".join(f"| {item['name']} | `{item['ref']}` | {item['count']} |" for item in seed["selected_core_ips"])
    seed_report = f"""# V9 Seed Analysis

## Preregistered comparisons

- Native canonical seed: 13/18 (72.2%), targeted 9/9, controls 4/9.
- Without core seed: 16/18 (88.9%), targeted 9/9, controls 7/9.
- Chimera seed: 12/18 (66.7%), targeted 9/9, controls 3/9.

Native minus no-seed was -16.7 percentage points overall. Native minus chimera was +5.6 points. Targeted performance was identical at 9/9 in all three, so seed differences occurred only on negative controls. The primary result therefore provides **no evidence that active canonical seed participation improves topology-targeted performance**. It shows that the present seed integration can reduce control-task performance.

## Retrieval behavior

Native observer-aware retrieval selected {seed['native_seed_artifacts_selected']} canonical-seed artifacts across {seed['native_tasks_with_seed_exposure']}/18 tasks. Because every native task exposed at least one seed IP, success/exposure correlation is not identifiable within that condition: there is no unexposed comparison group.

| Core IP | Ref | Selections |
|---|---|---:|
{core_lines}

Compared with the no-seed condition, seed-bearing native contexts omitted {seed['runtime_artifacts_displaced_vs_no_seed']} runtime artifact slots across tasks. There were {len(seed['unexposed_seed_bridge_events'])} recorded cases where a selected runtime candidate's path used a seed IP that was not itself exposed. All benchmark tasks have a single measured `final_decision` stage.

Native-vs-chimera does not isolate ontology truth. The chimera preserves vocabulary/content and relation-type counts but changes semantic plausibility and node-specific adjacency. The one-task native advantage is a small secondary point estimate, not evidence that native SToE organization is superior.
"""
    (ROOT / "V9_SEED_ANALYSIS.md").write_text(seed_report, encoding="utf-8")

    oa_map = {row["task_id"]: row for row in rows_for(rows, OA)}
    compare_conditions = [QB, DENSE, BM25, NO_SEED, CHIMERA]
    disagreement_lines = []
    for task_id in data["task_ids"]:
        oa_row = oa_map[task_id]
        cells = []
        for condition in compare_conditions:
            other = next(row for row in rows if row["task_id"] == task_id and row["condition"] == condition)
            cells.append("✓" if other["exact_success"] else "✗")
        disagreement_lines.append(
            f"| {task_id} | {oa_row['subset']} | {'✓' if oa_row['exact_success'] else '✗'} | " + " | ".join(cells) + f" | {oa_row['focal_ip_rank'] or '—'} | {', '.join(oa_row['retrieved_refs'])} |"
        )
    navigation_report = f"""# V9 Navigation Postmortem

## Observer-aware versus query-blind

Observer-aware changed the selected context on {navigation['observer_context_changed_vs_query_blind']}/18 tasks. Those changes improved correctness on {navigation['changes_improved_answer']} tasks, hurt it on {navigation['changes_hurt_answer']}, and left binary correctness unchanged on {navigation['changes_same_correctness']}. It selected a path containing `invalidates` on {navigation['observer_selected_state_change_path_tasks']}/18 tasks and a complete invalidation→rejected-by path on {navigation['observer_selected_critical_invalidation_rejection_path_tasks']}/18.

Observer-aware recovered all 9 targeted answers; query-blind recovered none. This strongly supports the narrow claim that the v9 observer/state-change navigator repairs the v8 graph-local navigation failure on this constructed targeted subset. It does not establish superiority over conventional retrieval overall: dense scored 15/18 versus observer-aware 13/18.

## Task-level matrix

| Task | Subset | Observer | Query-blind | Dense | BM25 | No seed | Chimera | Observer focal rank | Observer selected refs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(disagreement_lines)}

## Residual confounds

The observer policy is intentionally specialized for changed-constraint paths; negative controls expose its opportunity cost. Formal typed labels, supplied runtime-to-seed bridges, answer-bearing focal artifacts, and the shared three-edge targeted grammar remain confounds. Untyped tied native observer at 13/18, while removing state-change scoring scored 14/18 overall because it improved one control without losing targeted tasks. These results prevent attributing the full point gain to every named component.
"""
    (ROOT / "V9_NAVIGATION_POSTMORTEM.md").write_text(navigation_report, encoding="utf-8")

    final_report = f"""# SToE V9 Final Report

## A. Frozen primary result

The immutable primary completed 252 rows using frozen `gemma4:26b` and 18 tasks in nine independent family clusters. Observer-aware SToE topology scored **13/18 (72.2%)**. Frozen dense semantic retrieval scored **15/18 (83.3%)**; BM25 scored **14/18 (77.8%)**; query-blind topology scored **3/18 (16.7%)**.

On the topology-targeted subset, observer-aware scored **9/9**, dense **6/9**, BM25 **5/9**, and query-blind **0/9**. On negative controls, observer-aware scored **4/9**, dense **9/9**, BM25 **9/9**, and query-blind **3/9**.

The architecture therefore shows a strong domain boundary: observer-aware changed-state topology repaired the targeted v8-style navigation failure, but conventional retrieval remained better overall because topology performed poorly on controls.

## B. Preregistered secondary analyses

Native seed scored 13/18, no-seed 16/18, and chimera 12/18. All scored 9/9 targeted; differences were confined to controls. The current canonical-seed integration offered no detectable targeted benefit and was worse overall than runtime topology without the seed.

Ablations must be interpreted individually. Without failures collapsed to 3/18, supporting failed-history availability on targeted tasks. Randomized edges scored 3/18. Untyped tied native at 13/18. Without state-change scoring scored 14/18 overall and still 9/9 targeted, so the benchmark does not isolate a necessary contribution from that numerical score component once the structural path is present. Without query relevance tied native at 13/18.

## C. Counterfactual analyses

All 13 native observer successes were replayed. The three targeted wins unique versus dense all had a necessary or contributory graph intervention. This satisfies the preregistered mechanism-fraction component, while retaining the caveat that interventions change downstream retrieved context.

## D. Post-hoc observations

The canonical seed was exposed on every native task and displaced runtime artifacts. Its core vocabulary was not required for the 9/9 targeted result because no-seed also scored 9/9. The numerical state-change rank term was likewise not necessary for targeted success in this dataset, despite critical structural paths being used. These observations generate narrower follow-up hypotheses but do not alter frozen scores.

## Verdict

The preregistered all-required success criterion is **NOT MET** because observer-aware topology was five tasks worse than dense on nine negative controls, exceeding the allowed two-task deficit. Overall verdict: **NOT SUPPORTED** under the frozen rule.

Scientifically, the narrower v8→v9 architectural repair is supported on topology-targeted tasks, but superiority over strong conventional retrieval is not established. The canonical seed mechanism is not supported as beneficial in this benchmark. This says nothing about the truth or falsity of the broader SToE ontology.
"""
    (ROOT / "V9_FINAL_REPORT.md").write_text(final_report, encoding="utf-8")

    result_summary = f"""# V9 Result Summary

Model: gemma4:26b (`5571076f…9d251`)
Benchmark: frozen_primary_v1, SHA-256 `8c74a2af…a43b62`
N: 18 tasks, 9 family clusters
Primary comparison: observer-aware topology vs frozen dense semantic retrieval on 9 targeted tasks
Observer-aware targeted success: 9/9 (100.0%)
Dense targeted success: 6/9 (66.7%)
Targeted absolute difference: +33.3 percentage points
Targeted 95% family-cluster bootstrap CI: [{pct(comparisons[0]['family_cluster_bootstrap_95_ci'][0])}, {pct(comparisons[0]['family_cluster_bootstrap_95_ci'][1])}]
Targeted exact paired result: p={comparisons[0]['exact_paired_p_two_sided']:.3f}
Observer-aware overall: 13/18 (72.2%)
Dense overall: 15/18 (83.3%)
Query-blind overall: 3/18 (16.7%)
Native / no-seed / chimera: 13/18 / 16/18 / 12/18
Preregistered success criterion met: NO
Overall verdict: NOT SUPPORTED

Observer-aware topology solved all constructed changed-constraint tasks and strongly outperformed query-blind topology, but it failed five negative controls solved by dense retrieval. The canonical seed did not improve targeted performance and reduced overall performance relative to no-seed runtime topology. See the statistical, seed, counterfactual, and navigation reports for the scoped interpretation.
"""
    (ROOT / "V9_RESULT_SUMMARY.md").write_text(result_summary, encoding="utf-8")

    reproduction = f"""PRIMARY EXPERIMENT COMPLETED. This command records the immutable invocation; do not rerun to replace the frozen result.

PowerShell from stoe_v9_experiment:
$env:PYTHONPATH=(Resolve-Path '.\\src')
python -m stoe_v9 run --tasks benchmarks\\frozen_primary_v1.json --provider ollama --api-base http://127.0.0.1:11434 --model gemma4:26b --model-digest 5571076f3d70050487b26b341705799e0ab29b808164f90d20d4cf84f699d251 --embedding-model qwen3-embedding:0.6b --embedding-digest ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d --output V9_PRIMARY_RESULTS.json --allow-primary

Frozen raw result SHA-256: {stats['raw_result_sha256']}
Benchmark SHA-256: {spec['sets']['primary_sha256']}
Canonical seed SHA-256: {spec['canonical_seed']['sha256']}
"""
    (ROOT / "V9_PRIMARY_REPRODUCTION_COMMAND.txt").write_text(reproduction, encoding="utf-8")

    output_names = [
        "V9_PRIMARY_RESULTS.json", "V9_PRIMARY_RAW_TRACES.json", "V9_PRIMARY_ANALYSIS_DATA.json",
        "V9_PRIMARY_STATISTICAL_ANALYSIS.md", "V9_PRIMARY_COUNTERFACTUAL_RESULTS.json",
        "V9_PRIMARY_COUNTERFACTUAL_REPORT.md", "V9_SEED_ANALYSIS.md",
        "V9_NAVIGATION_POSTMORTEM.md", "V9_FINAL_REPORT.md", "V9_RESULT_SUMMARY.md",
        "V9_PRIMARY_REPRODUCTION_COMMAND.txt", "V9_PRIMARY_ENVIRONMENT.json",
        "V9_PRIMARY_PREFLIGHT.md", "V9_EXPERIMENT_SPEC.json", "V9_PRE_PRIMARY_MANIFEST.json",
        "data/stoe_seed.json", "benchmarks/frozen_primary_v1.json", "tools/analyze_primary.py",
    ]
    manifest = {
        "schema_version": 1,
        "status": "PRIMARY_AND_ANALYSIS_COMPLETE",
        "raw_primary_immutable": True,
        "files": {
            name: {
                "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                "bytes": (ROOT / name).stat().st_size,
            }
            for name in output_names
        },
    }
    write_json(ROOT / "V9_POSTRUN_MANIFEST.json", manifest)
    print(json.dumps({
        "verdict": criterion["verdict"],
        "criterion_met": criterion["all_required_met"],
        "raw_sha256": stats["raw_result_sha256"],
        "outputs": len(output_names) + 1,
    }))


if __name__ == "__main__":
    main()
