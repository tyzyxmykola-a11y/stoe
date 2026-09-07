from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .token_budget import TokenEstimator, compact_text


SCHEMA_VERSION = 1
ACTION_STATUSES = {"pending", "running", "completed", "uncertain", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResearchStateStore:
    def __init__(
        self,
        *,
        runtime_dir: Path,
        checkpoint_dir: Path,
        bootstrap_path: Path | None = None,
        project_root: Path | None = None,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self.runtime_dir = runtime_dir.resolve()
        self.checkpoint_dir = checkpoint_dir.resolve()
        self.bootstrap_path = bootstrap_path.resolve() if bootstrap_path else None
        self.project_root = (project_root or checkpoint_dir.parent).resolve()
        self.estimator = estimator or TokenEstimator()
        self.state_path = self.runtime_dir / "research_state.json"
        self.artifact_dir = self.runtime_dir / "research_artifacts"
        self.latest_path = self.checkpoint_dir / "LATEST.json"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if self.state_path.exists():
            return self._read_validated(self.state_path)
        if self.latest_path.exists():
            pointer = self._read_json(self.latest_path)
            checkpoint = self.checkpoint_dir / str(pointer["file"])
            if _sha256_file(checkpoint) != pointer["sha256"]:
                raise RuntimeError("research checkpoint hash mismatch")
            envelope = self._read_json(checkpoint)
            state = envelope.get("state")
            if not isinstance(state, dict):
                raise RuntimeError("research checkpoint does not contain state")
            self._validate_state(state)
            self.save(state)
            return state
        if self.bootstrap_path and self.bootstrap_path.exists():
            state = self._read_validated(self.bootstrap_path)
            self.save(state)
            return state
        state = self.empty_state()
        self.save(state)
        return state

    @staticmethod
    def empty_state() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "objective": "",
            "current_task": "",
            "active_hypothesis": None,
            "evidence": [],
            "author_definitions": [],
            "corrections": [],
            "decisions": [],
            "unresolved_questions": [],
            "versions": {"active": None, "candidate": None},
            "actions": [],
            "artifacts": [],
            "next_executable_step": "",
            "measurements": {"provider_usage": [], "budgets": [], "truncations": [], "checkpoint_events": []},
            "updated_at": _now(),
        }

    def save(self, state: dict[str, Any]) -> None:
        value = deepcopy(state)
        value["updated_at"] = _now()
        self._validate_state(value)
        self._atomic_json(self.state_path, value)

    def checkpoint(self, *, reason: str, budget: dict[str, Any] | None = None) -> dict[str, Any]:
        state = self.load()
        fingerprint = self._state_fingerprint(state)
        if self.latest_path.exists():
            latest = self._read_json(self.latest_path)
            if latest.get("state_fingerprint") == fingerprint:
                return {**latest, "created": False, "reason": "state unchanged since latest checkpoint"}
        checkpoint_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + fingerprint[:10]
        event = {
            "checkpoint_id": checkpoint_id,
            "reason": reason,
            "created_at": _now(),
            "budget": budget or {},
        }
        state.setdefault("measurements", {}).setdefault("checkpoint_events", []).append(event)
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "checkpoint_id": checkpoint_id,
            "state_fingerprint": self._state_fingerprint(state),
            "reason": reason,
            "created_at": event["created_at"],
            "state": state,
        }
        path = self.checkpoint_dir / f"{checkpoint_id}.json"
        self._atomic_json(path, envelope)
        pointer = {
            "checkpoint_id": checkpoint_id,
            "file": path.name,
            "sha256": _sha256_file(path),
            "state_fingerprint": fingerprint,
            "created_at": event["created_at"],
        }
        self._atomic_json(self.latest_path, pointer)
        self.save(state)
        if self.bootstrap_path is not None:
            self._atomic_json(self.bootstrap_path, state)
        return {**pointer, "path": str(path), "created": True}

    def begin_action(self, *, action_id: str, description: str) -> dict[str, Any]:
        state = self.load()
        existing = next((item for item in state["actions"] if item["action_id"] == action_id), None)
        if existing:
            if existing["status"] == "completed":
                return {"started": False, "duplicate_completed": True, "action": existing}
            if existing["status"] in {"running", "uncertain"}:
                return {"started": False, "requires_reconciliation": True, "action": existing}
            existing.update({"status": "running", "started_at": _now(), "description": description})
            action = existing
        else:
            action = {
                "action_id": action_id,
                "description": description,
                "status": "running",
                "started_at": _now(),
                "completed_at": None,
                "result_refs": [],
            }
            state["actions"].append(action)
        self.save(state)
        return {"started": True, "action": action}

    def set_action_status(
        self, *, action_id: str, status: str, result_refs: list[str] | None = None
    ) -> dict[str, Any]:
        if status not in ACTION_STATUSES:
            raise ValueError(f"invalid action status: {status}")
        state = self.load()
        action = next((item for item in state["actions"] if item["action_id"] == action_id), None)
        if action is None:
            raise KeyError(action_id)
        action["status"] = status
        action["result_refs"] = list(result_refs or action.get("result_refs", []))
        if status == "completed":
            action["completed_at"] = _now()
        self.save(state)
        return action

    def register_artifact(
        self,
        *,
        ref: str,
        path: Path,
        summary: str,
        kind: str,
        provenance: str,
        source_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        source = path.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        state = self.load()
        try:
            stored_path = source.relative_to(self.project_root).as_posix()
        except ValueError:
            stored_path = str(source)
        artifact = {
            "ref": ref,
            "path": stored_path,
            "sha256": _sha256_file(source),
            "bytes": source.stat().st_size,
            "summary": summary,
            "summary_is_exact_source": False,
            "kind": kind,
            "provenance": provenance,
            "source_refs": list(source_refs or []),
        }
        state["artifacts"] = [item for item in state["artifacts"] if item["ref"] != ref]
        state["artifacts"].append(artifact)
        self.save(state)
        return artifact

    def preserve_tool_output(
        self,
        *,
        ref: str,
        output: str,
        summary: str,
        preview_tokens: int,
    ) -> dict[str, Any]:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", ref).strip("_") or "artifact"
        path = self.artifact_dir / f"{safe}.txt"
        path.write_text(output, encoding="utf-8", newline="\n")
        artifact = self.register_artifact(
            ref=ref,
            path=path,
            summary=summary,
            kind="tool_output",
            provenance="complete_local_artifact",
        )
        preview, event = compact_text(output, max_tokens=preview_tokens, estimator=self.estimator)
        if event:
            event.update({"artifact_ref": ref, "artifact_sha256": artifact["sha256"]})
            state = self.load()
            state["measurements"]["truncations"].append(event)
            self.save(state)
        return {"artifact": artifact, "preview": preview, "truncation": event}

    def load_artifact(self, ref: str) -> str:
        state = self.load()
        artifact = next((item for item in state["artifacts"] if item["ref"] == ref), None)
        if artifact is None:
            raise KeyError(ref)
        path = self._resolve_artifact_path(str(artifact["path"]))
        if _sha256_file(path) != artifact["sha256"]:
            raise RuntimeError(f"artifact hash mismatch: {ref}")
        return path.read_text(encoding="utf-8")

    def context_delta(self, known_hashes: dict[str, str]) -> dict[str, Any]:
        state = self.load()
        changed = [
            item for item in state["artifacts"] if known_hashes.get(item["ref"]) != item["sha256"]
        ]
        unchanged = [
            item["ref"] for item in state["artifacts"] if known_hashes.get(item["ref"]) == item["sha256"]
        ]
        return {"changed": changed, "unchanged_refs": unchanged}

    def build_resume_context(
        self,
        *,
        max_tokens: int,
        known_hashes: dict[str, str] | None = None,
        expand_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        known_hashes = known_hashes or {}
        expand = set(expand_refs or [])
        essential_evidence = [
            {
                "claim": item.get("claim", ""),
                "kind": item.get("kind", ""),
                "stance": item.get("stance", ""),
                "source_refs": item.get("source_refs", []),
            }
            for item in state["evidence"]
            if item.get("stance") in {"contradicts", "failure", "correction"}
            or item.get("kind") in {"failure", "author_correction"}
        ]
        compact_state = {
            "representation": "versioned_summary_with_source_links_not_exact_source_recovery",
            "objective": state["objective"],
            "current_task": state["current_task"],
            "active_hypothesis": state["active_hypothesis"],
            "essential_evidence": essential_evidence,
            "author_definitions": [
                {"claim": item.get("claim", ""), "source_refs": item.get("source_refs", [])}
                for item in state["author_definitions"]
            ],
            "corrections": [
                {"claim": item.get("claim", ""), "source_refs": item.get("source_refs", [])}
                for item in state["corrections"]
            ],
            "decisions": [
                {"decision": item.get("decision", ""), "source_refs": item.get("source_refs", [])}
                for item in state["decisions"][-8:]
            ],
            "unresolved_questions": state["unresolved_questions"],
            "versions": state["versions"],
            "actions": [
                {
                    "action_id": action["action_id"],
                    "status": action["status"],
                }
                for action in state["actions"][-8:]
            ],
            "next_executable_step": state["next_executable_step"],
            "artifacts": [],
        }
        included_refs: list[str] = []
        omitted_refs: list[dict[str, str]] = []
        truncations: list[dict[str, Any]] = []
        for artifact in state["artifacts"]:
            if known_hashes.get(artifact["ref"]) == artifact["sha256"] and artifact["ref"] not in expand:
                omitted_refs.append({"ref": artifact["ref"], "reason": "unchanged_hash"})
                continue
            representation = {
                "ref": artifact["ref"],
                "sha256": artifact["sha256"],
                "kind": artifact["kind"],
                "provenance": artifact["provenance"],
                "summary": artifact["summary"],
                "summary_is_exact_source": False,
                "full_source_path": artifact["path"],
            }
            if artifact["ref"] in expand:
                full = self.load_artifact(artifact["ref"])
                representation["expanded_full_content"] = full
            trial = deepcopy(compact_state)
            trial["artifacts"].append(representation)
            if self.estimator.estimate(
                json.dumps(trial, indent=2, ensure_ascii=False, sort_keys=True)
            ) <= max_tokens:
                compact_state = trial
                included_refs.append(artifact["ref"])
            else:
                if "expanded_full_content" in representation:
                    preview, event = compact_text(
                        representation.pop("expanded_full_content"),
                        max_tokens=max(32, max_tokens // 5),
                        estimator=self.estimator,
                    )
                    representation["expanded_preview"] = preview
                    if event:
                        event["artifact_ref"] = artifact["ref"]
                        truncations.append(event)
                    trial = deepcopy(compact_state)
                    trial["artifacts"].append(representation)
                    if self.estimator.estimate(
                        json.dumps(trial, indent=2, ensure_ascii=False, sort_keys=True)
                    ) <= max_tokens:
                        compact_state = trial
                        included_refs.append(artifact["ref"])
                        continue
                omitted_refs.append({"ref": artifact["ref"], "reason": "resume_context_budget"})
        rendered = json.dumps(compact_state, indent=2, ensure_ascii=False, sort_keys=True)
        estimated = self.estimator.estimate(rendered)
        if estimated > max_tokens:
            raise RuntimeError(
                "essential research state exceeds resume budget; increase max_tokens rather than silently truncating it"
            )
        return {
            "context": rendered,
            "estimated_tokens": estimated,
            "max_tokens": max_tokens,
            "estimator": self.estimator.metadata(),
            "included_artifact_refs": included_refs,
            "omitted_artifacts": omitted_refs,
            "truncation_events": truncations,
        }

    def _resolve_artifact_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (self.project_root / path).resolve()

    def _state_fingerprint(self, state: dict[str, Any]) -> str:
        value = deepcopy(state)
        value.pop("updated_at", None)
        measurements = value.get("measurements", {})
        measurements.pop("checkpoint_events", None)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return _sha256_bytes(encoded)

    def _read_validated(self, path: Path) -> dict[str, Any]:
        value = self._read_json(path)
        self._validate_state(value)
        return value

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError(f"expected JSON object: {path}")
        return value

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)

    @staticmethod
    def _validate_state(state: dict[str, Any]) -> None:
        if state.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError("unsupported research-state schema")
        required = {
            "objective",
            "current_task",
            "active_hypothesis",
            "evidence",
            "author_definitions",
            "corrections",
            "decisions",
            "unresolved_questions",
            "versions",
            "actions",
            "artifacts",
            "next_executable_step",
            "measurements",
            "updated_at",
        }
        missing = sorted(required - set(state))
        if missing:
            raise RuntimeError(f"research state missing fields: {missing}")
        action_ids: set[str] = set()
        for action in state["actions"]:
            if action.get("status") not in ACTION_STATUSES:
                raise RuntimeError(f"invalid action status: {action}")
            if action.get("action_id") in action_ids:
                raise RuntimeError(f"duplicate action id: {action.get('action_id')}")
            action_ids.add(action.get("action_id"))
        refs = [item.get("ref") for item in state["artifacts"]]
        if len(refs) != len(set(refs)):
            raise RuntimeError("duplicate artifact refs")
