from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import v9_frozen_analysis_library as frozen


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "V9_1_PRIMARY_RESULTS.json"
OLD_RESULT = ROOT.parent / "stoe_v9_experiment" / "V9_PRIMARY_RESULTS.json"
OA = frozen.OA
QB = frozen.QB
DENSE = frozen.DENSE
BM25 = frozen.BM25
NO_SEED = frozen.NO_SEED
CHIMERA = frozen.CHIMERA
REF_RE = re.compile(r"\[MEMORY_REF ([^\]]+)\]")


def write_json(name: str, value) -> None:
    (ROOT / name).write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(rows: list[dict], condition: str) -> dict:
    value = frozen.condition_metrics(rows, condition)
    selected = frozen.rows_for(rows, condition)
    value.update({
        "selected_artifacts": sum(row["selected_artifact_count"] for row in selected),
        "model_visible_artifacts": sum(row["model_visible_artifact_count"] for row in selected),
        "memory_characters": sum(row["serialized_memory_char_count"] for row in selected),
        "truncated_artifacts": sum(
            sum(bool(flag) for flag in row["per_artifact_truncated"].values()) for row in selected
        ),
        "visible_count_distribution": dict(sorted(Counter(
            row["model_visible_artifact_count"] for row in selected
        ).items())),
    })
    return value


def build_comparisons(rows: list[dict]) -> list[dict]:
    definitions = [
        (OA, DENSE, "topology_targeted"), (OA, QB, "all"),
        (OA, QB, "topology_targeted"), (OA, QB, "negative_control"),
        (OA, DENSE, "all"), (OA, DENSE, "negative_control"),
        (OA, BM25, "all"), (OA, BM25, "topology_targeted"),
        (OA, "SUCCESS_MEMORY", "all"), (OA, "SUCCESS_MEMORY", "topology_targeted"),
        (OA, NO_SEED, "all"), (OA, NO_SEED, "topology_targeted"),
        (OA, CHIMERA, "all"), (OA, CHIMERA, "topology_targeted"),
    ]
    definitions += [(OA, condition, subset) for condition in [
        "OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES",
        "OBSERVER_AWARE_TOPOLOGY_UNTYPED",
        "OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES",
        "OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL",
        "OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE",
    ] for subset in ("all", "topology_targeted", "negative_control")]
    return [frozen.comparison(rows, left, right, subset) for left, right, subset in definitions]


def result_for(metrics: list[dict], condition: str) -> dict:
    return next(item for item in metrics if item["condition"] == condition)


def row_map(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(row["task_id"], row["condition"]): row for row in rows}


def main() -> None:
    data = frozen.read_json(RESULT)
    old = frozen.read_json(OLD_RESULT)
    rows = data["results"]
    if len(rows) != 252:
        raise SystemExit(f"analysis refused: expected 252 primary rows, got {len(rows)}")
    exposure_failures = [
        row for row in rows
        if row["condition"] != "NO_MEMORY" and (
            row["selected_artifact_refs"] != row["model_visible_memory_refs"]
            or row["model_visible_artifact_count"] != 4
            or row["serialized_memory_char_count"] > 5000
        )
    ]
    if exposure_failures:
        raise SystemExit(f"analysis refused: {len(exposure_failures)} corrected exposure failures")

    metrics = [metric(rows, condition) for condition in data["conditions"]]
    comparisons = build_comparisons(rows)
    navigation = frozen.navigation_metrics(rows)
    seed = frozen.seed_metrics(rows, frozen.read_json(ROOT / "data/stoe_seed.json"))
    counterfactual = frozen.counterfactual_metrics(data, rows)
    criterion = frozen.success_criterion(rows, data)
    stats = {
        "schema_version": 1,
        "analysis_status": "V9_1_CORRECTIVE_REPLICATION_COMPLETE",
        "raw_result_sha256": digest(RESULT),
        "historical_v9_raw_result_sha256": digest(OLD_RESULT),
        "conditions": metrics,
        "comparisons": comparisons,
        "navigation": navigation,
        "seed": seed,
        "counterfactual": counterfactual,
        "success_criterion": criterion,
        "exposure_integrity_failures": 0,
    }
    write_json("V9_1_PRIMARY_ANALYSIS_DATA.json", stats)
    write_json("V9_1_PRIMARY_RAW_TRACES.json", {
        "schema_version": 2,
        "status": "V9_1_CORRECTIVE_REPLICATION_COMPLETE",
        "source_result": RESULT.name,
        "source_result_sha256": stats["raw_result_sha256"],
        "single_stage_protocol": "final_decision",
        "traces": rows,
    })
    write_json("V9_1_COUNTERFACTUAL_RESULTS.json", {
        "schema_version": 2,
        "status": "CORRECTED_COUNTERFACTUALS_COMPLETE",
        "source_result_sha256": stats["raw_result_sha256"],
        "replays": data["counterfactual_replays"],
        "summary": counterfactual,
    })

    oa = result_for(metrics, OA)
    dense = result_for(metrics, DENSE)
    bm25 = result_for(metrics, BM25)
    qb = result_for(metrics, QB)
    native = oa
    noseed = result_for(metrics, NO_SEED)
    chimera = result_for(metrics, CHIMERA)
    primary = comparisons[0]
    overall_dense = next(item for item in comparisons if item["right"] == DENSE and item["subset"] == "all")
    ci = primary["family_cluster_bootstrap_95_ci"]

    statistical = f"""# V9.1 Statistical Analysis

## Status and exposure gate

This is a **corrective replication**, not an independent confirmation. It contains 18 distinct tasks in nine family clusters and 14 frozen conditions (252 primary cells). All 234 memory-bearing cells exposed exactly four unique selected references, and no serialized memory block exceeded 5000 characters.

{frozen.metric_table(metrics)}

## Frozen paired comparisons

{frozen.comparison_table(comparisons)}

The confirmatory targeted comparison was observer-aware topology versus dense semantic retrieval: {primary['left_success']}/{primary['n']} versus {primary['right_success']}/{primary['n']}, an absolute difference of {frozen.pct(primary['absolute_difference'])}; family-cluster bootstrap 95% CI [{frozen.pct(ci[0])}, {frozen.pct(ci[1])}], exact paired p={primary['exact_paired_p_two_sided']:.6f}. Overall the same comparison was {overall_dense['left_success']}/{overall_dense['n']} versus {overall_dense['right_success']}/{overall_dense['n']}.

The frozen all-required success criterion is **{'MET' if criterion['all_required_met'] else 'NOT MET'}**. Individual checks: `{json.dumps(criterion['checks'], sort_keys=True)}`. A confidence interval containing zero is not called equivalence.

Across primary cells there were {sum(item['provider_errors'] for item in metrics)} provider errors, {sum(item['parse_errors'] for item in metrics)} parse errors, and {sum(item['transport_retries'] for item in metrics)} transport retries. Total primary tokens were {sum(item['total_tokens'] for item in metrics):,}; recorded generation latency was {sum(item['latency_seconds'] for item in metrics):.3f} seconds. Family-cluster intervals use the frozen 10,000 resamples and seed 9417.
"""
    (ROOT / "V9_1_STATISTICAL_ANALYSIS.md").write_text(statistical, encoding="utf-8")

    cf_lines = []
    labels = ["NECESSARY_FOR_SUCCESS", "CONTRIBUTORY", "NO_DETECTABLE_EFFECT", "COUNTERFACTUAL_IMPROVED", "INVALID_REPLAY"]
    for name, counts in counterfactual["classifications_by_intervention"].items():
        cf_lines.append("| " + name + " | " + " | ".join(str(counts.get(label, 0)) for label in labels) + " |")
    cf_report = f"""# V9.1 Corrected Counterfactual Report

The frozen replay suite ran after all 252 primary cells and used the corrected serializer plus fatal model-visible exposure assertions. It replayed {counterfactual['successful_observer_cases_replayed']} successful observer-aware cases with {counterfactual['generation_calls']} model calls. Self-reported `used_memory_refs` are not causal evidence.

| Intervention | Necessary | Contributory | No effect | Improved | Invalid |
|---|---:|---:|---:|---:|---:|
{chr(10).join(cf_lines)}

Topology-only targeted wins versus dense: {', '.join(criterion['topology_only_targeted_task_ids']) or 'none'}. Counterfactually supported under the frozen criterion: {', '.join(criterion['counterfactually_supported_topology_only_task_ids']) or 'none'} ({frozen.pct(criterion['counterfactual_mechanism_fraction'])}). These are pipeline interventions that can change the replacement context; they support dependence on the implemented mechanism, not philosophical claims about the full SToE ontology.
"""
    (ROOT / "V9_1_COUNTERFACTUAL_REPORT.md").write_text(cf_report, encoding="utf-8")

    native_rows = frozen.rows_for(rows, OA)
    selected_seed = [
        artifact for row in native_rows for artifact in row["serialization_artifacts"]
        if artifact["origin"] == "canonical_seed"
    ]
    seed_counts = Counter(item["ref"] for item in selected_seed)
    seed_table = "\n".join(
        f"| `{ref}` | {count} | {sum(item['serialized_content_chars'] for item in selected_seed if item['ref'] == ref)} | {sum(item['truncated'] for item in selected_seed if item['ref'] == ref)} |"
        for ref, count in seed_counts.most_common()
    ) or "| — | 0 | 0 | 0 |"
    seed_report = f"""# V9.1 Seed Analysis

Under corrected equal-four-artifact exposure, native seed scored {native['successes']}/{native['n']} overall ({native['targeted_successes']}/{native['targeted_n']} targeted; {native['control_successes']}/{native['control_n']} controls). Without core seed scored {noseed['successes']}/{noseed['n']} ({noseed['targeted_successes']}/{noseed['targeted_n']}; {noseed['control_successes']}/{noseed['control_n']}). Frozen chimera scored {chimera['successes']}/{chimera['n']} ({chimera['targeted_successes']}/{chimera['targeted_n']}; {chimera['control_successes']}/{chimera['control_n']}).

Native selected {len(selected_seed)} canonical-seed artifacts; {sum(item['truncated'] for item in selected_seed)} were truncated. Total exposed seed semantic-content characters were {sum(item['serialized_content_chars'] for item in selected_seed):,}. Seed exposure displaced {seed['runtime_artifacts_displaced_vs_no_seed']} runtime slots relative to no-seed; {len(seed['unexposed_seed_bridge_events'])} selected runtime paths used unexposed seed bridge nodes.

| Seed ref | Selections | Serialized content chars | Truncations |
|---|---:|---:|---:|
{seed_table}

This tests whether the current canonical-seed integration helps this benchmark. Native below no-seed would not falsify the SToE ontology; native above chimera would be evidence only within this model, benchmark, and integration.
"""
    (ROOT / "V9_1_SEED_ANALYSIS.md").write_text(seed_report, encoding="utf-8")

    maps = row_map(rows)
    nav_lines = []
    for task_id in data["task_ids"]:
        a = maps[(task_id, OA)]
        values = [maps[(task_id, condition)] for condition in (QB, DENSE, BM25, NO_SEED, CHIMERA)]
        nav_lines.append(
            f"| {task_id} | {a['subset']} | {'✓' if a['exact_success'] else '✗'} | "
            + " | ".join('✓' if item['exact_success'] else '✗' for item in values)
            + f" | {a['focal_ip_rank'] or '—'} | {', '.join(a['retrieved_refs'])} |"
        )
    untyped = result_for(metrics, "OBSERVER_AWARE_TOPOLOGY_UNTYPED")
    nochange = result_for(metrics, "OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL")
    navigation_report = f"""# V9.1 Navigation Postmortem

Observer-aware and query-blind selected different contexts on {navigation['observer_context_changed_vs_query_blind']}/18 tasks; those changes improved {navigation['changes_improved_answer']}, harmed {navigation['changes_hurt_answer']}, and left binary correctness unchanged on {navigation['changes_same_correctness']}. Observer-aware scored {oa['targeted_successes']}/{oa['targeted_n']} targeted versus query-blind {qb['targeted_successes']}/{qb['targeted_n']}; dense scored {dense['targeted_successes']}/{dense['targeted_n']} and BM25 {bm25['targeted_successes']}/{bm25['targeted_n']}.

| Task | Subset | Observer | Query-blind | Dense | BM25 | No seed | Chimera | Focal rank | Observer selected refs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(nav_lines)}

The untyped condition scored {untyped['successes']}/{untyped['n']}; it inherits the typed navigator's selected plan, so this compares relation labels shown to the LLM, not whether typed semantics matter during navigation. WITHOUT_STATE_CHANGE_SIGNAL scored {nochange['successes']}/{nochange['n']}; `invalidates` and `rejected_by` can still affect structural/provenance terms, so this does not remove all state-change structure.
"""
    (ROOT / "V9_1_NAVIGATION_POSTMORTEM.md").write_text(navigation_report, encoding="utf-8")

    old_map = row_map(old["results"])
    comparison_lines = []
    classifications = Counter()
    for row in rows:
        prior = old_map[(row["task_id"], row["condition"])]
        old_visible = REF_RE.findall(prior["memory_context"])
        selections_equal = prior["retrieved_refs"] == row["retrieved_refs"]
        exposure_changed = old_visible != row["model_visible_memory_refs"]
        if not selections_equal:
            classification = "NOT_COMPARABLE"
        elif prior["exact_success"] and row["exact_success"]:
            classification = "UNCHANGED_CORRECT"
        elif not prior["exact_success"] and not row["exact_success"]:
            classification = "UNCHANGED_INCORRECT"
        elif exposure_changed and not prior["exact_success"] and row["exact_success"]:
            classification = "CORRECTED_AFTER_EXPOSURE_FIX"
        elif exposure_changed and prior["exact_success"] and not row["exact_success"]:
            classification = "BROKE_AFTER_EXPOSURE_FIX"
        else:
            classification = "STOCHASTIC_CHANGE"
        classifications[classification] += 1
        lost = [ref for ref in prior["retrieved_refs"] if ref not in old_visible]
        comparison_lines.append(
            f"| {row['task_id']} | {row['condition']} | {', '.join(prior['retrieved_refs']) or '—'} | "
            f"{', '.join(old_visible) or '—'} | {', '.join(row['model_visible_memory_refs']) or '—'} | "
            f"{', '.join(lost) or '—'} | {prior['answer']} | {row['answer']} | "
            f"{'✓' if prior['exact_success'] else '✗'}→{'✓' if row['exact_success'] else '✗'} | {classification} |"
        )
    corrective = f"""# V9 vs V9.1 Corrective Comparison

V9.1 is a corrective replication, not an independent confirmation. Selected refs matched in all 252 dry-run cells before serialization. Classification totals: `{json.dumps(dict(classifications), sort_keys=True)}`. A changed answer is not automatically attributed causally to serialization; exposure-unchanged answer flips are labeled stochastic.

| Task | Condition | Frozen selected refs | V9 visible refs | V9.1 visible refs | V9 refs lost | V9 answer | V9.1 answer | Correctness | Classification |
|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(comparison_lines)}
"""
    (ROOT / "V9_VS_V9_1_CORRECTIVE_COMPARISON.md").write_text(corrective, encoding="utf-8")

    verdict = "SUPPORTED" if criterion["all_required_met"] else "NOT SUPPORTED"
    final = f"""# SToE V9.1 Corrective Replication Final Report

The measurement correction succeeded: all memory-bearing primary and counterfactual calls used bounded per-artifact serialization with exact selected/visible equality and a 5000-character total cap. Frozen selection was unchanged.

Observer-aware topology scored {oa['successes']}/{oa['n']} overall and {oa['targeted_successes']}/{oa['targeted_n']} targeted. Dense scored {dense['successes']}/{dense['n']} overall and {dense['targeted_successes']}/{dense['targeted_n']} targeted; BM25 {bm25['successes']}/{bm25['n']} and {bm25['targeted_successes']}/{bm25['targeted_n']}; query-blind {qb['successes']}/{qb['n']} and {qb['targeted_successes']}/{qb['targeted_n']}.

The frozen all-required criterion is **{verdict}**. Native/no-seed/chimera were {native['successes']}/{native['n']}, {noseed['successes']}/{noseed['n']}, and {chimera['successes']}/{chimera['n']}.

This result supports or fails only the tested SToE-derived retrieval/navigation hypothesis under this benchmark and local Gemma model. It does not establish the full SToE ontology, universal graph-memory superiority, or AGI superiority. Because v9 outcomes were already known and the benchmark was reused to correct an implementation defect, a new unseen holdout is required for independent confirmation.
"""
    (ROOT / "V9_1_FINAL_REPORT.md").write_text(final, encoding="utf-8")

    summary = f"""# V9.1 Result Summary

Replication type: CORRECTIVE REPLICATION (not independent confirmation)
Model: gemma4:26b (`5571076f…9d251`)
Benchmark: frozen_primary_v1 (`8c74a2af…a43b62`)
N: 18 tasks, 9 family clusters, 252 primary cells
Primary comparison: observer-aware topology vs dense semantic retrieval on 9 targeted tasks
Observer-aware targeted success: {primary['left_success']}/{primary['n']} ({frozen.pct(primary['left_rate'])})
Dense targeted success: {primary['right_success']}/{primary['n']} ({frozen.pct(primary['right_rate'])})
Absolute difference: {frozen.pct(primary['absolute_difference'])}
95% family-cluster bootstrap CI: [{frozen.pct(ci[0])}, {frozen.pct(ci[1])}]
Exact paired p: {primary['exact_paired_p_two_sided']:.6f}
Observer-aware overall: {oa['successes']}/{oa['n']} ({frozen.pct(oa['success_rate'])})
Dense overall: {dense['successes']}/{dense['n']} ({frozen.pct(dense['success_rate'])})
Query-blind overall: {qb['successes']}/{qb['n']} ({frozen.pct(qb['success_rate'])})
Native / no-seed / chimera: {native['successes']}/{native['n']} / {noseed['successes']}/{noseed['n']} / {chimera['successes']}/{chimera['n']}
Preregistered success criterion met: {'YES' if criterion['all_required_met'] else 'NO'}
Overall verdict: {verdict}

All 234 memory-bearing cells exposed four selected artifacts; zero exceeded 5000 characters. See the statistical, seed, counterfactual, navigation, and v9-comparison reports for scoped interpretation.
"""
    (ROOT / "V9_1_RESULT_SUMMARY.md").write_text(summary, encoding="utf-8")

    output_names = [
        "V9_1_PRIMARY_RESULTS.json", "V9_1_PRIMARY_RAW_TRACES.json",
        "V9_1_PRIMARY_ANALYSIS_DATA.json", "V9_1_STATISTICAL_ANALYSIS.md",
        "V9_1_COUNTERFACTUAL_RESULTS.json", "V9_1_COUNTERFACTUAL_REPORT.md",
        "V9_1_SEED_ANALYSIS.md", "V9_1_NAVIGATION_POSTMORTEM.md",
        "V9_VS_V9_1_CORRECTIVE_COMPARISON.md", "V9_1_FINAL_REPORT.md",
        "V9_1_RESULT_SUMMARY.md", "V9_1_ENVIRONMENT.json", "V9_1_PREFLIGHT.md",
        "V9_1_EXPERIMENT_SPEC.json", "V9_1_PRE_PRIMARY_MANIFEST.json",
        "V9_1_REPRODUCTION_COMMAND.txt", "data/stoe_seed.json",
        "benchmarks/frozen_primary_v1.json", "tools/analyze_v9_1.py",
    ]
    write_json("V9_1_POSTRUN_MANIFEST.json", {
        "schema_version": 1,
        "status": "CORRECTIVE_REPLICATION_AND_ANALYSIS_COMPLETE",
        "raw_primary_immutable": True,
        "files": {
            name: {"sha256": digest(ROOT / name), "bytes": (ROOT / name).stat().st_size}
            for name in output_names
        },
    })
    print(json.dumps({
        "verdict": verdict,
        "criterion_met": criterion["all_required_met"],
        "raw_sha256": stats["raw_result_sha256"],
        "outputs": len(output_names) + 1,
    }))


if __name__ == "__main__":
    main()
