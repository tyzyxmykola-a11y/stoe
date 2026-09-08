from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from stoe_agent.self_code_cycle_v2 import ACTION_ID  # noqa: E402
from stoe_agent.supervisor import RebuildSupervisor, SupervisorConfig  # noqa: E402


def main() -> int:
    supervisor = RebuildSupervisor(
        SupervisorConfig.defaults(repo_root=REPO_ROOT, model="gemma4:26b")
    )
    root = REPO_ROOT / "agent" / "self_code_candidates" / "self_code_cycle_v2_deduplicate_context"
    report = REPO_ROOT / "agent" / "SUPERVISED_SELF_CODE_MODIFICATION_V2.md"
    artifacts = (
        ("self_code_v2_preflight", root / "preflight.json", "Bounded model, context, output, checkpoint, and SHA-canonical retrieval preflight.", "generation_preflight", []),
        ("self_code_v2_qualification", root / "qualification.json", "Two disclosed formatting calls: first passed; second stopped at the trusted raw-wire capture bound.", "formatting_qualification", ["self_code_v2_preflight"]),
        ("self_code_v2_raw_qualification_1", root / "raw" / "self-code-cycle_v2_format-qualification-1.ndjson", "Losslessly captured first disclosed formatting response.", "raw_model_response", ["self_code_v2_qualification"]),
        ("self_code_v2_raw_qualification_2", root / "raw" / "self-code-cycle_v2_format-qualification-2.ndjson", "Losslessly captured partial second formatting response; stopped by trusted raw-wire bound.", "raw_model_response", ["self_code_v2_qualification"]),
        ("self_code_v2_postmortem", root / "qualification_postmortem.json", "Diagnosis separating trusted wire-capture termination from provider output truncation or established schema noncompliance.", "failed_attempt", ["self_code_v2_qualification", "self_code_v2_raw_qualification_2"]),
        ("self_code_v2_memory_snapshot", REPO_ROOT / "agent" / "self_code_v2" / "continuity_snapshot.json", "Hash-addressed SToE Memory observer, failure, decision, succession, and exact-next-action reference map.", "continuity_reference", ["self_code_v2_postmortem"]),
        ("self_code_v2_report", report, "Final supervised self-code cycle v2 report; no candidate or activation.", "research_report", ["self_code_v2_postmortem", "self_code_v2_memory_snapshot"]),
        ("self_code_v2_manifest", root / "evidence_manifest.json", "Hashes for the immutable v2 call evidence and report.", "evidence_manifest", ["self_code_v2_report"]),
    )

    action = supervisor.research_state.begin_action(
        action_id=ACTION_ID,
        description="Qualify reliable inert line-patch generation, then permit one model-proposed reporter modification only if the disclosed gate passes.",
    )
    if action.get("duplicate_completed"):
        print(json.dumps({"decision": "SKIP_COMPLETED_ACTION", "action": action}, indent=2))
        return 0
    refs = []
    for ref, path, summary, kind, source_refs in artifacts:
        supervisor.research_state.register_artifact(
            ref=ref,
            path=path,
            summary=summary,
            kind=kind,
            provenance="supervised_self_code_cycle_v2",
            source_refs=source_refs,
        )
        refs.append(ref)

    state = supervisor.research_state.load()
    state["current_task"] = (
        "Self-code v2 failed safely at disclosed formatting qualification 2 because the trusted raw-NDJSON cap terminated capture; "
        "zero real candidate calls and no activation occurred."
    )
    evidence = {
        "claim": "Qualification 1 passed; qualification 2 was terminated by the trusted 64,000-byte raw NDJSON capture bound before a terminal provider event; the main call was never opened.",
        "kind": "failure",
        "source_refs": ["self_code_v2_qualification", "self_code_v2_raw_qualification_2", "self_code_v2_postmortem"],
        "stance": "failure",
    }
    correction = {
        "claim": "Wire-format capture bytes must be bounded separately from reconstructed model payload and output tokens; future infrastructure uses an 8,000,000-byte bound and RAW_CAPTURE_LIMIT_ABORT classification without rewriting v2 evidence.",
        "claim_type": "correction",
        "source_refs": ["self_code_v2_postmortem", "self_code_v2_report"],
    }
    decision = {
        "decision": "Fail closed, preserve both disclosed calls, make no real generation call, leave the active release unchanged, and never retry the closed v2 call IDs.",
        "source_refs": ["self_code_v2_qualification", "self_code_v2_report"],
    }
    question = {
        "claim_type": "question",
        "question": "Can gemma4:26b complete two disclosed inert line-patch qualifications under the corrected bounded wire capture before one newly authorized successor attempt?",
        "source_refs": ["self_code_v2_postmortem", "self_code_v2_memory_snapshot"],
    }
    for key, value in (("evidence", evidence), ("corrections", correction), ("decisions", decision)):
        if value not in state[key]:
            state[key].append(value)
    if question not in state["unresolved_questions"]:
        state["unresolved_questions"].append(question)
    state["active_hypothesis"] = {
        "claim": question["question"],
        "claim_type": "development_hypothesis",
        "source_refs": question["source_refs"],
    }
    state["versions"]["candidate"] = None
    state["next_executable_step"] = (
        "Await Mykola's approval for a new successor action with new stable qualification IDs; do not retry self-code-cycle:v2:deduplicate-development-context."
    )
    supervisor.research_state.save(state)
    supervisor.research_state.set_action_status(action_id=ACTION_ID, status="failed", result_refs=refs)
    checkpoint = supervisor.research_state.checkpoint(
        reason="Conserve v2 formatting-gate failure, raw wire-capture correction, SToE Memory references, and zero real candidate calls"
    )
    resume = supervisor.research_state.build_resume_context(max_tokens=1800)
    print(json.dumps({
        "decision": "FAILED_QUALIFICATION_CONSERVED",
        "action_id": ACTION_ID,
        "artifact_refs": refs,
        "checkpoint": checkpoint,
        "resume": {
            "estimated_tokens": resume["estimated_tokens"],
            "max_tokens": resume["max_tokens"],
            "reserve_tokens": resume["reserve_tokens"],
        },
    }, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
