from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


FIELDS = {"status", "decision", "evidence", "risks", "next_action"}
ROLES = {"planner": "PLANNER.md", "coder": "CODER.md", "reviewer": "REVIEWER.md", "test_analyst": "TEST_ANALYST.md"}
STATUSES = {"success", "failure", "deferred"}
MAX_RAW_BYTES = 1_000_000
MAX_CANDIDATE_ARTIFACT_BYTES = 1_000_000
INSTRUCTION_LABELS = {"architecture", "escalation", "contract", "role"}
ARTIFACT_FIELDS = {"path", "sha256", "size_bytes"}
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_ARTIFACT_PARTS = {
    ".git", ".env", "credentials", "secrets", "protected_evals",
    "research_checkpoints",
}


class LocalDevelopmentError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def instruction_root() -> Path:
    return Path(__file__).resolve().parents[2] / "local_development"


def load_instructions(role: str, root: Path | None = None) -> dict[str, dict[str, str]]:
    if role not in ROLES:
        raise LocalDevelopmentError("unsupported local-development role")
    base = (root or instruction_root()).resolve()
    result: dict[str, dict[str, str]] = {}
    names = (
        ("architecture", "ARCHITECTURE_V2.md"),
        ("escalation", "CHATGPT_ESCALATION.md"),
        ("contract", "WORKER_CONTRACT_V2.md"),
        ("role", ROLES[role]),
    )
    for label, name in names:
        path = (base / name).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise LocalDevelopmentError("canonical instruction artifact is missing or outside its root")
        raw = path.read_bytes()
        if not raw or len(raw) > 32_000:
            raise LocalDevelopmentError("canonical instruction artifact is empty or oversized")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LocalDevelopmentError("canonical instruction artifact is not UTF-8") from exc
        result[label] = {"version": "v2", "path": path.relative_to(base.parent).as_posix(), "sha256": _sha256(raw), "content": content}
    return result


def control_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": sorted(STATUSES)},
            "decision": {"type": "string", "maxLength": 320},
            "evidence": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 180}},
            "risks": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 160}},
            "next_action": {"type": "string", "maxLength": 240},
        },
        "required": sorted(FIELDS),
        "additionalProperties": False,
    }


def validate_control(value: Any, *, known_metadata: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise LocalDevelopmentError("control response must contain exactly five fields")
    if not isinstance(value["status"], str) or value["status"] not in STATUSES:
        raise LocalDevelopmentError("invalid control status")
    for field, limit in (("decision", 320), ("next_action", 240)):
        if not isinstance(value[field], str) or len(value[field]) > limit:
            raise LocalDevelopmentError(f"invalid {field}")
    for field, count, chars in (("evidence", 4, 180), ("risks", 3, 160)):
        items = value[field]
        if not isinstance(items, list) or len(items) > count or any(not isinstance(item, str) or len(item) > chars for item in items):
            raise LocalDevelopmentError(f"invalid {field}")
    if value["status"] == "success" and not value["evidence"]:
        raise LocalDevelopmentError("success requires evidence")
    if value["status"] in {"failure", "deferred"} and not value["risks"]:
        raise LocalDevelopmentError("failure or deferred status requires risks")
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()
    for item in known_metadata:
        if isinstance(item, str) and item and item.casefold() in serialized:
            raise LocalDevelopmentError("control response repeats supervisor-known metadata")
    return value


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _preserve_raw(raw: bytes, raw_path: Path) -> dict[str, Any]:
    preserved = raw[:MAX_RAW_BYTES]
    metadata = {
        "path": raw_path.as_posix(),
        "sha256": _sha256(raw),
        "original_bytes": len(raw),
        "preserved_bytes": len(preserved),
        "truncated": len(raw) > len(preserved),
    }
    _atomic_write(raw_path, preserved)
    metadata_path = raw_path.with_suffix(raw_path.suffix + ".metadata.json")
    _atomic_write(
        metadata_path,
        (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return {**metadata, "metadata_path": metadata_path.as_posix()}


def parse_preserved_control(
    raw: bytes,
    raw_path: Path,
    *,
    known_metadata: tuple[str, ...] = (),
) -> dict[str, Any]:
    preservation = _preserve_raw(raw, raw_path)
    if preservation["truncated"]:
        raise LocalDevelopmentError(
            f"raw response exceeded hard cap; capped evidence at {preservation['metadata_path']}"
        )
    try:
        envelope = json.loads(raw.decode("utf-8"))
        if not isinstance(envelope, dict) or envelope.get("done") is not True:
            raise LocalDevelopmentError("Ollama envelope is incomplete")
        done_reason = envelope.get("done_reason")
        if isinstance(done_reason, str) and done_reason.casefold() in {"length", "error"}:
            raise LocalDevelopmentError(f"Ollama envelope ended with {done_reason}")
        response = envelope["response"]
        if not isinstance(response, str):
            raise LocalDevelopmentError("Ollama response payload must be a JSON string")
        control = validate_control(json.loads(response), known_metadata=known_metadata)
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, LocalDevelopmentError) as exc:
        raise LocalDevelopmentError(f"preserved response failed closed: {exc}") from exc
    return control


def validate_candidate_artifact(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != ARTIFACT_FIELDS:
        raise LocalDevelopmentError("candidate artifact must contain only path, sha256, and size_bytes")
    path_value = value["path"]
    if not isinstance(path_value, str) or not path_value or len(path_value) > 240 or "\\" in path_value:
        raise LocalDevelopmentError("invalid candidate artifact path")
    path = PurePosixPath(path_value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part.casefold() in FORBIDDEN_ARTIFACT_PARTS for part in path.parts)
        or path.suffix.casefold() != ".json"
    ):
        raise LocalDevelopmentError("candidate artifact path is not an inert bounded JSON path")
    if not isinstance(value["sha256"], str) or not HEX_SHA256.fullmatch(value["sha256"]):
        raise LocalDevelopmentError("invalid candidate artifact SHA-256")
    size = value["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_CANDIDATE_ARTIFACT_BYTES:
        raise LocalDevelopmentError("invalid candidate artifact size")
    return dict(value)


def _validate_instruction_artifacts(
    instructions: Any,
) -> dict[str, dict[str, str]]:
    if not isinstance(instructions, dict) or set(instructions) != INSTRUCTION_LABELS:
        raise LocalDevelopmentError("trusted instruction set is incomplete")
    checked: dict[str, dict[str, str]] = {}
    for label, item in instructions.items():
        if not isinstance(item, dict) or set(item) != {"version", "path", "sha256", "content"}:
            raise LocalDevelopmentError("invalid trusted instruction artifact")
        if item["version"] != "v2" or not isinstance(item["path"], str):
            raise LocalDevelopmentError("invalid trusted instruction identity")
        content = item["content"]
        if not isinstance(content, str) or _sha256(content.encode("utf-8")) != item["sha256"]:
            raise LocalDevelopmentError("instruction content does not match its SHA-256")
        checked[label] = dict(item)
    return checked


def trusted_envelope(
    control: dict[str, Any], *, action_id: str, role: str, model: str, digest: str,
    instructions: dict[str, dict[str, str]], artifact: dict[str, str] | None = None,
) -> dict[str, Any]:
    instructions = _validate_instruction_artifacts(instructions)
    metadata_values = (
        action_id,
        role,
        model,
        digest,
        *(item["path"] for item in instructions.values()),
        *(item["sha256"] for item in instructions.values()),
    )
    control = validate_control(control, known_metadata=metadata_values)
    if (
        role not in ROLES
        or not isinstance(action_id, str)
        or not action_id
        or len(action_id) > 128
        or not isinstance(model, str)
        or not model
        or len(model) > 160
        or not isinstance(digest, str)
        or not HEX_SHA256.fullmatch(digest)
    ):
        raise LocalDevelopmentError("invalid trusted worker identity")
    checked_artifact = None if artifact is None else validate_candidate_artifact(artifact)
    if role == "coder" and control["status"] == "success" and checked_artifact is None:
        raise LocalDevelopmentError("successful coder result requires a separate candidate artifact")
    return {
        "action_id": action_id,
        "role": role,
        "model": model,
        "digest": digest,
        "control": control,
        "failure_condition": control["risks"][0] if control["status"] != "success" else "",
        "instruction_artifacts": {
            key: {field: value[field] for field in ("version", "path", "sha256")}
            for key, value in instructions.items()
        },
        "candidate_artifact": checked_artifact,
    }


def model_instructions(role: str, root: Path | None = None) -> tuple[str, dict[str, dict[str, str]]]:
    artifacts = load_instructions(role, root)
    # Architecture and escalation are hashed governance evidence, not recurring
    # model context. Workers receive only the compact contract and their role.
    text = artifacts["contract"]["content"] + "\n\n" + artifacts["role"]["content"]
    return text, artifacts


def _ensure_ip(field: Any, *, ref: str, identity: dict[str, Any], create: dict[str, Any]) -> dict[str, Any]:
    try:
        existing = field.get_ip(ref)
    except (AttributeError, KeyError):
        return field.add_ip(ref=ref, **create)
    for key, expected in identity.items():
        if existing.get(key) != expected:
            raise LocalDevelopmentError(f"stable SToE ref collision for {ref}")
    return existing


def _ensure_relation(field: Any, *, source_ref: str, target_ref: str, relation: str, note: str) -> None:
    edges: list[dict[str, Any]] = []
    try:
        edges.extend(field.get_ip(source_ref).get("edges", []))
    except (AttributeError, KeyError):
        pass
    edges.extend(getattr(field, "edges", []))
    if any(
        edge.get("source", edge.get("source_ref")) == source_ref
        and edge.get("target", edge.get("target_ref")) == target_ref
        and edge.get("relation") == relation
        for edge in edges
    ):
        return
    field.add_relation(source_ref=source_ref, target_ref=target_ref, relation=relation, note=note)


def record_envelope(field: Any, envelope: dict[str, Any], *, goal: str, session_id: str) -> dict[str, Any]:
    """Persist trusted identities and compact worker control; never raw payloads."""
    required = {
        "action_id", "role", "model", "digest", "control", "failure_condition",
        "instruction_artifacts", "candidate_artifact",
    }
    if not isinstance(envelope, dict) or set(envelope) != required:
        raise LocalDevelopmentError("invalid trusted envelope")
    metadata_values = (envelope["action_id"], envelope["role"], envelope["model"], envelope["digest"])
    control = validate_control(envelope["control"], known_metadata=metadata_values)
    expected_failure = control["risks"][0] if control["status"] != "success" else ""
    if envelope["failure_condition"] != expected_failure:
        raise LocalDevelopmentError("trusted failure condition does not match control")
    instruction_items = envelope["instruction_artifacts"]
    if not isinstance(instruction_items, dict) or set(instruction_items) != INSTRUCTION_LABELS:
        raise LocalDevelopmentError("trusted envelope instruction set is incomplete")
    candidate = envelope["candidate_artifact"]
    if candidate is not None:
        candidate = validate_candidate_artifact(candidate)
    if envelope["role"] == "coder" and control["status"] == "success" and candidate is None:
        raise LocalDevelopmentError("successful coder result requires a separate candidate artifact")
    action_ref = "LDA_" + _sha256(envelope["action_id"].encode())[:16]
    result_ref = "LDR_" + _sha256((envelope["action_id"] + ":result").encode())[:16]
    instruction_refs = []
    for item in instruction_items.values():
        if (
            not isinstance(item, dict)
            or set(item) != {"version", "path", "sha256"}
            or item["version"] != "v2"
            or not isinstance(item["path"], str)
            or not isinstance(item["sha256"], str)
            or not HEX_SHA256.fullmatch(item["sha256"])
        ):
            raise LocalDevelopmentError("invalid recorded instruction identity")
        ref = "LDI_" + item["sha256"][:16]
        content = f"Instruction {item['path']} sha256={item['sha256']}"
        _ensure_ip(
            field,
            ref=ref,
            identity={"content": content, "kind": "InstructionArtifactIP", "metadata": item},
            create={"content": content, "kind": "InstructionArtifactIP", "origin": "runtime_reasoning", "outcome": "active", "session_id": session_id, "metadata": item, "visible": True},
        )
        instruction_refs.append(ref)
    action_metadata = {key: envelope[key] for key in ("action_id", "role", "model", "digest")}
    _ensure_ip(
        field,
        ref=action_ref,
        identity={"content": goal, "kind": "WorkerActionIP", "metadata": action_metadata},
        create={"content": goal, "kind": "WorkerActionIP", "origin": "runtime_reasoning", "outcome": control["status"], "session_id": session_id, "metadata": action_metadata, "visible": True},
    )
    origin = "failure_history" if control["status"] != "success" else "runtime_reasoning"
    result_metadata = {"control": control, "candidate_artifact": candidate}
    _ensure_ip(
        field,
        ref=result_ref,
        identity={"content": control["decision"], "kind": "WorkerResultIP", "failure_condition": expected_failure, "metadata": result_metadata},
        create={"content": control["decision"], "kind": "WorkerResultIP", "origin": origin, "outcome": control["status"], "failure_condition": expected_failure, "session_id": session_id, "metadata": result_metadata, "visible": True},
    )
    for ref in instruction_refs:
        _ensure_relation(field, source_ref=action_ref, target_ref=ref, relation="depends_on", note="trusted worker action used this exact instruction artifact")
    _ensure_relation(field, source_ref=result_ref, target_ref=action_ref, relation="generated_by", note="validated compact worker result generated by action")
    artifact_ref = None
    if candidate is not None:
        artifact_ref = "LDC_" + candidate["sha256"][:16]
        artifact_content = f"Candidate artifact sha256={candidate['sha256']} size={candidate['size_bytes']}"
        _ensure_ip(
            field,
            ref=artifact_ref,
            identity={"content": artifact_content, "kind": "ArtifactIP", "metadata": candidate},
            create={"content": artifact_content, "kind": "ArtifactIP", "origin": "runtime_reasoning", "outcome": "supported", "session_id": session_id, "metadata": candidate, "visible": True},
        )
        _ensure_relation(field, source_ref=artifact_ref, target_ref=action_ref, relation="generated_by", note="candidate artifact generated by this exact worker action")
        _ensure_relation(field, source_ref=result_ref, target_ref=artifact_ref, relation="depends_on", note="worker result refers to this canonical candidate artifact")
    evaluation_ref = "LDE_" + _sha256((envelope["action_id"] + ":evaluation").encode())[:16]
    evaluation_content = "Worker Contract v2 validation passed"
    evaluation_metadata = {"action_id": envelope["action_id"]}
    _ensure_ip(
        field,
        ref=evaluation_ref,
        identity={"content": evaluation_content, "kind": "evaluation", "metadata": evaluation_metadata},
        create={"content": evaluation_content, "kind": "evaluation", "origin": "evaluation", "outcome": "passed", "session_id": session_id, "metadata": evaluation_metadata, "visible": True},
    )
    _ensure_relation(field, source_ref=evaluation_ref, target_ref=result_ref, relation="evaluates", note="Evaluation of validated Worker Contract v2 result")
    return {"action": action_ref, "result": result_ref, "instructions": instruction_refs, "artifact": artifact_ref, "evaluation": evaluation_ref}
