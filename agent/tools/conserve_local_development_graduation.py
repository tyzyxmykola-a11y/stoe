from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from stoe_agent.local_development import _ensure_ip, _ensure_relation  # noqa: E402
from stoe_agent.local_development_pipeline import SESSION, field_store  # noqa: E402


REPORT = ROOT / "agent" / "LOCAL_DEVELOPMENT_V2_GRADUATION_REPORT.json"


def main() -> int:
    store = field_store()
    raw = REPORT.read_bytes()
    report_sha = hashlib.sha256(raw).hexdigest()
    nodes = {
        "IP_ldv2graduationobjective01": ("Complete one safe real Local Development v2 plan-code-review-test-apply-commit-push vertical slice for connection-conserving reporting.", "DevelopmentObjectiveIP", "runtime_reasoning", "supported", "", {}),
        "IP_ldv2graduationevaluation01": ("Accepted candidate f48f02d9 passed all 9 focused semantic checks, 32 focused Local Development tests, and 136 full Agent tests.", "evaluation", "evaluation", "passed", "", {"candidate_sha256": "f48f02d9c3e2d72a6dba2b95af76ee71c5d4e29effe620d6db2325e53c92c92b"}),
        "IP_ldv2graduationcommit02": ("Commit 7b647e170eb2240913572da1ffe33175705f305e applies the exact qualified reporting candidate and bounded IR gates.", "CommitIP", "runtime_reasoning", "supported", "", {"commit": "7b647e170eb2240913572da1ffe33175705f305e"}),
        "IP_ldv2graduationpush02": ("Feature branch push published commit 7b647e170eb2240913572da1ffe33175705f305e without merge, force push, or release.", "PushIP", "runtime_reasoning", "supported", "", {"branch": "feature/hermes-promotion-policy-v1"}),
        "IP_ldv2commitidentitycorrection01": ("Correct graduation commit identity is 7b647e170eb2240913572da1ffe33175705f305e; supersede the earlier unverified commit/push metadata.", "CorrectionIP", "runtime_reasoning", "supported", "", {"commit": "7b647e170eb2240913572da1ffe33175705f305e"}),
        "IP_ldv2qualified02": ("Local Development v2 is operationally qualified for v1 use at verified commit 7b647e170eb2240913572da1ffe33175705f305e.", "DecisionIP", "runtime_reasoning", "supported", "", {"qualified": True, "commit": "7b647e170eb2240913572da1ffe33175705f305e"}),
        "IP_ldv2graduationreport02": (f"Artifact agent/LOCAL_DEVELOPMENT_V2_GRADUATION_REPORT.json sha256={report_sha}", "ArtifactIP", "runtime_reasoning", "supported", "", {"path": "agent/LOCAL_DEVELOPMENT_V2_GRADUATION_REPORT.json", "sha256": report_sha, "size_bytes": len(raw)}),
        "IP_hermesgovernornext01": ("SToE Hermes Development Governor v1: Hermes B governs the qualified local-worker development loop instead of Codex initiating each stage.", "NextActionIP", "runtime_reasoning", "active", "", {}),
    }
    for ref, (content, kind, origin, outcome, failure, metadata) in nodes.items():
        _ensure_ip(store, ref=ref, identity={"content": content, "kind": kind, "metadata": metadata}, create={"content": content, "kind": kind, "origin": origin, "outcome": outcome, "failure_condition": failure, "session_id": SESSION, "metadata": metadata, "visible": True})
    links = [
        ("LDA_0bafb604347b97a5", "IP_ldv2graduationobjective01", "depends_on", "Accepted local planner action served this graduation objective."),
        ("LDR_c2eefd1dcfcb57c5", "LDR_1be0fd75c1044423", "corrects", "No-op successor corrected the initial grammar failure but was rejected."),
        ("LDR_a81b8a6c001619ab", "LDR_c2eefd1dcfcb57c5", "corrects", "Static-obligation rejection followed the no-op failure."),
        ("LDR_9dc21216fefa12cc", "LDR_a81b8a6c001619ab", "corrects", "Task IR attempt corrected free-form emission and exposed fixed-table schema defect."),
        ("LDR_22b4a405f02b4ebd", "LDR_9dc21216fefa12cc", "corrects", "Fixed-table IR successor produced the accepted candidate."),
        ("LDR_80520178450d3ada", "LDC_24205ebe0e1eda13", "evaluates", "Independent local review of exact accepted candidate artifact."),
        ("IP_ldv2graduationevaluation01", "LDC_24205ebe0e1eda13", "evaluates", "Deterministic focused and full evaluation of exact candidate."),
        ("IP_ldv2graduationcommit02", "IP_ldv2graduationevaluation01", "depends_on", "Trusted apply and commit required green deterministic evaluation."),
        ("IP_ldv2graduationcommit02", "LDC_24205ebe0e1eda13", "implements", "Commit implements the exact accepted candidate."),
        ("IP_ldv2graduationpush02", "IP_ldv2graduationcommit02", "follows", "Normal feature-branch push followed commit."),
        ("IP_ldv2commitidentitycorrection01", "IP_ldv2graduationcommit01", "corrects", "Verified Git identity corrects unverified commit metadata."),
        ("IP_ldv2commitidentitycorrection01", "IP_ldv2graduationpush01", "corrects", "Verified Git identity corrects unverified push metadata."),
        ("IP_ldv2qualified02", "IP_ldv2graduationpush02", "supported_by", "Qualification requires completed push."),
        ("IP_ldv2qualified02", "IP_ldv2graduationevaluation01", "supported_by", "Qualification requires green tests."),
        ("IP_ldv2qualified02", "IP_ldv2qualified01", "corrects", "Verified qualification identity supersedes unverified metadata."),
        ("IP_ldv2graduationreport02", "IP_ldv2qualified02", "summarizes", "Artifact-backed graduation report."),
        ("IP_hermesgovernornext01", "IP_ldv2qualified02", "follows", "Next architectural stage begins after graduation."),
    ]
    for source, target, relation, note in links:
        _ensure_relation(store, source_ref=source, target_ref=target, relation=relation, note=note)
    goal = "Begin SToE Hermes Development Governor v1 from the verified Local Development v2 graduation commit."
    existing = next((item for item in store.list_recent(session_id=SESSION, limit=30)["items"] if item["kind"] == "current_state" and item["metadata"].get("goal") == goal), None)
    state = {"observer_state_ref": existing["ref"]} if existing else store.set_observer_state(
        goal=goal,
        question="How should Hermes B initiate and govern the qualified bounded worker stages while trusted tools retain authority?",
        active_constraints=["Local Development v2 frozen as good enough for v1", "Hermes B only", "Trusted validation/apply/Git authority remains external to models"],
        changed_constraints=["A complete safe local development vertical slice has passed and been pushed."],
        evidence=["Plan, code, review, tests, apply, commit, and push completed", "Candidate and active source hashes match"],
        open_questions=["Minimal Hermes B governor interface and recovery ownership"],
        recent_refs=["IP_ldv2qualified02", "IP_ldv2graduationreport02", "IP_hermesgovernornext01"],
        current_reasoning_ref="IP_hermesgovernornext01",
        session_id=SESSION,
    )
    print(json.dumps({"report_sha256": report_sha, "refs": list(nodes), "state": state["observer_state_ref"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
