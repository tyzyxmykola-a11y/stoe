from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .investigation import evaluate_public_selector
from .qualified_harness import CONDITIONS, MECHANISM_IDS
from .selection_policy import (
    ALL_FIELDS,
    EXPECTED_SORT,
    POLICY_FORMAT,
    POLICY_VERSION,
    TEXT_FIELDS,
    policy_selector,
    validate_policy,
)


PROPOSAL_MAX_TOKENS = 1400
POLICY_MAX_TOKENS = 2000
MIN_REMAINING_TOKENS = 1024
REPETITIONS = 3
PROPOSAL_SEEDS = (7701, 7702, 7703)
POLICY_SEEDS = (8701, 8702, 8703)
HARNESS_VERSION = "public-response-grammar-v3-dev3"


def _string(max_length: int, *, allow_empty: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string", "maxLength": max_length}
    if not allow_empty:
        result["minLength"] = 1
    return result


def proposal_schema(investigation: dict[str, Any]) -> dict[str, Any]:
    failed = [d for d in investigation["diagnostics"] if not d["selector_passed"]]
    finding = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "observed_selection": {"type": "array", "maxItems": 3, "items": _string(64)},
            "missed_required": {"type": "array", "maxItems": 3, "items": _string(64)},
            "mechanism_ids": {
                "type": "array", "minItems": 1, "maxItems": 6, "uniqueItems": True,
                "items": {"type": "string", "maxLength": 64, "enum": list(MECHANISM_IDS)},
            },
            "rationale": _string(140),
        },
        "required": ["observed_selection", "missed_required", "mechanism_ids", "rationale"],
    }
    names = [str(d["case"]) for d in failed]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "hypothesis": _string(180),
            "observed_evidence": {"type": "array", "minItems": 1, "maxItems": 3, "items": _string(140)},
            "diagnostic_findings": {
                "type": "object", "additionalProperties": False,
                "properties": {name: deepcopy(finding) for name in names},
                "required": names,
            },
            "source_diagnosis": _string(180),
            "proposed_change": _string(220),
            "implementation_inputs": {
                "type": "array", "minItems": 1, "maxItems": len(MECHANISM_IDS),
                "uniqueItems": True,
                "items": {"type": "string", "maxLength": 64, "enum": list(MECHANISM_IDS)},
            },
            "input_feasibility": _string(140),
            "expected_benefit": _string(140),
            "risks": {"type": "array", "minItems": 1, "maxItems": 3, "items": _string(120)},
        },
        "required": [
            "hypothesis", "observed_evidence", "diagnostic_findings", "source_diagnosis",
            "proposed_change", "implementation_inputs", "input_feasibility",
            "expected_benefit", "risks",
        ],
    }


def _condition_item(*, plural: bool = False, value_required: bool = True) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "field": {"type": "string", "maxLength": 64, "enum": sorted(ALL_FIELDS)},
    }
    required = ["field"]
    if value_required:
        key = "values" if plural else "value"
        properties[key] = (
            {"type": "array", "minItems": 1, "maxItems": 2, "uniqueItems": True, "items": _string(32)}
            if plural else _string(32)
        )
        required.append(key)
    return {
        "type": "object", "additionalProperties": False,
        "properties": properties, "required": required,
    }


def _conditions_schema() -> dict[str, Any]:
    names = {
        "equals": _condition_item(),
        "not_equals": _condition_item(),
        "in_values": _condition_item(plural=True),
        "not_in_values": _condition_item(plural=True),
        "contains_token": _condition_item(),
        "nonempty": _condition_item(value_required=False),
    }
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            name: {"type": "array", "maxItems": 1, "items": item}
            for name, item in names.items()
        },
        "required": list(names),
    }


POLICY_TABLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "format": {"type": "string", "maxLength": 32, "enum": [POLICY_FORMAT]},
        "version": {"type": "integer", "minimum": POLICY_VERSION, "maximum": POLICY_VERSION},
        "filters": {
            "type": "array", "maxItems": 2,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"conditions": _conditions_schema()},
                "required": ["conditions"],
            },
        },
        "token_similarity_rules": {
            "type": "array", "maxItems": 3,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "weight": {"type": "number", "minimum": -100, "maximum": 100},
                    "left_fields": {
                        "type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True,
                        "items": {"type": "string", "maxLength": 64, "enum": sorted(TEXT_FIELDS)},
                    },
                    "right_field": {"type": "string", "maxLength": 64, "enum": sorted(TEXT_FIELDS)},
                },
                "required": ["weight", "left_fields", "right_field"],
            },
        },
        "constant_if_rules": {
            "type": "array", "maxItems": 3,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "weight": {"type": "number", "minimum": -100, "maximum": 100},
                    "conditions": _conditions_schema(),
                },
                "required": ["weight", "conditions"],
            },
        },
        "conditional_similarity_rules": {
            "type": "array", "maxItems": 3,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "weight": {"type": "number", "minimum": -100, "maximum": 100},
                    "bias": {"type": "number", "minimum": -100, "maximum": 100},
                    "conditions": _conditions_schema(),
                    "left_fields": {
                        "type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True,
                        "items": {"type": "string", "maxLength": 64, "enum": sorted(TEXT_FIELDS)},
                    },
                    "right_field": {"type": "string", "maxLength": 64, "enum": sorted(TEXT_FIELDS)},
                },
                "required": ["weight", "bias", "conditions", "left_fields", "right_field"],
            },
        },
        "implementation_note": _string(160),
    },
    "required": [
        "format", "version", "filters", "token_similarity_rules", "constant_if_rules",
        "conditional_similarity_rules", "implementation_note",
    ],
}


def validate_schema(value: Any, schema: dict[str, Any], path: str = "response") -> None:
    kind = schema.get("type")
    if kind == "object":
        if type(value) is not dict:
            raise RuntimeError(f"{path} must be an object")
        properties = schema.get("properties", {})
        if not set(schema.get("required", [])).issubset(value):
            raise RuntimeError(f"{path} is missing required fields")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise RuntimeError(f"{path} contains additional fields")
        for key, child in value.items():
            validate_schema(child, properties[key], f"{path}.{key}")
    elif kind == "array":
        if type(value) is not list:
            raise RuntimeError(f"{path} must be an array")
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 10**9):
            raise RuntimeError(f"{path} violates item bounds")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise RuntimeError(f"{path} must contain unique items")
        for index, child in enumerate(value):
            validate_schema(child, schema["items"], f"{path}[{index}]")
    elif kind == "string":
        if type(value) is not str:
            raise RuntimeError(f"{path} must be a string")
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 10**9):
            raise RuntimeError(f"{path} violates length bounds")
        if "enum" in schema and value not in schema["enum"]:
            raise RuntimeError(f"{path} is not an allowed identifier")
    elif kind in {"number", "integer"}:
        expected = type(value) is int if kind == "integer" else type(value) in {int, float}
        if not expected or isinstance(value, bool):
            raise RuntimeError(f"{path} must be a {kind}")
        if not schema.get("minimum", float("-inf")) <= value <= schema.get("maximum", float("inf")):
            raise RuntimeError(f"{path} violates numeric bounds")


def validate_proposal(proposal: dict[str, Any], investigation: dict[str, Any]) -> None:
    validate_schema(proposal, proposal_schema(investigation), "proposal")
    failed = {d["case"]: d for d in investigation["diagnostics"] if not d["selector_passed"]}
    if set(proposal["diagnostic_findings"]) != set(failed):
        raise RuntimeError("diagnostic findings do not exactly match exposed failed cases")
    for case, observed in failed.items():
        finding = proposal["diagnostic_findings"][case]
        if finding["observed_selection"] != observed["selector_selected"]:
            raise RuntimeError(f"proposal misstates observed selection for {case}")
        if finding["missed_required"] != observed["missed_refs"]:
            raise RuntimeError(f"proposal misstates missed refs for {case}")
        if not set(finding["mechanism_ids"]).intersection(proposal["implementation_inputs"]):
            raise RuntimeError(f"finding mechanisms are disconnected from implementation inputs for {case}")


def _compile_conditions(tables: dict[str, list[dict[str, Any]]], path: str) -> list[dict[str, Any]]:
    mapping = {
        "equals": ("eq", "value"), "not_equals": ("not_eq", "value"),
        "in_values": ("in", "values"), "not_in_values": ("not_in", "values"),
        "contains_token": ("contains_token", "value"), "nonempty": ("nonempty", None),
    }
    compiled: list[dict[str, Any]] = []
    for table, (op, operand) in mapping.items():
        for row in tables[table]:
            condition = {"field": row["field"], "op": op}
            if operand is not None:
                condition[operand] = row[operand]
            compiled.append(condition)
    if not compiled:
        raise RuntimeError(f"{path} must select at least one typed condition")
    return compiled


def compile_policy_tables(response: dict[str, Any]) -> dict[str, Any]:
    validate_schema(response, POLICY_TABLE_SCHEMA, "policy_response")
    rules: list[dict[str, Any]] = []
    filters = [
        {"action": "exclude_if", "conditions": _compile_conditions(row["conditions"], f"filter {i}")}
        for i, row in enumerate(response["filters"])
    ]
    for row in response["token_similarity_rules"]:
        rules.append({"op": "token_similarity", **row})
    for i, row in enumerate(response["constant_if_rules"]):
        rules.append({
            "op": "constant_if", "weight": row["weight"],
            "conditions": _compile_conditions(row["conditions"], f"constant_if {i}"),
        })
    for i, row in enumerate(response["conditional_similarity_rules"]):
        rules.append({
            "op": "conditional_similarity", "weight": row["weight"], "bias": row["bias"],
            "conditions": _compile_conditions(row["conditions"], f"conditional_similarity {i}"),
            "left_fields": row["left_fields"], "right_field": row["right_field"],
        })
    if not rules:
        raise RuntimeError("policy tables must contain at least one scoring rule")
    policy = {
        "format": response["format"], "version": response["version"], "filters": filters,
        "score_rules": rules, "sort": EXPECTED_SORT,
        "budget": {"strategy": "greedy_skip_oversize"},
    }
    gate = validate_policy(policy)
    if not gate.passed:
        raise RuntimeError("compiled policy failed validation: " + "; ".join(gate.errors))
    return policy


def largest_valid_proposal(investigation: dict[str, Any]) -> dict[str, Any]:
    fill = lambda n: "x" * n
    findings: dict[str, Any] = {}
    for observed in investigation["diagnostics"]:
        if observed["selector_passed"]:
            continue
        findings[observed["case"]] = {
            "observed_selection": list(observed["selector_selected"]),
            "missed_required": list(observed["missed_refs"]),
            "mechanism_ids": list(MECHANISM_IDS[:6]), "rationale": fill(140),
        }
    proposal = {
        "hypothesis": fill(180), "observed_evidence": [fill(140)] * 3,
        "diagnostic_findings": findings, "source_diagnosis": fill(180),
        "proposed_change": fill(220), "implementation_inputs": list(MECHANISM_IDS),
        "input_feasibility": fill(140), "expected_benefit": fill(140),
        "risks": [fill(120)] * 3,
    }
    validate_proposal(proposal, investigation)
    return proposal


def largest_valid_policy_response() -> dict[str, Any]:
    conditions = {
        "equals": [{"field": "item.failure_condition", "value": "x" * 32}],
        "not_equals": [{"field": "item.outcome", "value": "x" * 32}],
        "in_values": [{"field": "item.kind", "values": ["x" * 32, "y" * 32]}],
        "not_in_values": [{"field": "item.origin", "values": ["x" * 32, "y" * 32]}],
        "contains_token": [{"field": "item.content", "value": "x" * 32}],
        "nonempty": [{"field": "observer_state.goal"}],
    }
    response = {
        "format": POLICY_FORMAT, "version": POLICY_VERSION,
        "filters": [{"conditions": deepcopy(conditions)} for _ in range(2)],
        "token_similarity_rules": [
            {"weight": 100, "left_fields": ["observer_state.goal", "observer_state.changed_constraints", "observer_state.evidence"], "right_field": "item.content"}
            for _ in range(3)
        ],
        "constant_if_rules": [{"weight": 100, "conditions": deepcopy(conditions)} for _ in range(3)],
        "conditional_similarity_rules": [
            {"weight": 100, "bias": 100, "conditions": deepcopy(conditions),
             "left_fields": ["observer_state.goal", "observer_state.changed_constraints", "observer_state.evidence"],
             "right_field": "item.content"}
            for _ in range(3)
        ],
        "implementation_note": "x" * 160,
    }
    compile_policy_tables(response)
    return response


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


PROPOSAL_SYSTEM = "Formulate one falsifiable selector-policy hypothesis from exposed diagnostics. Return only schema-valid JSON."
POLICY_SYSTEM = "Fill the fixed inert policy tables. Return only schema-valid JSON; never emit source code."


def proposal_prompt(active_source: str, bundle: dict[str, Any], *, structural: bool) -> str:
    payload = {
        "required_case_keys": [d["case"] for d in bundle["investigation"]["diagnostics"] if not d["selector_passed"]],
        "allowed_mechanism_ids": MECHANISM_IDS, "active_source": active_source,
        "observable_diagnostics": bundle["observable_diagnostics"], "unstructured_memory": bundle["unstructured_memory"],
    }
    prompt = "Use every required case key exactly once. Use only exposed evidence and allowed identifiers. INPUT=" + _compact(payload)
    if structural:
        prompt += "\nTYPED_RELATIONAL_OVERLAY=" + _compact(bundle["typed_relational_overlay"])
    return prompt


def policy_prompt(active_source: str, bundle: dict[str, Any], proposal: dict[str, Any], *, structural: bool) -> str:
    payload = {
        "instructions": [
            "Provide all fixed tables, using [] when a table is unused.",
            "Each condition operator has its own table and operand shape; include every table and use [] when unused.",
            "At least one scoring-rule table must be nonempty.",
            "Generalize from mechanism fields; do not encode case names or item refs.",
        ],
        "proposal": proposal, "active_source": active_source,
        "observable_diagnostics": bundle["observable_diagnostics"], "unstructured_memory": bundle["unstructured_memory"],
    }
    prompt = "Compile the hypothesis into the fixed policy tables. INPUT=" + _compact(payload)
    if structural:
        prompt += "\nTYPED_RELATIONAL_OVERLAY=" + _compact(bundle["typed_relational_overlay"])
    return prompt


def qualify_context(model_client: Any, active_source: str, bundle: dict[str, Any]) -> dict[str, Any]:
    proposal = largest_valid_proposal(bundle["investigation"])
    max_policy = largest_valid_policy_response()
    estimator = model_client.budget_manager.estimator
    output_estimates = {
        "proposal": estimator.estimate(_compact(proposal)),
        "policy": estimator.estimate(_compact(max_policy)),
    }
    if output_estimates["proposal"] > PROPOSAL_MAX_TOKENS or output_estimates["policy"] > POLICY_MAX_TOKENS:
        raise RuntimeError(f"largest schema-valid output exceeds generation reserve: {output_estimates}")
    conditions: dict[str, Any] = {}
    for condition in CONDITIONS:
        structural = condition == "BOUNDED_TYPED_STOE"
        stages = {
            "proposal": model_client.budget_manager.plan(
                system=PROPOSAL_SYSTEM, prompt=proposal_prompt(active_source, bundle, structural=structural),
                reserved_generation_tokens=PROPOSAL_MAX_TOKENS,
            ),
            "policy": model_client.budget_manager.plan(
                system=POLICY_SYSTEM, prompt=policy_prompt(active_source, bundle, proposal, structural=structural),
                reserved_generation_tokens=POLICY_MAX_TOKENS,
            ),
        }
        for stage, plan in stages.items():
            if not plan["fits"] or plan["estimated"]["remaining"] < MIN_REMAINING_TOKENS:
                raise RuntimeError(f"{condition} {stage} lacks qualified reserve: {plan['estimated']['remaining']}")
        conditions[condition] = stages
    return {
        "qualified": True, "model_calls": 0, "largest_output_estimated_tokens": output_estimates,
        "minimum_required_remaining_tokens": MIN_REMAINING_TOKENS,
        "minimum_observed_remaining_tokens": min(s["estimated"]["remaining"] for c in conditions.values() for s in c.values()),
        "conditions": conditions,
    }


def exercise_mock_pipelines(model_client: Any, active_source: str, bundle: dict[str, Any]) -> dict[str, Any]:
    """Run the exact two-stage contract with a non-provider client."""
    runs: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        structural = condition == "BOUNDED_TYPED_STOE"
        proposal, proposal_trace = model_client.generate_json(
            system=PROPOSAL_SYSTEM, prompt=proposal_prompt(active_source, bundle, structural=structural),
            schema=proposal_schema(bundle["investigation"]), max_output_tokens=PROPOSAL_MAX_TOKENS,
            seed=PROPOSAL_SEEDS[0],
        )
        validate_proposal(proposal, bundle["investigation"])
        response, policy_trace = model_client.generate_json(
            system=POLICY_SYSTEM, prompt=policy_prompt(active_source, bundle, proposal, structural=structural),
            schema=POLICY_TABLE_SCHEMA, max_output_tokens=POLICY_MAX_TOKENS, seed=POLICY_SEEDS[0],
        )
        policy = compile_policy_tables(response)
        runs.append({
            "condition": condition, "proposal_trace": proposal_trace, "policy_trace": policy_trace,
            "policy": policy, "public_evaluation": evaluate_public_selector(policy_selector(policy)),
        })
    return {"completed": True, "model_calls": 4, "hidden_evaluation_performed": False, "runs": runs}


def run_public_rehearsal(supervisor: Any, bundle_path: Path, output_path: Path) -> dict[str, Any]:
    bundle_bytes = bundle_path.read_bytes()
    bundle = json.loads(bundle_bytes.decode("utf-8"))
    pointer = supervisor.read_active_pointer()
    active_source_path = Path(pointer["source_path"])
    active_source = active_source_path.read_text(encoding="utf-8")
    identity = supervisor.model_client.identity()
    qualification = qualify_context(supervisor.model_client, active_source, bundle)
    result: dict[str, Any] = {
        "schema_version": 1, "harness_version": HARNESS_VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scope": "EXPOSED_PUBLIC_DEVELOPMENT_ONLY",
        "hidden_evaluation_performed": False, "activation_performed": False,
        "model": {"name": identity.name, "digest": identity.digest, "ollama_version": identity.ollama_version},
        "settings": {
            "temperature": 0, "top_p": 0.9, "top_k": 40, "num_ctx": supervisor.model_client.context_limit_tokens,
            "proposal_max_output_tokens": PROPOSAL_MAX_TOKENS, "policy_max_output_tokens": POLICY_MAX_TOKENS,
            "proposal_seeds": list(PROPOSAL_SEEDS), "policy_seeds": list(POLICY_SEEDS), "retry_count": 0,
        },
        "input_bundle": {"path": str(bundle_path), "sha256": hashlib.sha256(bundle_bytes).hexdigest()},
        "active_baseline": {"path": str(active_source_path), "sha256": pointer["sha256"]},
        "qualification": qualification, "runs": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        for repetition in range(REPETITIONS):
            for condition in CONDITIONS:
                structural = condition == "BOUNDED_TYPED_STOE"
                run: dict[str, Any] = {"repetition": repetition + 1, "condition": condition, "status": "started"}
                result["runs"].append(run)
                try:
                    proposal, trace = supervisor.model_client.generate_json(
                        system=PROPOSAL_SYSTEM, prompt=proposal_prompt(active_source, bundle, structural=structural),
                        schema=proposal_schema(bundle["investigation"]), max_output_tokens=PROPOSAL_MAX_TOKENS,
                        seed=PROPOSAL_SEEDS[repetition],
                    )
                    run.update({"proposal": proposal, "proposal_trace": trace})
                    validate_proposal(proposal, bundle["investigation"])
                    response, trace = supervisor.model_client.generate_json(
                        system=POLICY_SYSTEM, prompt=policy_prompt(active_source, bundle, proposal, structural=structural),
                        schema=POLICY_TABLE_SCHEMA, max_output_tokens=POLICY_MAX_TOKENS,
                        seed=POLICY_SEEDS[repetition],
                    )
                    run.update({"policy_table_response": response, "policy_trace": trace})
                    policy = compile_policy_tables(response)
                    run["compiled_policy"] = policy
                    run["public_evaluation"] = evaluate_public_selector(policy_selector(policy))
                    run["status"] = "completed"
                except Exception as exc:
                    run.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
                supervisor._atomic_write_json(output_path, result)
        completed = sum(run["status"] == "completed" for run in result["runs"])
        result["summary"] = {
            "pipeline_count": REPETITIONS * len(CONDITIONS), "completed_pipeline_count": completed,
            "format_reliability": completed / (REPETITIONS * len(CONDITIONS)),
            "harness_qualified": completed == REPETITIONS * len(CONDITIONS),
            "qualification_rule": "all ordinary and structural public-development pipelines complete without retry",
            "scientific_claim": "format/harness qualification only; no hidden-case or SToE advantage evidence",
        }
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        supervisor._atomic_write_json(output_path, result)
        return result
    except BaseException:
        supervisor._atomic_write_json(output_path, result)
        raise
