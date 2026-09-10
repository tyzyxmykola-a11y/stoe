from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_development import _ensure_ip, _ensure_relation  # noqa: E402
from stoe_agent.local_development_pipeline import SESSION, field_store  # noqa: E402


REPORT = ROOT / "agent" / "LOCAL_DEVELOPMENT_V2_FUNCTION_CYCLE_REPORT.json"


def main() -> int:
    store = field_store()
    raw = REPORT.read_bytes()
    report_sha = hashlib.sha256(raw).hexdigest()
    report = json.loads(raw.decode("utf-8"))
    nodes = {
        "IP_ldv2functiongrammar01": {
            "content": "Trusted function-only candidate grammar qualified: exact path/function/parent hash, one FunctionDef, no imports or scope expansion.",
            "kind": "CorrectionIP", "origin": "runtime_reasoning", "outcome": "supported", "failure_condition": "",
            "metadata": {"format": "stoe.function_replacement"},
        },
        "IP_ldv2focusedfailure01": {
            "content": "Focused evaluation rejected candidate 053d1d12: duplicate connection refs and paths were lost and exact count fields were absent.",
            "kind": "evaluation", "origin": "evaluation", "outcome": "failed", "failure_condition": "connection conservation and count contract failed",
            "metadata": {"candidate_sha256": report["candidate"]["sha256"]},
        },
        "IP_ldv2recoverydecision01": {
            "content": "Do not apply candidate: local test diagnosis completed and bounded corrective generation ended in grammar then capability rejection.",
            "kind": "DecisionIP", "origin": "runtime_reasoning", "outcome": "rejected", "failure_condition": "bounded local recovery exhausted",
            "metadata": {"applied": False},
        },
        "IP_ldv2functionreport01": {
            "content": f"Artifact agent/LOCAL_DEVELOPMENT_V2_FUNCTION_CYCLE_REPORT.json sha256={report_sha}",
            "kind": "ArtifactIP", "origin": "runtime_reasoning", "outcome": "supported", "failure_condition": "",
            "metadata": {"path": "agent/LOCAL_DEVELOPMENT_V2_FUNCTION_CYCLE_REPORT.json", "sha256": report_sha, "size_bytes": len(raw)},
        },
        "IP_ldv2escalationnext01": {
            "content": "Escalate exact capability-allowlist rejection and failed connection preservation to ChatGPT architecture authority; do not retry closed actions.",
            "kind": "NextActionIP", "origin": "runtime_reasoning", "outcome": "active", "failure_condition": "",
            "metadata": {"recovery_exhausted": True},
        },
    }
    for ref, value in nodes.items():
        create = dict(value)
        create.update({"session_id": SESSION, "visible": True})
        _ensure_ip(store, ref=ref, identity={"content": value["content"], "kind": value["kind"], "metadata": value["metadata"]}, create=create)
    links = [
        ("IP_ldv2functiongrammar01", "IP_3198109ede9e4356", "corrects", "Function grammar corrects the earlier whole-file/line-patch boundary failure."),
        ("IP_ldv2focusedfailure01", "LDR_0cd0a46bf68e7a33", "evaluates", "Focused deterministic behavior evaluation of exact candidate result."),
        ("LDR_0159d1ed5fc4bc77", "IP_ldv2focusedfailure01", "diagnoses", "Local test analyst diagnosed preserved deterministic failures."),
        ("LDR_d8e92ecbcbfa8104", "LDR_0159d1ed5fc4bc77", "corrects", "First linked corrective generation used test diagnosis."),
        ("LDR_4188e0c8e27a784d", "LDR_d8e92ecbcbfa8104", "corrects", "Second linked corrective generation used exact grammar defect."),
        ("IP_ldv2recoverydecision01", "IP_ldv2focusedfailure01", "depends_on", "Decision depends on authoritative focused evaluation."),
        ("IP_ldv2recoverydecision01", "LDR_4188e0c8e27a784d", "depends_on", "Decision depends on final bounded capability rejection."),
        ("IP_ldv2functionreport01", "IP_ldv2recoverydecision01", "summarizes", "Artifact-backed compact checkpoint report."),
        ("IP_ldv2escalationnext01", "IP_ldv2recoverydecision01", "follows", "Exact next action follows bounded recovery decision."),
    ]
    for source, target, relation, note in links:
        _ensure_relation(store, source_ref=source, target_ref=target, relation=relation, note=note)
    goal = "Resolve Local Development v2 bounded recovery escalation without retrying closed actions."
    existing_state = next((item for item in store.list_recent(session_id=SESSION, limit=20)["items"] if item["kind"] == "current_state" and item["metadata"].get("goal") == goal), None)
    state = {"observer_state_ref": existing_state["ref"]} if existing_state else store.set_observer_state(
        goal=goal,
        question="Should the pure-reporting allowlist or generation contract change to obtain connection-conserving code without expanding authority?",
        active_constraints=["No candidate applied", "Closed actions cannot retry", "Trust boundary changes require ChatGPT", "Detailed artifacts remain local and hashed"],
        evidence=["Function grammar qualified", "Candidate failed focused behavior", "Local analyst diagnosed", "Two corrective successors failed"],
        open_questions=["Whether a narrow trusted grammar/capability correction is architectural or deterministic plumbing"],
        recent_refs=["IP_ldv2functionreport01", "IP_ldv2recoverydecision01", "IP_ldv2escalationnext01"],
        current_reasoning_ref="IP_ldv2recoverydecision01",
        session_id=SESSION,
    )
    print(json.dumps({"report_sha256": report_sha, "refs": list(nodes), "state": state["observer_state_ref"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
