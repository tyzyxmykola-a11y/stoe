from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_development import _ensure_ip, _ensure_relation  # noqa: E402
from stoe_agent.local_development_pipeline import SESSION, field_store  # noqa: E402


REPORT = ROOT / "agent" / "LOCAL_DEVELOPMENT_V2_ALLOWLIST_SUCCESSION_REPORT.json"


def main() -> int:
    store = field_store()
    raw = REPORT.read_bytes()
    report_sha = hashlib.sha256(raw).hexdigest()
    nodes = {
        "IP_ldv2allowlistevaluation01": ("Focused evaluation rejected the grammar-valid successor: it was byte-identical to the parent and lacked payload deduplication, paths, and required counts.", "evaluation", "evaluation", "failed", "required reporting semantics absent", {"candidate_sha256": "cd31b0dd4ce7a2c8fdfec4553c02171b2510527fddf251fee901ea5c0279dce7"}),
        "IP_ldv2allowlistdecision01": ("Do not apply: the narrow boundary correction passed, but the bounded local successor chain did not produce a semantic source change.", "DecisionIP", "runtime_reasoning", "rejected", "candidate is unchanged and focused tests failed", {"applied": False}),
        "IP_ldv2allowlistreport01": (f"Artifact agent/LOCAL_DEVELOPMENT_V2_ALLOWLIST_SUCCESSION_REPORT.json sha256={report_sha}", "ArtifactIP", "runtime_reasoning", "supported", "", {"path": "agent/LOCAL_DEVELOPMENT_V2_ALLOWLIST_SUCCESSION_REPORT.json", "sha256": report_sha, "size_bytes": len(raw)}),
        "IP_ldv2codeemissionnext01": ("Improve bounded local code-emission reliability or authorize a stronger coding route; never retry the closed successor actions.", "NextActionIP", "runtime_reasoning", "active", "", {"recovery_exhausted": True}),
    }
    for ref, (content, kind, origin, outcome, failure, metadata) in nodes.items():
        _ensure_ip(store, ref=ref, identity={"content": content, "kind": kind, "metadata": metadata}, create={"content": content, "kind": kind, "origin": origin, "outcome": outcome, "failure_condition": failure, "session_id": SESSION, "metadata": metadata, "visible": True})
    links = [
        ("IP_ldv2allowlistevaluation01", "LDR_f0a869694def9c43", "evaluates", "Focused deterministic evaluation of exact successor candidate."),
        ("IP_ldv2allowlistevaluation01", "LDR_0888b156a9175cd5", "contradicts", "Exact diff and tests contradict the reviewer acceptance."),
        ("LDR_f5958cffd09deaa2", "IP_ldv2allowlistevaluation01", "diagnoses", "Local analyst diagnosed the semantic test failure."),
        ("IP_ldv2allowlistdecision01", "IP_ldv2allowlistcorrection01", "depends_on", "Decision retains the qualified boundary correction."),
        ("IP_ldv2allowlistdecision01", "IP_ldv2allowlistevaluation01", "depends_on", "No-apply decision depends on deterministic evaluation."),
        ("IP_ldv2allowlistreport01", "IP_ldv2allowlistdecision01", "summarizes", "Artifact-backed outcome report."),
        ("IP_ldv2codeemissionnext01", "IP_ldv2allowlistdecision01", "follows", "Exact unresolved action after bounded recovery."),
    ]
    for source, target, relation, note in links:
        _ensure_relation(store, source_ref=source, target_ref=target, relation=relation, note=note)
    goal = "Resolve bounded local code-emission reliability without retrying the closed allowlist-successor actions."
    existing = next((item for item in store.list_recent(session_id=SESSION, limit=30)["items"] if item["kind"] == "current_state" and item["metadata"].get("goal") == goal), None)
    state = {"observer_state_ref": existing["ref"]} if existing else store.set_observer_state(
        goal=goal,
        question="Which bounded routing or serialization correction can produce a real function change without weakening authority boundaries?",
        active_constraints=["Allowlist correction retained", "Active source unchanged", "Closed actions never retry", "Deterministic tests remain authoritative"],
        evidence=["Boundary adversarial tests pass", "Three successor artifacts failed or were unchanged", "Reviewer false acceptance recorded", "Test analyst diagnosed missing implementation"],
        open_questions=["Whether a stronger coding-qualified model can fit interactive resource reserves"],
        recent_refs=["IP_ldv2allowlistcorrection01", "IP_ldv2allowlistevaluation01", "IP_ldv2allowlistdecision01", "IP_ldv2codeemissionnext01"],
        current_reasoning_ref="IP_ldv2allowlistdecision01",
        session_id=SESSION,
    )
    print(json.dumps({"report_sha256": report_sha, "refs": list(nodes), "state": state["observer_state_ref"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
