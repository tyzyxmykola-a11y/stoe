from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from stoe_agent.self_code_cycle import ACTION_ID  # noqa: E402
from stoe_agent.supervisor import RebuildSupervisor, SupervisorConfig  # noqa: E402


def main() -> int:
    supervisor = RebuildSupervisor(
        SupervisorConfig.defaults(repo_root=REPO_ROOT, model="gemma4:26b")
    )
    candidate_root = REPO_ROOT / "agent" / "self_code_candidates" / "self_code_cycle_v1_deduplicate_context"
    report_path = REPO_ROOT / "agent" / "SUPERVISED_SELF_CODE_MODIFICATION_V1.md"
    failure_path = candidate_root / "failed_attempt.json"
    manifest_path = candidate_root / "attempt_manifest.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))

    action = supervisor.research_state.begin_action(
        action_id=ACTION_ID,
        description="One bounded model-proposed source modification of the agent-owned development-context reporter.",
    )
    if action.get("duplicate_completed"):
        print(json.dumps({"decision": "SKIP_COMPLETED_ACTION", "action": action}, indent=2))
        return 0

    refs = []
    for ref, path, summary, kind in (
        (
            "self_code_v1_attempt_manifest",
            manifest_path,
            "Exact bounded objective, retrieved SToE context and traversal trace, prompt/schema/settings, and response-preservation limitation.",
            "generation_trace",
        ),
        (
            "self_code_v1_failed_attempt",
            failure_path,
            "One gemma4:26b call failed schema parsing; no valid patch or candidate source was accepted.",
            "failed_candidate",
        ),
        (
            "self_code_v1_report",
            report_path,
            "Supervised self-code-modification v1 implementation and failed-cycle report.",
            "research_report",
        ),
    ):
        supervisor.research_state.register_artifact(
            ref=ref,
            path=path,
            summary=summary,
            kind=kind,
            provenance="supervised_self_code_cycle_v1",
            source_refs=refs.copy(),
        )
        refs.append(ref)

    state = supervisor.research_state.load()
    state["current_task"] = (
        "Supervised self-code-modification v1 completed as a safe failed attempt: one gemma4:26b response was malformed; "
        "no candidate source or activation exists."
    )
    failure_claim = {
        "claim": (
            "The first supervised source-generation call returned an unterminated JSON string; the inert patch gate accepted no "
            "artifact, the active source stayed unchanged, and the same stable action is not retryable."
        ),
        "kind": "failure",
        "source_refs": ["self_code_v1_failed_attempt", "self_code_v1_attempt_manifest", "self_code_v1_report"],
        "stance": "failure",
    }
    if failure_claim not in state["evidence"]:
        state["evidence"].append(failure_claim)
    correction = {
        "claim": (
            "Instrumentation correction: the frozen Ollama client raises during JSON parsing before returning the malformed raw "
            "provider body, so this attempt preserves the exact error and prompt but not the raw response."
        ),
        "claim_type": "correction",
        "source_refs": ["self_code_v1_attempt_manifest", "self_code_v1_report"],
    }
    if correction not in state["corrections"]:
        state["corrections"].append(correction)
    decision = {
        "decision": (
            "Fail closed, preserve the attempt, do not retry its stable action, and do not activate; qualify lossless raw-response "
            "capture under a new approved development action before another generation."
        ),
        "source_refs": ["self_code_v1_failed_attempt", "self_code_v1_report"],
    }
    if decision not in state["decisions"]:
        state["decisions"].append(decision)
    question = {
        "claim_type": "question",
        "question": (
            "How can a successor cycle preserve raw Ollama output before parsing and qualify schema-complete gemma4:26b patch "
            "responses on disclosed fixtures without weakening the inert patch boundary or executing generated Python?"
        ),
        "source_refs": ["self_code_v1_attempt_manifest", "self_code_v1_report"],
    }
    state["active_hypothesis"] = {
        "claim": question["question"],
        "claim_type": "development_hypothesis",
        "source_refs": question["source_refs"],
    }
    if question not in state["unresolved_questions"]:
        state["unresolved_questions"].append(question)
    state["versions"]["candidate"] = None
    state["next_executable_step"] = (
        "Await Mykola's approval for a new action that adds lossless raw-response capture and disclosed schema rehearsal; do not "
        "retry self-code-cycle:v1:deduplicate-development-context."
    )
    supervisor.research_state.save(state)
    supervisor.research_state.set_action_status(
        action_id=ACTION_ID,
        status="failed",
        result_refs=refs,
    )

    field_result_refs = failure.get("field_refs", {})
    report_ip = supervisor.journal.add_ip(
        cycle_id="SELF_CODE_V1_FAILED",
        label="final_report",
        content=f"Full conserved report: {report_path.relative_to(REPO_ROOT).as_posix()}",
        kind="report",
        outcome="preserved",
        metadata={"artifact_ref": "self_code_v1_report"},
    )
    if field_result_refs.get("decision"):
        supervisor.journal.relate(
            field_result_refs["decision"],
            report_ip["ref"],
            "conserved_by",
            "The tracked report conserves the failed succession decision.",
        )
    checkpoint = supervisor.research_state.checkpoint(
        reason="Conserve supervised self-code-modification v1 failed attempt without retry or activation"
    )
    resume = supervisor.research_state.build_resume_context(max_tokens=1800)
    print(
        json.dumps(
            {
                "decision": "FAILED_ATTEMPT_CONSERVED",
                "action_id": ACTION_ID,
                "artifact_refs": refs,
                "field_report_ref": report_ip["ref"],
                "checkpoint": checkpoint,
                "resume": {
                    "estimated_tokens": resume["estimated_tokens"],
                    "max_tokens": resume["max_tokens"],
                    "reserve_tokens": resume["reserve_tokens"],
                },
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
