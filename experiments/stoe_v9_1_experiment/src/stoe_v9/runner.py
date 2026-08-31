from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from .models import RetrievalResult, TaskDefinition
from .navigator import ObserverAwareNavigator, QueryBlindNavigator, trace_to_dict
from .providers import GenerationParams, GenerationResult, compose_user_content
from .retrieval import (
    EmbeddingBackend,
    assert_serialized_memory,
    bm25_retrieve,
    dense_retrieve,
    serialize_memory,
    success_retrieve,
)
from .tasks import build_task_graph


class Condition(str, Enum):
    NO_MEMORY = "NO_MEMORY"
    SUCCESS_MEMORY = "SUCCESS_MEMORY"
    BM25_MEMORY = "BM25_MEMORY"
    DENSE_SEMANTIC_MEMORY = "DENSE_SEMANTIC_MEMORY"
    TYPED_SEMANTIC_MEMORY = "TYPED_SEMANTIC_MEMORY"
    QUERY_BLIND_TOPOLOGY = "QUERY_BLIND_TOPOLOGY"
    OBSERVER_AWARE_STOE_TOPOLOGY = "OBSERVER_AWARE_STOE_TOPOLOGY"
    OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED = "OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED"
    OBSERVER_AWARE_STOE_CHIMERA_SEED = "OBSERVER_AWARE_STOE_CHIMERA_SEED"
    OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES = "OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES"
    OBSERVER_AWARE_TOPOLOGY_UNTYPED = "OBSERVER_AWARE_TOPOLOGY_UNTYPED"
    OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES = "OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES"
    OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL = "OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL"
    OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE = "OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE"


ALL_CONDITIONS = list(Condition)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
IP_RE = re.compile(r"^IP_[0-9]{5}$")
SEED_REF_RE = re.compile(r"^SEED_[0-9a-f]{16}$")
INTERNAL_REF_RE = re.compile(r"^(?:IP_[0-9]{5}|SEED_[0-9a-f]{16}|STOE_Seed_IP)$", re.I)


class ExperimentRunner:
    def __init__(
        self,
        *,
        provider,
        params: GenerationParams,
        embedder: EmbeddingBackend,
        retrieval_items: int = 4,
        max_memory_chars: int = 5000,
        seed: int = 9417,
    ):
        self.provider = provider
        self.params = params
        self.embedder = embedder
        self.retrieval_items = retrieval_items
        self.max_memory_chars = max_memory_chars
        self.seed = seed

    def run(self, tasks: list[TaskDefinition], conditions: list[Condition], *, counterfactuals: bool) -> dict:
        rows = []
        started = time.time()
        for task in tasks:
            typed_plan: RetrievalResult | None = None
            for condition in conditions:
                row, plan = self._run_task(task, condition, typed_plan=typed_plan)
                rows.append(row)
                if condition == Condition.OBSERVER_AWARE_STOE_TOPOLOGY:
                    typed_plan = plan
        replays = self._counterfactuals(tasks, rows) if counterfactuals else []
        return {
            "schema_version": 2,
            "status": "V9_1_CORRECTIVE_REPLICATION_COMPLETE",
            "provider": self.provider.name,
            "model": self.params.model,
            "model_digest": getattr(self.provider, "expected_model_digest", None),
            "embedding_backend": getattr(self.embedder, "name", None),
            "parameters": asdict(self.params),
            "retrieval_items": self.retrieval_items,
            "max_memory_chars": self.max_memory_chars,
            "seed": self.seed,
            "started_unix": started,
            "conditions": [item.value for item in conditions],
            "task_ids": [task.id for task in tasks],
            "results": rows,
            "counterfactual_replays": replays,
        }

    def _retrieve(self, task: TaskDefinition, condition: Condition, typed_plan: RetrievalResult | None = None):
        seed_mode = "native"
        if condition == Condition.OBSERVER_AWARE_STOE_WITHOUT_CORE_SEED:
            seed_mode = "absent"
        elif condition == Condition.OBSERVER_AWARE_STOE_CHIMERA_SEED:
            seed_mode = "chimera"
        graph, state = build_task_graph(task, seed_mode=seed_mode)
        typed = False
        if condition == Condition.NO_MEMORY:
            result = RetrievalResult([], "none", [], realized_artifact_count=0)
        elif condition == Condition.SUCCESS_MEMORY:
            result = success_retrieve(graph, limit=self.retrieval_items)
        elif condition in {Condition.DENSE_SEMANTIC_MEMORY, Condition.TYPED_SEMANTIC_MEMORY}:
            result = dense_retrieve(graph, state, self.embedder, limit=self.retrieval_items)
            typed = condition == Condition.TYPED_SEMANTIC_MEMORY
        elif condition == Condition.BM25_MEMORY:
            result = bm25_retrieve(graph, state, limit=self.retrieval_items)
        elif condition == Condition.QUERY_BLIND_TOPOLOGY:
            result = QueryBlindNavigator(graph).select(state, limit=self.retrieval_items)
            typed = True
        else:
            if condition == Condition.OBSERVER_AWARE_TOPOLOGY_RANDOMIZED_EDGES:
                graph = graph.randomized_transition_endpoints(self.seed)
            include_failures = condition != Condition.OBSERVER_AWARE_TOPOLOGY_WITHOUT_FAILURES
            use_change = condition != Condition.OBSERVER_AWARE_TOPOLOGY_WITHOUT_STATE_CHANGE_SIGNAL
            use_query = condition != Condition.OBSERVER_AWARE_TOPOLOGY_WITHOUT_QUERY_RELEVANCE
            if condition == Condition.OBSERVER_AWARE_TOPOLOGY_UNTYPED and typed_plan is not None:
                result = clone_plan(typed_plan, "observer_aware_topology_untyped_locked_plan")
            else:
                result = ObserverAwareNavigator(graph).select(
                    state, limit=self.retrieval_items, include_failures=include_failures,
                    use_state_change=use_change, use_query_relevance=use_query,
                )
            typed = condition != Condition.OBSERVER_AWARE_TOPOLOGY_UNTYPED
        serialization = serialize_memory(graph, result, typed=typed, max_chars=self.max_memory_chars)
        result.serialization = serialization.to_dict()
        context = serialization.text
        return graph, state, result, context

    def _assert_final_context(
        self, prompt: str, context: str, selected_refs: list[str], *, required: bool
    ) -> None:
        final_user_content = compose_user_content(prompt, context)
        if required:
            assert_serialized_memory(context, selected_refs, max_chars=self.max_memory_chars)
            expected_tail = "MEMORY_CONTEXT:\n" + (context or "(none)")
            if not final_user_content.endswith(expected_tail):
                raise AssertionError("fatal final prompt/context composition mismatch")

    def _run_task(self, task: TaskDefinition, condition: Condition, *, typed_plan: RetrievalResult | None):
        graph, state, retrieval, context = self._retrieve(task, condition, typed_plan)
        prompt = make_prompt(task, state)
        serialization = retrieval.serialization or {}
        final_user_content = compose_user_content(prompt, context)
        self._assert_final_context(
            prompt, context, retrieval.refs, required=condition != Condition.NO_MEMORY
        )
        started = time.perf_counter()
        try:
            generation = self.provider.generate(prompt, context, self.params)
            error = None
        except Exception as exc:
            generation = GenerationResult("", 0, 0, 0.0, {})
            error = f"{type(exc).__name__}: {exc}"
        parsed, parse_error = parse_response(generation.text, retrieval.refs)
        answer = parsed["answer"]
        exact = (
            answer.strip().upper() == task.expected_answer.upper()
            and not UUID_RE.fullmatch(answer.strip())
            and not INTERNAL_REF_RE.fullmatch(answer.strip())
        )
        focal_rank = retrieval.refs.index(task.topology_target_ref) + 1 if task.topology_target_ref in retrieval.refs else None
        row = {
            "task_id": task.id,
            "family": task.family,
            "subset": task.subset,
            "condition": condition.value,
            "question": task.question,
            "goal": task.goal,
            "expected_answer": task.expected_answer,
            "answer": answer,
            "exact_success": exact,
            "internal_id_contamination": bool(UUID_RE.fullmatch(answer.strip()) or INTERNAL_REF_RE.fullmatch(answer.strip())),
            "used_memory_refs": parsed["used_memory_refs"],
            "confidence": parsed["confidence"],
            "current_state_ip": asdict(state),
            "retrieved_refs": retrieval.refs,
            "retrieved_origins": [str(graph.nodes[ref].metadata.get("origin", "runtime_reasoning")) for ref in retrieval.refs],
            "retrieval_scores": retrieval.scores,
            "retrieval_method": retrieval.method,
            "field_seed_mode": graph.field_metadata.get("seed_mode"),
            "canonical_seed_sha256": graph.field_metadata.get("canonical_seed_sha256"),
            "realized_artifact_count": retrieval.realized_artifact_count,
            "selected_artifact_count": serialization.get("selected_artifact_count", 0),
            "selected_artifact_refs": serialization.get("selected_artifact_refs", []),
            "model_visible_artifact_count": serialization.get("model_visible_artifact_count", 0),
            "model_visible_memory_refs": serialization.get("model_visible_memory_refs", []),
            "serialized_memory_char_count": serialization.get("serialized_memory_char_count", 0),
            "serialization_artifacts": serialization.get("artifacts", []),
            "per_artifact_original_char_count": {
                artifact["ref"]: artifact["original_content_chars"]
                for artifact in serialization.get("artifacts", [])
            },
            "per_artifact_serialized_char_count": {
                artifact["ref"]: artifact["serialized_content_chars"]
                for artifact in serialization.get("artifacts", [])
            },
            "per_artifact_truncated": {
                artifact["ref"]: artifact["truncated"]
                for artifact in serialization.get("artifacts", [])
            },
            "exact_serialized_memory": context,
            "final_user_prompt_sha256": hashlib.sha256(final_user_content.encode()).hexdigest(),
            "focal_ip_ref": task.topology_target_ref,
            "focal_ip_rank": focal_rank,
            "evaluation_ip_selected": "IP_00006" in retrieval.refs,
            "memory_context": context,
            "prompt": prompt,
            "model_response_raw": generation.text,
            "parse_error": parse_error,
            "provider_error": error,
            "input_tokens": generation.input_tokens,
            "output_tokens": generation.output_tokens,
            "latency_seconds": generation.latency_seconds,
            "wall_seconds": time.perf_counter() - started,
            "provider_metadata": generation.metadata,
            "navigation_trace": [trace_to_dict(trace) for trace in retrieval.traces],
        }
        return row, retrieval

    def _counterfactuals(self, tasks: list[TaskDefinition], rows: list[dict]) -> list[dict]:
        by_key = {(row["condition"], row["task_id"]): row for row in rows}
        output = []
        for task in tasks:
            original = by_key.get((Condition.OBSERVER_AWARE_STOE_TOPOLOGY.value, task.id))
            if not original or not original["exact_success"]:
                continue
            graph, state = build_task_graph(task)
            self._assert_final_context(
                original["prompt"], original["memory_context"], original["retrieved_refs"], required=True
            )
            control = self.provider.generate(original["prompt"], original["memory_context"], self.params)
            control_parsed, control_error = parse_response(control.text, original["retrieved_refs"])
            control_success = control_parsed["answer"].strip().upper() == task.expected_answer.upper()
            interventions = {
                "REMOVE_FOCAL_FAILED_IP": (graph.without_node("IP_00002"), True, True),
                "REMOVE_STATE_CHANGE_IP": (graph.without_node("IP_00004"), True, True),
                "REMOVE_CRITICAL_TYPED_RELATION": (graph.without_relation("rejected_by"), True, True),
                "RANDOMIZE_CRITICAL_EDGES": (graph.randomized_transition_endpoints(self.seed + 17), True, True),
                "REMOVE_QUERY_RANKING": (graph, True, False),
            }
            replay_rows = []
            for name, (changed_graph, use_change, use_query) in interventions.items():
                retrieval = ObserverAwareNavigator(changed_graph).select(
                    state, limit=self.retrieval_items, use_state_change=use_change,
                    use_query_relevance=use_query,
                )
                serialization = serialize_memory(
                    changed_graph, retrieval, typed=True, max_chars=self.max_memory_chars
                )
                retrieval.serialization = serialization.to_dict()
                context = serialization.text
                self._assert_final_context(
                    original["prompt"], context, retrieval.refs, required=True
                )
                generated = self.provider.generate(original["prompt"], context, self.params)
                parsed, parse_error = parse_response(generated.text, retrieval.refs)
                success = parsed["answer"].strip().upper() == task.expected_answer.upper()
                if not control_success:
                    classification = "INVALID_REPLAY"
                elif not success:
                    classification = "NECESSARY_FOR_SUCCESS"
                elif parsed["confidence"] > control_parsed["confidence"] + 0.05:
                    classification = "COUNTERFACTUAL_IMPROVED"
                elif parsed != control_parsed:
                    classification = "CONTRIBUTORY"
                else:
                    classification = "NO_DETECTABLE_EFFECT"
                replay_rows.append({
                    "intervention": name,
                    "classification": classification,
                    "answer": parsed["answer"],
                    "success": success,
                    "parse_error": parse_error,
                    "retrieved_refs": retrieval.refs,
                    "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
                    "input_tokens": generated.input_tokens,
                    "output_tokens": generated.output_tokens,
                    "latency_seconds": generated.latency_seconds,
                    "model_response_raw": generated.text,
                    "memory_context": context,
                    "selected_artifact_count": serialization.selected_artifact_count,
                    "selected_artifact_refs": serialization.selected_artifact_refs,
                    "model_visible_artifact_count": serialization.model_visible_artifact_count,
                    "model_visible_memory_refs": serialization.model_visible_memory_refs,
                    "serialized_memory_char_count": serialization.serialized_memory_char_count,
                    "serialization_artifacts": [asdict(item) for item in serialization.artifacts],
                    "navigation_trace": [trace_to_dict(trace) for trace in retrieval.traces],
                    "provider_metadata": generated.metadata,
                })
            output.append({
                "task_id": task.id,
                "control_success": control_success,
                "control_parse_error": control_error,
                "control_answer": control_parsed["answer"],
                "control_response_raw": control.text,
                "control_provider_metadata": control.metadata,
                "original_context_sha256": hashlib.sha256(original["memory_context"].encode()).hexdigest(),
                "interventions": replay_rows,
            })
        return output


def clone_plan(plan: RetrievalResult, method: str) -> RetrievalResult:
    return RetrievalResult(
        refs=list(plan.refs), method=method, scores=list(plan.scores),
        traces=list(plan.traces), realized_artifact_count=plan.realized_artifact_count,
    )


def make_prompt(task: TaskDefinition, state) -> str:
    return (
        f"TASK_ID: {task.id}\n"
        f"CURRENT_GOAL: {task.goal}\n"
        f"ACTIVE_CONSTRAINTS: {'; '.join(task.active_constraints)}\n"
        f"RECENTLY_CHANGED_OR_INVALIDATED_CONSTRAINTS: {'; '.join(task.changed_constraints)}\n"
        f"CURRENT_QUESTION: {task.question}\n"
        "Return the task-domain answer token, not a memory reference or storage identifier."
    )


def parse_response(text: str, allowed_refs: list[str]) -> tuple[dict[str, Any], str | None]:
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("response is not an object")
        answer = str(value.get("answer", ""))
        refs = value.get("used_memory_refs", [])
        if not isinstance(refs, list):
            raise ValueError("used_memory_refs is not a list")
        refs = [
            str(ref) for ref in refs
            if str(ref) in allowed_refs and (IP_RE.fullmatch(str(ref)) or SEED_REF_RE.fullmatch(str(ref)))
        ]
        confidence = float(value.get("confidence", 0.0))
        return {"answer": answer, "used_memory_refs": refs, "confidence": confidence}, None
    except Exception as exc:
        return {"answer": "", "used_memory_refs": [], "confidence": 0.0}, str(exc)


def write_results(result: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
