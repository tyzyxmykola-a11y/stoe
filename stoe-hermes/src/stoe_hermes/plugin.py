from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .promotion import render_active_context


PLUGIN_NAME = "stoe-hermes"
MCP_SERVER = "stoe_memory"
SESSION_CONTEXT_CHARS = 4_000


class SToEHermesAdapter:
    """Use Hermes' capability-gated MCP facade; never open the SToE database."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._states: dict[str, str] = {}
        self._retrieved: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def _session_id(kwargs: dict[str, Any]) -> str:
        return str(kwargs.get("session_id") or kwargs.get("session_key") or "hermes-unknown")[:160]

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        envelope = self.ctx.call_mcp(MCP_SERVER, tool, arguments, timeout=30)
        if not isinstance(envelope, dict) or not envelope.get("ok"):
            error = envelope.get("error", "invalid MCP envelope") if isinstance(envelope, dict) else "invalid MCP envelope"
            raise RuntimeError(f"SToE Memory {tool} failed: {error}")
        value = envelope.get("structuredContent")
        if value is None:
            value = envelope.get("result")
        if not isinstance(value, dict):
            raise RuntimeError(f"SToE Memory {tool} returned no structured object")
        return value

    def on_session_start(self, **kwargs: Any) -> None:
        session_id = self._session_id(kwargs)
        recent = self._call("stoe_list_recent", {"limit": 8})
        recent_refs = [str(item["ref"]) for item in recent.get("items", []) if item.get("ref")]
        status = self._call("stoe_field_status", {})
        latest_state = status.get("last_observer_state") or {}
        latest_ref = latest_state.get("ref") if isinstance(latest_state, dict) else None
        if latest_ref and str(latest_ref) not in recent_refs:
            recent_refs.append(str(latest_ref))
        state = self._call(
            "stoe_set_observer_state",
            {
                "goal": "Continue the current SToE Agent development objective through Hermes.",
                "question": "Which bounded connected prior state is relevant to this Hermes session?",
                "active_constraints": ["Preserve provenance, failures, decisions, and protected succession boundaries."],
                "changed_constraints": [],
                "evidence": [],
                "open_questions": [],
                "invalidates_refs": [],
                "recent_refs": recent_refs,
                "session_id": f"hermes:{session_id}",
            },
        )
        observer_ref = str(state["observer_state_ref"])
        retrieval = self._call(
            "stoe_navigate",
            {
                "observer_state_ref": observer_ref,
                "limit": 8,
                "max_depth": 4,
                "include_failures": True,
                "include_seed": False,
                "per_item_chars": 500,
                "total_chars": SESSION_CONTEXT_CHARS,
            },
        )
        self._states[session_id] = observer_ref
        self._retrieved[session_id] = list(retrieval.get("selected_items") or [])

    def pre_llm_call(self, **kwargs: Any) -> dict[str, str] | None:
        session_id = self._session_id(kwargs)
        if session_id not in self._states:
            self.on_session_start(**kwargs)
        content = render_active_context(self._retrieved.get(session_id, []), SESSION_CONTEXT_CHARS)
        return {"context": content} if content else None

    def retrieve(self, params: dict[str, Any], **kwargs: Any) -> str:
        merged = {**kwargs, **params}
        session_id = self._session_id(merged)
        if session_id not in self._states:
            self.on_session_start(**merged)
        limit = min(max(int(params.get("limit", 6)), 1), 12)
        retrieval = self._call(
            "stoe_navigate",
            {
                "observer_state_ref": self._states[session_id],
                "limit": limit,
                "max_depth": 4,
                "include_failures": True,
                "include_seed": False,
                "per_item_chars": 500,
                "total_chars": SESSION_CONTEXT_CHARS,
            },
        )
        items = list(retrieval.get("selected_items") or [])
        self._retrieved[session_id] = items
        return json.dumps(
            {
                "observer_state_ref": self._states[session_id],
                "retrieval_run_id": retrieval.get("run_id"),
                "context": render_active_context(items, SESSION_CONTEXT_CHARS),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def conserve(self, params: dict[str, Any], **kwargs: Any) -> str:
        merged = {**kwargs, **params}
        session_id = self._session_id(merged)
        outcome = str(params.get("outcome") or "observed")[:80]
        failure_condition = str(params.get("failure_condition") or "")[:1000]
        origin = "failure_history" if outcome in {"failed", "rejected"} else "runtime_reasoning"
        created = self._call(
            "stoe_add_ip",
            {
                "content": str(params.get("content") or "")[:4000],
                "kind": str(params.get("kind") or "HermesOutcomeIP")[:80],
                "origin": origin,
                "outcome": outcome,
                "failure_condition": failure_condition,
                "session_id": f"hermes:{session_id}",
                "visible": True,
                "metadata": {"hermes_session_id": session_id, "adapter": PLUGIN_NAME},
            },
        )
        observer_ref = self._states.get(session_id)
        if observer_ref:
            self._call(
                "stoe_add_relation",
                {
                    "source_ref": observer_ref,
                    "target_ref": created["ref"],
                    "relation": "contains",
                    "weight": 1.0,
                    "note": "Hermes outcome conserved by the SToE adapter",
                },
            )
        return json.dumps({"ref": created["ref"], "outcome": outcome}, sort_keys=True)

    def on_session_end(self, **kwargs: Any) -> None:
        completed = bool(kwargs.get("completed"))
        interrupted = bool(kwargs.get("interrupted"))
        outcome = "failed" if interrupted or not completed else "observed"
        self.conserve(
            {
                "session_id": self._session_id(kwargs),
                "kind": "HermesSessionEndIP",
                "outcome": outcome,
                "failure_condition": "Hermes session interrupted or incomplete" if outcome == "failed" else "",
                "content": f"Hermes session ended: completed={completed}, interrupted={interrupted}, model={kwargs.get('model', '')}, platform={kwargs.get('platform', '')}",
            }
        )


def register(ctx: Any) -> None:
    adapter = SToEHermesAdapter(ctx)
    skill_root = Path(os.environ.get("STOE_REASONING_SKILL_DIR", ""))
    if not skill_root.is_absolute() or not (skill_root / "SKILL.md").is_file():
        raise RuntimeError("STOE_REASONING_SKILL_DIR must name the canonical installed skill")
    ctx.register_skill(
        "stoe-reasoning",
        skill_root,
        description="Observer-aware SToE reasoning with conserved failures and typed succession.",
    )
    ctx.register_hook("on_session_start", adapter.on_session_start)
    ctx.register_hook("pre_llm_call", adapter.pre_llm_call)
    ctx.register_hook("on_session_end", adapter.on_session_end)
    ctx.register_tool(
        name="stoe_retrieve",
        toolset="stoe_memory",
        schema={
            "name": "stoe_retrieve",
            "description": "Retrieve bounded observer-aware context from the canonical SToE field.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 12}},
                "additionalProperties": False,
            },
        },
        handler=adapter.retrieve,
    )
    ctx.register_tool(
        name="stoe_conserve",
        toolset="stoe_memory",
        schema={
            "name": "stoe_conserve",
            "description": "Conserve an important Hermes outcome or failure in SToE Memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "maxLength": 4000},
                    "kind": {"type": "string", "maxLength": 80},
                    "outcome": {"type": "string", "enum": ["observed", "supported", "failed", "rejected"]},
                    "failure_condition": {"type": "string", "maxLength": 1000},
                },
                "required": ["content", "kind", "outcome"],
                "additionalProperties": False,
            },
        },
        handler=adapter.conserve,
    )
