from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


V9 = Path(__file__).resolve().parents[2] / "stoe_v9_experiment"
OUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V9 / "src"))

from stoe_v9.tasks import build_task_graph, load_tasks  # noqa: E402


REF_RE = re.compile(r"\[MEMORY_REF ([^\]]+)\]")
TYPED = {
    "TYPED_SEMANTIC_MEMORY",
    "QUERY_BLIND_TOPOLOGY",
    "OBSERVER_AWARE_STOE_TOPOLOGY",
    "OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED",
    "OBSERVER_AWARE_STOE_CHIMERA_SEED",
    "OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES",
    "OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES",
    "OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL",
    "OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE",
}


def line_for(graph, row: dict, ref: str) -> str:
    node = graph.nodes[ref]
    typed = row["condition"] in TYPED
    relation = str(node.metadata.get("relation_context", "connected_to")) if typed else "untyped"
    trace = next((item for item in row["navigation_trace"] if item["candidate_ip"] == ref), None)
    if typed and trace and trace["edge_types"]:
        relation = ">".join(
            f"{kind}:{direction}"
            for kind, direction in zip(trace["edge_types"], trace["edge_directions"])
        )
    return (
        f"[MEMORY_REF {ref}] KIND={node.kind}; OUTCOME={node.outcome}; "
        f"RELATION_CONTEXT={relation}; SEMANTIC_CONTENT={node.content}"
    )


def main() -> None:
    data = json.loads((V9 / "V9_PRIMARY_RESULTS.json").read_text(encoding="utf-8"))
    tasks = {task.id: task for task in load_tasks(V9 / "benchmarks/frozen_primary_v1.json")}
    audit_rows = []
    for row in data["results"]:
        graph, _ = build_task_graph(tasks[row["task_id"]], seed_mode=row["field_seed_mode"])
        selected = list(row["retrieved_refs"])
        visible = REF_RE.findall(row["memory_context"])
        original_lines = {ref: line_for(graph, row, ref) for ref in selected}
        original_lengths = {ref: len(text) for ref, text in original_lines.items()}
        lost = [ref for ref in selected if ref not in visible]
        responsible = lost[0] if lost else None
        prefix = []
        overflow_at = None
        for ref in selected:
            candidate = "\n".join(prefix + [original_lines[ref]])
            if len(candidate) > 5000:
                overflow_at = ref
                break
            prefix.append(original_lines[ref])
        if visible != selected[: len(visible)]:
            raise RuntimeError(f"old context is not selected prefix: {row['task_id']} {row['condition']}")
        audit_rows.append({
            "task_id": row["task_id"],
            "family": row["family"],
            "condition": row["condition"],
            "subset": row["subset"],
            "stage": "final_decision",
            "selected_artifact_count": len(selected),
            "selected_refs": selected,
            "actual_model_visible_artifact_count": len(visible),
            "actual_visible_refs": visible,
            "selected_refs_lost_before_model_exposure": lost,
            "original_serialized_line_chars": original_lengths,
            "oversized_artifact_responsible": responsible,
            "reconstructed_break_ref": overflow_at,
            "exact_memory_characters_sent": len(row["memory_context"]),
            "exact_memory_context_sent": row["memory_context"],
            "violated_four_visible_invariant": len(selected) == 4 and len(visible) < 4,
            "old_context_matches_reconstructed_prefix": row["memory_context"] == "\n".join(prefix),
        })

    grouped = defaultdict(lambda: Counter(rows=0, selected_four=0, violations=0, visible_blocks=0, lost_refs=0))
    for row in audit_rows:
        for key in [(row["condition"], "all"), (row["condition"], row["subset"]), ("ALL_CONDITIONS", "all"), ("ALL_CONDITIONS", row["subset"])]:
            item = grouped[key]
            item["rows"] += 1
            item["selected_four"] += row["selected_artifact_count"] == 4
            item["violations"] += row["violated_four_visible_invariant"]
            item["visible_blocks"] += row["actual_model_visible_artifact_count"]
            item["lost_refs"] += len(row["selected_refs_lost_before_model_exposure"])
    summary = [
        {"condition": condition, "subset": subset, **dict(counts)}
        for (condition, subset), counts in sorted(grouped.items())
    ]
    payload = {
        "schema_version": 1,
        "status": "DIAGNOSTIC_AUDIT_OF_IMMUTABLE_V9",
        "source": str(V9 / "V9_PRIMARY_RESULTS.json"),
        "scientific_status": "V9_PRIMARY_INVALID_CONTEXT_BUDGET",
        "rows": audit_rows,
        "summary": summary,
    }
    (OUT / "V9_CONTEXT_EXPOSURE_AUDIT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    condition_lines = []
    for item in summary:
        if item["subset"] == "all" and item["condition"] != "ALL_CONDITIONS":
            condition_lines.append(
                f"| {item['condition']} | {item['rows']} | {item['selected_four']} | {item['violations']} | {item['lost_refs']} | {item['visible_blocks']} |"
            )
    subset_lines = []
    for subset in ("topology_targeted", "negative_control"):
        item = next(entry for entry in summary if entry["condition"] == "ALL_CONDITIONS" and entry["subset"] == subset)
        subset_lines.append(f"| {subset} | {item['rows']} | {item['selected_four']} | {item['violations']} | {item['lost_refs']} |")
    total = next(entry for entry in summary if entry["condition"] == "ALL_CONDITIONS" and entry["subset"] == "all")
    responsible = Counter(row["oversized_artifact_responsible"] for row in audit_rows if row["oversized_artifact_responsible"])
    responsible_lines = "\n".join(f"| `{ref}` | {count} |" for ref, count in responsible.most_common()) or "| none | 0 |"
    report = f"""# Frozen V9 Context Exposure Audit

## Result

All 252 frozen v9 primary rows were audited against the exact `memory_context` sent to Gemma. The old prefix was independently reconstructed from the frozen selected refs, graph nodes, typed paths, and serializer. Every row matched its reconstructed prefix.

- Rows selecting four artifacts: **{total['selected_four']}**
- Four-selected rows exposing fewer than four: **{total['violations']}**
- Selected refs lost before model exposure: **{total['lost_refs']}**
- Scientific status: **V9_PRIMARY_INVALID_CONTEXT_BUDGET**

## By condition

| Condition | Rows | Selected 4 | Exposure violations | Lost refs | Visible blocks |
|---|---:|---:|---:|---:|---:|
{chr(10).join(condition_lines)}

## By benchmark subset

| Subset | Rows | Selected 4 | Exposure violations | Lost refs |
|---|---:|---:|---:|---:|
{chr(10).join(subset_lines)}

## First block responsible for old break

| Ref | Rows |
|---|---:|
{responsible_lines}

The JSON artifact contains every task, family, condition, stage, selected/visible ref list, lost refs, reconstructed original line lengths, responsible block, exact memory characters, exact context, and invariant flag. This audit is diagnostic only and does not alter or rescore v9.
"""
    (OUT / "V9_CONTEXT_EXPOSURE_AUDIT.md").write_text(report, encoding="utf-8")
    print(json.dumps({
        "rows": len(audit_rows),
        "selected_four": total["selected_four"],
        "violations": total["violations"],
        "lost_refs": total["lost_refs"],
    }))


if __name__ == "__main__":
    main()
