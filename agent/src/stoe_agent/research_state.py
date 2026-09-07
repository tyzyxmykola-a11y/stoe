from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .continuity import (
    LINEAGE_SCHEMA_VERSION,
    ContinuityDivergenceError,
    Lineage,
    advance_lineage,
    compare_lineage,
)
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
        branch_id: str = "unscoped",
    ) -> None:
        self.runtime_dir = runtime_dir.resolve()
        self.checkpoint_dir = checkpoint_dir.resolve()
        self.bootstrap_path = bootstrap_path.resolve() if bootstrap_path else None
        self.project_root = (project_root or checkpoint_dir.parent).resolve()
        self.estimator = estimator or TokenEstimator()
        self.branch_id = branch_id
        self.state_path = self.runtime_dir / "research_state.json"
        self.runtime_lineage_path = self.runtime_dir / "research_state.lineage.json"
        self.artifact_dir = self.runtime_dir / "research_artifacts"
        self.latest_path = self.checkpoint_dir / "LATEST.json"
        self.lineage_manifest_path = self.checkpoint_dir / "LINEAGE.json"
        self.bootstrap_lineage_path = (
            self.bootstrap_path.with_name(f"{self.bootstrap_path.stem}.lineage.json")
            if self.bootstrap_path
            else None
        )
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        history = self._load_checkpoint_history()
        candidates: list[tuple[str, dict[str, Any], Lineage]] = []
        if self.state_path.exists():
            state = self._read_validated(self.state_path)
            candidates.append(
                ("runtime", state, self._lineage_for_state(state, self.runtime_lineage_path, history))
            )
        if self.latest_path.exists():
            state, lineage = self._load_latest_checkpoint(history)
            candidates.append(("latest_checkpoint", state, lineage))
        if self.bootstrap_path and self.bootstrap_path.exists():
            state = self._read_validated(self.bootstrap_path)
            candidates.append(
                (
                    "bootstrap",
                    state,
                    self._lineage_for_state(state, self.bootstrap_lineage_path, history),
                )
            )
        if not candidates:
            state = self.empty_state()
            fingerprint = self._state_fingerprint(state)
            lineage = Lineage(
                kind="research_state",
                stream_id=f"research-state:{fingerprint[:16]}",
                branch_id=self.branch_id,
                identity=fingerprint,
                parent_identity=None,
                ancestor_identities=(),
            )
            self._write_runtime(state, lineage)
            return state

        selected_source, selected_state, selected_lineage = candidates[0]
        source_priority = {"runtime": 0, "bootstrap": 1, "latest_checkpoint": 2}
        for source, state, lineage in candidates[1:]:
            try:
                relation = compare_lineage(lineage, selected_lineage)
            except ContinuityDivergenceError as exc:
                raise ContinuityDivergenceError(
                    f"cannot reconcile {source} with {selected_source}: {exc}"
                ) from exc
            if relation == "ahead" or (
                relation == "equal" and source_priority[source] > source_priority[selected_source]
            ):
                selected_source, selected_state, selected_lineage = source, state, lineage

        runtime_fingerprint = (
            self._state_fingerprint(self._read_validated(self.state_path))
            if self.state_path.exists()
            else None
        )
        if selected_source != "runtime" or runtime_fingerprint != selected_lineage.identity:
            self._write_runtime(selected_state, selected_lineage)
        elif not self.runtime_lineage_path.exists():
            self._atomic_json(
                self.runtime_lineage_path,
                selected_lineage.to_json(identity_field="state_fingerprint"),
            )
        return selected_state

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
        fingerprint = self._state_fingerprint(value)
        if self.state_path.exists():
            current = self._read_validated(self.state_path)
            history = self._load_checkpoint_history()
            lineage = self._lineage_for_state(current, self.runtime_lineage_path, history)
            lineage = advance_lineage(lineage, fingerprint)
        else:
            history = self._load_checkpoint_history()
            lineage = self._lineage_from_history(fingerprint, history)
            if lineage is None:
                lineage = Lineage(
                    kind="research_state",
                    stream_id=f"research-state:{fingerprint[:16]}",
                    branch_id=self.branch_id,
                    identity=fingerprint,
                    parent_identity=None,
                    ancestor_identities=(),
                )
        self._write_runtime(value, lineage)

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
            "lineage": self._runtime_lineage().to_json(identity_field="state_fingerprint"),
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
        lineage = self._runtime_lineage()
        self._update_lineage_manifest(path=path, envelope=envelope, lineage=lineage)
        if self.bootstrap_path is not None:
            self._atomic_json(self.bootstrap_path, state)
            if self.bootstrap_lineage_path is not None:
                self._atomic_json(
                    self.bootstrap_lineage_path,
                    lineage.to_json(identity_field="state_fingerprint"),
                )
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
        failure_evidence = [
            {
                "claim": item.get("claim", ""),
                "kind": item.get("kind", ""),
                "stance": item.get("stance", ""),
                "source_refs": item.get("source_refs", []),
            }
            for item in state["evidence"]
            if item.get("stance") in {"contradicts", "failure"}
            or item.get("kind") == "failure"
        ]
        essential_evidence = (
            failure_evidence
            if len(failure_evidence) <= 2
            else [failure_evidence[0], failure_evidence[-1]]
        )
        target_tokens = min(max_tokens, max(256, int(max_tokens * 0.80)))
        completed_action_ids = [
            action["action_id"] for action in state["actions"] if action["status"] == "completed"
        ]
        compact_state = {
            "representation": "versioned_summary_with_source_links_not_exact_source_recovery",
            "objective": state["objective"],
            "current_task": state["current_task"],
            "active_hypothesis": {"see": "unresolved_questions[-1]"}
            if state["active_hypothesis"]
            else None,
            "essential_evidence": essential_evidence,
            "author_definitions": state["author_definitions"][-1:],
            "corrections": [
                {"claim": item.get("claim", ""), "source_refs": item.get("source_refs", [])}
                for item in state["corrections"][-2:]
            ],
            "decisions": [
                {"decision": item.get("decision", ""), "source_refs": item.get("source_refs", [])}
                for item in state["decisions"][-2:]
            ],
            "unresolved_questions": state["unresolved_questions"][-1:],
            "versions": state["versions"],
            "completed_action_ids": completed_action_ids,
            "open_actions": [
                {"action_id": action["action_id"], "status": action["status"]}
                for action in state["actions"]
                if action["status"] != "completed"
            ],
            "folded_history": {
                "author_definition_count": len(state["author_definitions"]),
                "decision_count": len(state["decisions"]),
                "evidence_count": len(state["evidence"]),
                "correction_count": len(state["corrections"]),
                "complete_details": "research_state.json and hash-addressed artifact refs",
            },
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
            ) <= target_tokens:
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
                    ) <= target_tokens:
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
            "target_tokens": target_tokens,
            "reserve_tokens": max_tokens - estimated,
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

    def _load_checkpoint_history(self) -> list[dict[str, Any]]:
        if self.lineage_manifest_path.exists():
            manifest = self._read_json(self.lineage_manifest_path)
            if manifest.get("schema_version") != LINEAGE_SCHEMA_VERSION:
                raise RuntimeError("unsupported research lineage manifest schema")
            entries = manifest.get("checkpoints")
            if not isinstance(entries, list):
                raise RuntimeError("research lineage manifest has no checkpoint list")
            prior_fingerprints: list[str] = []
            stream_id: str | None = None
            branch_id: str | None = None
            for entry in entries:
                path = self.checkpoint_dir / str(entry["file"])
                if not path.is_file() or _sha256_file(path) != entry["sha256"]:
                    raise RuntimeError(f"research lineage checkpoint hash mismatch: {path.name}")
                envelope = self._read_json(path)
                state = envelope.get("state")
                if not isinstance(state, dict):
                    raise RuntimeError(f"research checkpoint does not contain state: {path.name}")
                self._validate_state(state)
                fingerprint = self._state_fingerprint(state)
                if fingerprint != entry.get("state_fingerprint"):
                    raise RuntimeError(f"research lineage state fingerprint mismatch: {path.name}")
                declared_ancestors = entry.get("ancestor_state_fingerprints")
                if not isinstance(declared_ancestors, list):
                    raise RuntimeError(f"research lineage ancestry mismatch: {path.name}")
                expected_ancestors = list(dict.fromkeys(prior_fingerprints))
                cursor = 0
                for ancestor in declared_ancestors:
                    if cursor < len(expected_ancestors) and ancestor == expected_ancestors[cursor]:
                        cursor += 1
                if cursor != len(expected_ancestors) or fingerprint in declared_ancestors:
                    raise RuntimeError(f"research lineage ancestry mismatch: {path.name}")
                declared_parent = entry.get("parent_state_fingerprint")
                if declared_parent is not None and declared_parent not in declared_ancestors:
                    raise RuntimeError(f"research lineage parent mismatch: {path.name}")
                stream_id = stream_id or str(entry.get("stream_id"))
                branch_id = branch_id or str(entry.get("branch_id"))
                if entry.get("stream_id") != stream_id or entry.get("branch_id") != branch_id:
                    raise RuntimeError(f"research lineage stream changed inside manifest: {path.name}")
                if not prior_fingerprints or prior_fingerprints[-1] != fingerprint:
                    prior_fingerprints.append(fingerprint)
            return entries

        entries: list[dict[str, Any]] = []
        ancestors: list[str] = []
        stream_id = ""
        for path in sorted(self.checkpoint_dir.glob("*.json")):
            if path.name in {"LATEST.json", "LINEAGE.json"}:
                continue
            envelope = self._read_json(path)
            state = envelope.get("state")
            if not isinstance(state, dict):
                raise RuntimeError(f"research checkpoint does not contain state: {path.name}")
            self._validate_state(state)
            fingerprint = self._state_fingerprint(state)
            if not stream_id:
                stream_id = f"research-state:{fingerprint[:16]}"
            entries.append(
                {
                    "checkpoint_id": str(envelope["checkpoint_id"]),
                    "file": path.name,
                    "sha256": _sha256_file(path),
                    "state_fingerprint": fingerprint,
                    "parent_state_fingerprint": ancestors[-1] if ancestors else None,
                    "ancestor_state_fingerprints": list(dict.fromkeys(ancestors)),
                    "stream_id": stream_id,
                    "branch_id": self.branch_id,
                }
            )
            if not ancestors or ancestors[-1] != fingerprint:
                ancestors.append(fingerprint)
        return entries

    def _lineage_from_history(
        self, fingerprint: str, history: list[dict[str, Any]]
    ) -> Lineage | None:
        matches = [entry for entry in history if entry["state_fingerprint"] == fingerprint]
        if not matches:
            return None
        entry = matches[-1]
        return Lineage(
            kind="research_state",
            stream_id=str(entry["stream_id"]),
            branch_id=str(entry["branch_id"]),
            identity=fingerprint,
            parent_identity=entry.get("parent_state_fingerprint"),
            ancestor_identities=tuple(entry.get("ancestor_state_fingerprints", [])),
        )

    def _lineage_for_state(
        self,
        state: dict[str, Any],
        lineage_path: Path | None,
        history: list[dict[str, Any]],
    ) -> Lineage:
        fingerprint = self._state_fingerprint(state)
        if lineage_path and lineage_path.exists():
            value = self._read_json(lineage_path)
            if value.get("state_fingerprint") != fingerprint:
                raise ContinuityDivergenceError(
                    f"lineage fingerprint does not match {lineage_path.name} state"
                )
            return Lineage(
                kind=str(value.get("kind")),
                stream_id=str(value.get("stream_id")),
                branch_id=str(value.get("branch_id")),
                identity=fingerprint,
                parent_identity=value.get("parent_state_fingerprint"),
                ancestor_identities=tuple(value.get("ancestor_state_fingerprints", [])),
            )
        inferred = self._lineage_from_history(fingerprint, history)
        if inferred is None:
            raise ContinuityDivergenceError(
                f"unanchored research state {fingerprint[:12]} has no ancestry proof"
            )
        return inferred

    def _load_latest_checkpoint(
        self, history: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], Lineage]:
        pointer = self._read_json(self.latest_path)
        checkpoint = self.checkpoint_dir / str(pointer["file"])
        if _sha256_file(checkpoint) != pointer["sha256"]:
            raise RuntimeError("research checkpoint hash mismatch")
        envelope = self._read_json(checkpoint)
        state = envelope.get("state")
        if not isinstance(state, dict):
            raise RuntimeError("research checkpoint does not contain state")
        self._validate_state(state)
        fingerprint = self._state_fingerprint(state)
        if pointer.get("state_fingerprint") != fingerprint:
            raise RuntimeError("latest checkpoint state fingerprint mismatch")
        lineage = self._lineage_from_history(fingerprint, history)
        if lineage is None:
            raise ContinuityDivergenceError("latest checkpoint is absent from verified lineage")
        return state, lineage

    def _runtime_lineage(self) -> Lineage:
        if not self.state_path.exists():
            raise RuntimeError("runtime research state is missing")
        return self._lineage_for_state(
            self._read_validated(self.state_path),
            self.runtime_lineage_path,
            self._load_checkpoint_history(),
        )

    def _write_runtime(self, state: dict[str, Any], lineage: Lineage) -> None:
        if self._state_fingerprint(state) != lineage.identity:
            raise RuntimeError("refusing to bind research state to the wrong lineage fingerprint")
        self._atomic_json(self.state_path, state)
        self._atomic_json(
            self.runtime_lineage_path,
            lineage.to_json(identity_field="state_fingerprint"),
        )

    def _update_lineage_manifest(
        self, *, path: Path, envelope: dict[str, Any], lineage: Lineage
    ) -> None:
        entries = self._load_checkpoint_history()
        entry = {
            "checkpoint_id": str(envelope["checkpoint_id"]),
            "file": path.name,
            "sha256": _sha256_file(path),
            "state_fingerprint": lineage.identity,
            "parent_state_fingerprint": lineage.parent_identity,
            "ancestor_state_fingerprints": list(lineage.ancestor_identities),
            "stream_id": lineage.stream_id,
            "branch_id": lineage.branch_id,
        }
        entries = [item for item in entries if item["file"] != path.name]
        entries.append(entry)
        self._atomic_json(
            self.lineage_manifest_path,
            {
                "schema_version": LINEAGE_SCHEMA_VERSION,
                "kind": "research_state_lineage",
                "checkpoints": entries,
            },
        )

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
