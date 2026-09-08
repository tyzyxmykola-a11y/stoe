from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


POLICY_FORMAT = "stoe.selection_policy"
POLICY_VERSION = 1
MAX_POLICY_BYTES = 16_384
MAX_RULES = 24
MAX_FILTERS = 12
MAX_CONDITIONS_PER_RULE = 8
MAX_FIELDS_PER_RULE = 8
MAX_ITEMS = 512
MAX_ITEM_OUTPUT = 128
MAX_OUTPUT_CHARS = 65_536
MAX_FIELD_CHARS = 8_192
MAX_TOTAL_INPUT_CHARS = 262_144
MAX_OPERATIONS = 200_000
MAX_TOKENS_PER_VALUE = 1_024

OBSERVER_FIELDS = {
    "observer_state.goal",
    "observer_state.active_constraints",
    "observer_state.changed_constraints",
    "observer_state.evidence",
    "observer_state.open_questions",
}
ITEM_FIELDS = {
    "item.ref",
    "item.content",
    "item.origin",
    "item.kind",
    "item.outcome",
    "item.failure_condition",
    "item.created_order",
}
TEXT_FIELDS = (OBSERVER_FIELDS | ITEM_FIELDS) - {"item.created_order"}
ALL_FIELDS = OBSERVER_FIELDS | ITEM_FIELDS
CONDITION_OPS = {"eq", "not_eq", "in", "not_in", "contains_token", "nonempty"}
RULE_OPS = {"token_similarity", "constant_if", "conditional_similarity"}
EXPECTED_SORT = [
    {"key": "score", "direction": "desc"},
    {"key": "item.created_order", "direction": "desc"},
    {"key": "item.ref", "direction": "asc"},
]


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PolicyValidationResult:
    passed: bool
    errors: tuple[str, ...]
    estimated_operations: int = 0


def validate_policy(policy: object, *, item_count: int = MAX_ITEMS) -> PolicyValidationResult:
    errors: list[str] = []
    if type(policy) is not dict:
        return PolicyValidationResult(False, ("policy must be a JSON object",))
    try:
        encoded_size = len(json.dumps(policy, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        return PolicyValidationResult(False, (f"policy is not bounded JSON data: {type(exc).__name__}",))
    if encoded_size > MAX_POLICY_BYTES:
        errors.append(f"policy exceeds {MAX_POLICY_BYTES} bytes")
    allowed_top = {"format", "version", "filters", "score_rules", "sort", "budget"}
    if set(policy) != allowed_top:
        errors.append(f"policy fields must be exactly {sorted(allowed_top)}")
    if policy.get("format") != POLICY_FORMAT:
        errors.append(f"policy format must be {POLICY_FORMAT!r}")
    if policy.get("version") != POLICY_VERSION:
        errors.append(f"policy version must be {POLICY_VERSION}")

    filters = policy.get("filters")
    if type(filters) is not list:
        errors.append("filters must be a JSON array")
        filters = []
    elif len(filters) > MAX_FILTERS:
        errors.append(f"filters exceed {MAX_FILTERS}")
    for index, entry in enumerate(filters):
        if type(entry) is not dict or set(entry) != {"action", "conditions"}:
            errors.append(f"filter {index} must contain only action and conditions")
            continue
        if entry.get("action") != "exclude_if":
            errors.append(f"filter {index} action must be exclude_if")
        errors.extend(_validate_conditions(entry.get("conditions"), f"filter {index}"))

    rules = policy.get("score_rules")
    if type(rules) is not list or not rules:
        errors.append("score_rules must be a non-empty JSON array")
        rules = []
    elif len(rules) > MAX_RULES:
        errors.append(f"score_rules exceed {MAX_RULES}")
    complexity = len(filters)
    for index, rule in enumerate(rules):
        if type(rule) is not dict:
            errors.append(f"score rule {index} must be an object")
            continue
        op = rule.get("op")
        if op not in RULE_OPS:
            errors.append(f"score rule {index} has unsupported op {op!r}")
            continue
        common = {"op", "weight"}
        if op == "token_similarity":
            expected = common | {"left_fields", "right_field"}
        elif op == "constant_if":
            expected = common | {"conditions"}
        else:
            expected = common | {"conditions", "left_fields", "right_field", "bias"}
        if set(rule) != expected:
            errors.append(f"score rule {index} fields must be exactly {sorted(expected)}")
        errors.extend(_validate_number(rule.get("weight"), f"score rule {index} weight"))
        if op in {"token_similarity", "conditional_similarity"}:
            errors.extend(_validate_text_fields(rule.get("left_fields"), f"score rule {index} left_fields"))
            if rule.get("right_field") not in TEXT_FIELDS:
                errors.append(f"score rule {index} right_field is unavailable")
            complexity += len(rule.get("left_fields")) if type(rule.get("left_fields")) is list else 1
        if op in {"constant_if", "conditional_similarity"}:
            errors.extend(_validate_conditions(rule.get("conditions"), f"score rule {index}"))
            complexity += len(rule.get("conditions")) if type(rule.get("conditions")) is list else 1
        if op == "conditional_similarity":
            errors.extend(_validate_number(rule.get("bias"), f"score rule {index} bias"))

    if policy.get("sort") != EXPECTED_SORT:
        errors.append("sort must be the fixed deterministic score/created_order/ref ordering")
    budget = policy.get("budget")
    if type(budget) is not dict or budget != {"strategy": "greedy_skip_oversize"}:
        errors.append("budget must specify only greedy_skip_oversize")

    if type(item_count) is not int or isinstance(item_count, bool) or not 0 <= item_count <= MAX_ITEMS:
        errors.append(f"item_count must be between 0 and {MAX_ITEMS}")
        bounded_items = MAX_ITEMS
    else:
        bounded_items = item_count
    estimated_operations = bounded_items * max(1, complexity)
    if estimated_operations > MAX_OPERATIONS:
        errors.append(f"estimated operations exceed {MAX_OPERATIONS}")
    return PolicyValidationResult(not errors, tuple(sorted(set(errors))), estimated_operations)


def load_policy(path: str | Path) -> dict[str, Any]:
    policy_path = Path(path).resolve()
    size = policy_path.stat().st_size
    if size > MAX_POLICY_BYTES:
        raise PolicyError(f"policy exceeds {MAX_POLICY_BYTES} bytes")
    try:
        value = json.loads(policy_path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PolicyError(f"malformed policy: {type(exc).__name__}: {exc}") from exc
    result = validate_policy(value)
    if not result.passed:
        raise PolicyError("invalid policy: " + "; ".join(result.errors))
    return value


def execute_policy(
    policy: object,
    observer_state: dict,
    items: list[dict],
    max_items: int,
    max_chars: int,
) -> list[str]:
    if type(observer_state) is not dict or type(items) is not list:
        raise PolicyError("observer_state must be an object and items must be an array")
    if len(items) > MAX_ITEMS:
        raise PolicyError(f"items exceed {MAX_ITEMS}")
    if type(max_items) is not int or isinstance(max_items, bool) or not 0 <= max_items <= MAX_ITEM_OUTPUT:
        raise PolicyError(f"max_items must be between 0 and {MAX_ITEM_OUTPUT}")
    if type(max_chars) is not int or isinstance(max_chars, bool) or not 0 <= max_chars <= MAX_OUTPUT_CHARS:
        raise PolicyError(f"max_chars must be between 0 and {MAX_OUTPUT_CHARS}")
    validation = validate_policy(policy, item_count=len(items))
    if not validation.passed:
        raise PolicyError("invalid policy: " + "; ".join(validation.errors))

    safe_observer, safe_items = _project_inputs(observer_state, items)
    ranked: list[tuple[float, int, str, dict[str, Any]]] = []
    for item in safe_items:
        if any(_conditions_match(entry["conditions"], safe_observer, item) for entry in policy["filters"]):
            continue
        score = 0.0
        for rule in policy["score_rules"]:
            op = rule["op"]
            if op == "token_similarity":
                score += rule["weight"] * _field_similarity(
                    rule["left_fields"], rule["right_field"], safe_observer, item
                )
            elif op == "constant_if" and _conditions_match(rule["conditions"], safe_observer, item):
                score += rule["weight"]
            elif op == "conditional_similarity" and _conditions_match(
                rule["conditions"], safe_observer, item
            ):
                score += rule["bias"] + rule["weight"] * _field_similarity(
                    rule["left_fields"], rule["right_field"], safe_observer, item
                )
        ranked.append((score, item["created_order"], item["ref"], item))
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))

    selected: list[str] = []
    used_chars = 0
    for _score, _order, ref, item in ranked:
        size = len(item["content"])
        if len(selected) >= max_items:
            break
        if used_chars + size > max_chars:
            continue
        selected.append(ref)
        used_chars += size
    return selected


def policy_selector(policy: dict[str, Any]):
    def select_context(observer_state: dict, items: list[dict], max_items: int, max_chars: int) -> list[str]:
        return execute_policy(policy, observer_state, items, max_items, max_chars)

    return select_context


def _validate_number(value: object, label: str) -> list[str]:
    if type(value) not in {int, float} or not math.isfinite(float(value)) or abs(float(value)) > 100.0:
        return [f"{label} must be a finite number with absolute value <= 100"]
    return []


def _validate_text_fields(value: object, label: str) -> list[str]:
    if type(value) is not list or not value or len(value) > MAX_FIELDS_PER_RULE:
        return [f"{label} must contain 1..{MAX_FIELDS_PER_RULE} fields"]
    if len(value) != len(set(value)) or any(type(field) is not str or field not in TEXT_FIELDS for field in value):
        return [f"{label} contains duplicate or unavailable fields"]
    return []


def _validate_conditions(value: object, label: str) -> list[str]:
    if type(value) is not list or not value or len(value) > MAX_CONDITIONS_PER_RULE:
        return [f"{label} conditions must contain 1..{MAX_CONDITIONS_PER_RULE} entries"]
    errors: list[str] = []
    for index, condition in enumerate(value):
        prefix = f"{label} condition {index}"
        if type(condition) is not dict:
            errors.append(f"{prefix} must be an object")
            continue
        op = condition.get("op")
        expected = {"field", "op", "values"} if op in {"in", "not_in"} else {"field", "op", "value"}
        if op == "nonempty":
            expected = {"field", "op"}
        if set(condition) != expected:
            errors.append(f"{prefix} has invalid fields")
        if condition.get("field") not in ALL_FIELDS:
            errors.append(f"{prefix} names an unavailable field")
        if op not in CONDITION_OPS:
            errors.append(f"{prefix} has unsupported op {op!r}")
        if op in {"in", "not_in"}:
            values = condition.get("values")
            if type(values) is not list or not values or len(values) > 16 or any(not _small_scalar(v) for v in values):
                errors.append(f"{prefix} values must contain 1..16 small scalars")
        elif op != "nonempty" and not _small_scalar(condition.get("value")):
            errors.append(f"{prefix} value must be a small scalar")
    return errors


def _small_scalar(value: object) -> bool:
    if type(value) is float and not math.isfinite(value):
        return False
    return type(value) in {str, int, float, bool} and len(str(value)) <= 256


def _project_inputs(observer_state: dict, items: list[dict]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    total_chars = 0
    observer: dict[str, Any] = {}
    for field in OBSERVER_FIELDS:
        key = field.split(".", 1)[1]
        value, chars = _bounded_text_value(observer_state.get(key, [] if key != "goal" else ""), field)
        observer[key] = value
        total_chars += chars
    projected: list[dict[str, Any]] = []
    refs: set[str] = set()
    for index, raw in enumerate(items):
        if type(raw) is not dict:
            raise PolicyError(f"item {index} must be an object")
        ref = raw.get("ref")
        if type(ref) is not str or not ref or len(ref) > 256 or ref in refs:
            raise PolicyError(f"item {index} has invalid or duplicate ref")
        refs.add(ref)
        item: dict[str, Any] = {"ref": ref}
        total_chars += len(ref)
        for key in ("content", "origin", "kind", "outcome", "failure_condition"):
            value, chars = _bounded_text_value(raw.get(key, ""), f"item.{key}", allow_list=False)
            item[key] = value
            total_chars += chars
        order = raw.get("created_order", 0)
        if type(order) is not int or isinstance(order, bool) or abs(order) > 1_000_000_000:
            raise PolicyError(f"item {index} created_order is invalid")
        item["created_order"] = order
        projected.append(item)
    if total_chars > MAX_TOTAL_INPUT_CHARS:
        raise PolicyError(f"projected input exceeds {MAX_TOTAL_INPUT_CHARS} characters")
    return observer, projected


def _bounded_text_value(value: object, label: str, *, allow_list: bool = True) -> tuple[Any, int]:
    if type(value) is str:
        if len(value) > MAX_FIELD_CHARS:
            raise PolicyError(f"{label} exceeds {MAX_FIELD_CHARS} characters")
        return value, len(value)
    if allow_list and type(value) is list and all(type(item) is str for item in value):
        if len(value) > 128 or any(len(item) > MAX_FIELD_CHARS for item in value):
            raise PolicyError(f"{label} list exceeds its bound")
        return list(value), sum(len(item) for item in value)
    raise PolicyError(f"{label} must be {'a string or list[str]' if allow_list else 'a string'}")


def _value(field: str, observer: dict[str, Any], item: dict[str, Any]) -> Any:
    scope, key = field.split(".", 1)
    return observer[key] if scope == "observer_state" else item[key]


def _text(field: str, observer: dict[str, Any], item: dict[str, Any]) -> str:
    value = _value(field, observer, item)
    return " ".join(value) if type(value) is list else str(value)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower())[:MAX_TOKENS_PER_VALUE])


def _similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a | b))


def _field_similarity(
    left_fields: list[str], right_field: str, observer: dict[str, Any], item: dict[str, Any]
) -> float:
    left = " ".join(_text(field, observer, item) for field in left_fields)
    return _similarity(left, _text(right_field, observer, item))


def _conditions_match(conditions: list[dict[str, Any]], observer: dict[str, Any], item: dict[str, Any]) -> bool:
    for condition in conditions:
        actual = _value(condition["field"], observer, item)
        normalized = " ".join(actual) if type(actual) is list else actual
        op = condition["op"]
        if op == "eq" and normalized != condition["value"]:
            return False
        if op == "not_eq" and normalized == condition["value"]:
            return False
        if op == "in" and normalized not in condition["values"]:
            return False
        if op == "not_in" and normalized in condition["values"]:
            return False
        if op == "contains_token" and str(condition["value"]).lower() not in _tokens(str(normalized)):
            return False
        if op == "nonempty" and not normalized:
            return False
    return True
