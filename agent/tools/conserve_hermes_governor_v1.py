from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_development import _ensure_ip, _ensure_relation  # noqa: E402
from stoe_agent.local_development_pipeline import SESSION, field_store  # noqa: E402


REPORT = ROOT / "stoe-hermes" / "HERMES_DEVELOPMENT_GOVERNOR_V1_REPORT.json"
COMMIT = "a4c3878b7cc4c6cf89582fcc1cbba42983035144"


def main() -> int:
    store = field_store()
    raw = REPORT.read_bytes()
    report_sha = hashlib.sha256(raw).hexdigest()
    nodes = {
        "IP_hermesgovernorobjective01": ("Hermes B governs one real bounded documentation task through exact TaskScope, local workers, deterministic gates, trusted apply, commit, push, and conservation.", "DevelopmentObjectiveIP", "supported", {}),
        "IP_hermesgovernorevaluation01": ("Exact candidate d0743b25 passed TaskScope/artifact validation, independent local review, 46 Hermes tests, 136 Agent tests, frozen CLI hash, and git diff check.", "evaluation", "passed", {"candidate_sha256": "d0743b25d80dc4fbcbce5f751b3f883e3b50c47e83b24e5c2667bd8b1385844b"}),
        "IP_hermesgovernorcommit01": (f"Commit {COMMIT} implements Governor v1 and the exact governed README candidate.", "CommitIP", "supported", {"commit": COMMIT}),
        "IP_hermesgovernorpush01": (f"Normal feature-branch push published {COMMIT}; no merge, release, or force push occurred.", "PushIP", "supported", {"branch": "feature/hermes-promotion-policy-v1", "commit": COMMIT}),
        "IP_hermesgovernorqualified01": (f"SToE Hermes Development Governor v1 passed one real vertical task at {COMMIT}.", "DecisionIP", "supported", {"qualified": True, "commit": COMMIT}),
        "IP_hermesgovernorreport01": (f"Artifact stoe-hermes/HERMES_DEVELOPMENT_GOVERNOR_V1_REPORT.json sha256={report_sha}", "ArtifactIP", "supported", {"path": "stoe-hermes/HERMES_DEVELOPMENT_GOVERNOR_V1_REPORT.json", "sha256": report_sha, "size_bytes": len(raw)}),
        "IP_hermesgovernornext02": ("Hermes B selects and initiates the next bounded unresolved repository objective from the SToE field under TaskScope, without Codex initiating each stage.", "NextActionIP", "active", {}),
    }
    for ref, (content, kind, outcome, metadata) in nodes.items():
        _ensure_ip(store, ref=ref, identity={"content": content, "kind": kind, "metadata": metadata}, create={"content": content, "kind": kind, "origin": "runtime_reasoning", "outcome": outcome, "failure_condition": "", "session_id": SESSION, "metadata": metadata, "visible": True})
    links = [
        ("IP_hermesgovernorobjective01", "IP_hermesgovernornext01", "follows", "Governor milestone follows the conserved Local Development v2 graduation objective."),
        ("IP_hermes_taskscope_4169d3aaf028", "IP_hermesgovernorobjective01", "scopes", "Exact validated TaskScope bounds the governed task."),
        ("LDR_1b9ee02d68e118e4", "IP_hermes_taskscope_4169d3aaf028", "depends_on", "Local planner operated under exact TaskScope."),
        ("IP_hermes_governor_coder_failure02", "IP_hermes_governor_coder_failure01", "follows", "First correction exposed the heading-body validation defect."),
        ("LDR_28129d29000597a7", "IP_hermes_governor_coder_failure02", "corrects", "Final bounded coder successor satisfied the artifact contract."),
        ("LDR_3255cee5bbb1ac74", "LDC_bcfd697928380e80", "evaluates", "Independent reviewer evaluated the exact inert patch artifact."),
        ("IP_hermesgovernorevaluation01", "LDC_bcfd697928380e80", "evaluates", "Trusted deterministic suites evaluated the exact candidate."),
        ("IP_hermesgovernorcommit01", "IP_hermesgovernorevaluation01", "depends_on", "Trusted apply and commit required all green gates."),
        ("IP_hermesgovernorpush01", "IP_hermesgovernorcommit01", "follows", "Push followed the verified implementation commit."),
        ("IP_hermesgovernorqualified01", "IP_hermesgovernorpush01", "supported_by", "Qualification requires the completed feature-branch push."),
        ("IP_hermesgovernorqualified01", "IP_hermesgovernorevaluation01", "supported_by", "Qualification requires green deterministic evidence."),
        ("IP_hermesgovernorreport01", "IP_hermesgovernorqualified01", "summarizes", "Artifact-backed milestone report."),
        ("IP_hermesgovernornext02", "IP_hermesgovernorqualified01", "follows", "Next bounded objective begins after Governor v1 qualification."),
    ]
    for source, target, relation, note in links:
        _ensure_relation(store, source_ref=source, target_ref=target, relation=relation, note=note)
    goal = "Hermes B selects and initiates the next bounded repository objective under the qualified Governor v1 TaskScope protocol."
    existing = next((item for item in store.list_recent(session_id=SESSION, limit=40)["items"] if item["kind"] == "current_state" and item["metadata"].get("goal") == goal), None)
    state = {"observer_state_ref": existing["ref"]} if existing else store.set_observer_state(
        goal=goal,
        question="Which unresolved bounded repository objective should Hermes B govern next without Codex stage initiation?",
        active_constraints=["Exact TaskScope before workers", "Models have no trusted apply/Git/SToE-write authority", "Sequential local specialists under interactive resource policy"],
        changed_constraints=["Hermes Governor v1 completed one real plan-code-review-test-apply-commit-push cycle."],
        evidence=["46 Hermes and 136 Agent tests passed", f"Governed implementation pushed at {COMMIT}"],
        open_questions=["Next smallest unresolved objective retrievable from the SToE field"],
        recent_refs=["IP_hermesgovernorqualified01", "IP_hermesgovernorreport01", "IP_hermesgovernornext02"],
        current_reasoning_ref="IP_hermesgovernornext02",
        session_id=SESSION,
    )
    print(json.dumps({"report_sha256": report_sha, "refs": list(nodes), "state": state["observer_state_ref"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
