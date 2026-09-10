from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_development import _ensure_ip, _ensure_relation  # noqa: E402
from stoe_agent.local_development_pipeline import SESSION, field_store  # noqa: E402


CORRECTION_REF = "IP_ldv2allowlistcorrection01"


def main() -> int:
    store = field_store()
    content = "Narrow pure-reporting correction: permit built-in hash only inside the fixed reporting function; retain exact path/function grammar and forbid imports, I/O, process, network, Git, reflection, dynamic execution, and nested scope."
    metadata = {"added_call": "hash", "scope": "render_retrieved_context", "authority_expansion": False, "focused_tests": 18}
    _ensure_ip(
        store,
        ref=CORRECTION_REF,
        identity={"content": content, "kind": "CorrectionIP", "metadata": metadata},
        create={"content": content, "kind": "CorrectionIP", "origin": "state_change", "outcome": "supported", "failure_condition": "", "session_id": SESSION, "metadata": metadata, "visible": True},
    )
    _ensure_relation(store, source_ref=CORRECTION_REF, target_ref="LDR_4188e0c8e27a784d", relation="corrects", note="ChatGPT-authorized narrow correction resolves the exact capability-allowlist mismatch.")
    existing = next((item for item in store.list_recent(session_id=SESSION, limit=30)["items"] if item["kind"] == "current_state" and item["metadata"].get("current_reasoning_ref") == CORRECTION_REF), None)
    state = {"observer_state_ref": existing["ref"]} if existing else store.set_observer_state(
        goal="Generate and qualify a new connection-conserving reporting successor under the corrected pure-reporting boundary.",
        question="Can a fresh local successor satisfy grammar, authority, reviewer, and behavior tests?",
        active_constraints=["One fixed reporting function", "No imports or external authority", "Closed actions never retry", "Apply only after reviewer and deterministic tests"],
        changed_constraints=["Authority-free hash call is permitted only within the fixed reporting function."],
        evidence=["Architecture correction authorized", "18 focused boundary tests pass"],
        open_questions=["Whether the new successor preserves every connection and exact count fields"],
        invalidates_refs=["IP_ldv2escalationnext01"],
        recent_refs=[CORRECTION_REF, "IP_ldv2focusedfailure01", "LDR_4188e0c8e27a784d"],
        current_reasoning_ref=CORRECTION_REF,
        session_id=SESSION,
    )
    print(json.dumps({"correction_ref": CORRECTION_REF, "observer_state_ref": state["observer_state_ref"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
