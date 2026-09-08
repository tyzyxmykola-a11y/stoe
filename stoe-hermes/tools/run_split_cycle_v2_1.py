from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))
sys.path.insert(0, str(ROOT / "agent" / "src"))
sys.path.insert(0, str(ROOT / "plugins" / "stoe-memory"))

from core import FieldStore
from stoe_agent.self_code_cycle_v2 import atomic_json
from stoe_agent.token_budget import TokenEstimator
from stoe_hermes.split_cycle import (
    CODER,
    GEMMA,
    LocalModelClient,
    budget_call,
    code_schema,
    diff_text,
    sha256_bytes,
    validate_code,
)
from stoe_hermes.split_cycle_v2_1 import (
    ACTION_ID,
    FIXED_PLAN,
    PLAN_OUTPUT_TOKENS,
    compact_review_schema,
    fixed_plan_schema,
    plan_with_one_repair,
    validate_compact_review,
)
from stoe_hermes.succession import SuccessionError, run_bounded, sanitized_candidate_environment


OBSERVER_REF = "STATE_87a846a5a7c541fc"
EDITABLE_PATH = "stoe-hermes/src/stoe_hermes/context_renderer.py"


class Cycle:
    def __init__(self, runtime: Path):
        self.runtime = runtime.resolve()
        self.state_path = self.runtime / "cycle.json"
        self.client = LocalModelClient()
        if self.state_path.exists():
            raise SuccessionError("v2.1 stable action already started; never repeat it")
        self.state = {"action_id": ACTION_ID, "status": "new", "calls": {}, "format_failures": []}

    def save(self) -> None:
        atomic_json(self.state_path, self.state)

    def call(self, call_id: str, model: tuple[str, str], system: str, prompt: str, schema: dict, reserve: int, seed: int) -> dict:
        if call_id in self.state["calls"]:
            raise SuccessionError(f"stable model call cannot repeat: {call_id}")
        budget = budget_call(system, prompt, reserve)
        raw_path = self.runtime / "raw" / f"{call_id}.ndjson"
        self.state["calls"][call_id] = {"status": "started", "budget": budget, "raw_path": str(raw_path)}
        self.save()
        result = self.client.generate(
            name=model[0], digest=model[1], system=system, prompt=prompt,
            schema=schema, raw_path=raw_path, num_predict=reserve, seed=seed,
        )
        status = "completed" if result["diagnosis"] == "COMPLETE_STRUCTURED_OUTPUT" else "failed"
        self.state["calls"][call_id] = {"status": status, "budget": budget, "result": result}
        self.save()
        return result


def docker_containment_status() -> dict:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return {
            "client_present": True,
            "daemon_available": result.returncode == 0,
            "server_version": result.stdout.strip() if result.returncode == 0 else None,
            "diagnostic": result.stderr.strip()[:300],
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"client_present": False, "daemon_available": False, "server_version": None, "diagnostic": type(exc).__name__}


def field_context() -> dict:
    store = FieldStore()
    result = store.navigate(
        observer_state_ref=OBSERVER_REF, limit=10, max_depth=4,
        include_failures=True, include_seed=False, per_item_chars=420,
        total_chars=4_000, run_label="hermes_ab_v2_1_real_plan",
    )
    canonical: list[dict] = []
    connections: list[dict] = []
    seen: set[str] = set()
    for item in result["selected_items"]:
        content = item["content"]
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest not in seen:
            seen.add(digest)
            canonical.append({"sha256": digest, "content": content})
        connections.append({
            "ref": item["ref"], "payload_sha256": digest, "origin": item["origin"],
            "kind": item["kind"], "outcome": item["outcome"],
            "path": [
                {"type": edge["type"], "direction": edge["direction"], "from": edge["from"], "to": edge["to"]}
                for edge in item["path"]
            ],
        })
    before = json.dumps(result["selected_items"], ensure_ascii=False, sort_keys=True)
    after_value = {"canonical_payloads": canonical, "connections": connections}
    after = json.dumps(after_value, ensure_ascii=False, sort_keys=True)
    estimator = TokenEstimator()
    return {
        "retrieval_run_id": result["run_id"],
        **after_value,
        "canonical_payload_count": len(canonical),
        "connection_count": len(connections),
        "collapsed_duplicate_count": len(result["selected_items"]) - len(canonical),
        "estimated_tokens_before": estimator.estimate(before),
        "estimated_tokens_after": estimator.estimate(after),
    }


def trusted_inspection(parent: str, candidate: str, validation: dict, delta: str, docker: dict) -> dict:
    unrelated = [line for line in delta.splitlines() if line.startswith(("+++", "---")) and line not in {"--- parent", "+++ candidate"}]
    passed = (
        validation["lines"] <= 80
        and validation["bytes"] <= 12_000
        and not unrelated
        and "canonical_payloads=" in candidate
        and "collapsed_duplicates=" in candidate
        and candidate != parent
    )
    return {
        "passed": passed,
        "basis": "trusted_deterministic_ast_and_diff_inspection",
        "container": docker,
        "container_used": False,
        "candidate_capability": "single validated pure formatter; imports unchanged; calls and attributes allowlisted",
        "candidate_sha256": validation["candidate_sha256"],
        "diff_sha256": sha256_bytes(delta.encode("utf-8")),
        "unrelated_diff_headers": unrelated,
        "required_reporting_present": "canonical_payloads=" in candidate and "collapsed_duplicates=" in candidate,
        "remaining_host_authority": "bounded subprocess runs under the host account; static capability validation is the execution boundary",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=ROOT / "agent" / "runtime" / "hermes_ab_v2_1")
    args = parser.parse_args()
    cycle = Cycle(args.runtime)
    cycle.runtime.mkdir(parents=True, exist_ok=True)
    cycle.state["models"] = {
        "planner_reviewer": cycle.client.verify(*GEMMA),
        "coder": cycle.client.verify(*CODER),
    }
    cycle.state["container"] = docker_containment_status()
    context = field_context()
    cycle.state["field_context"] = {key: value for key, value in context.items() if key not in {"canonical_payloads", "connections"}}
    cycle.state["status"] = "planning"
    cycle.save()

    plan_system = "Return one JSON object only. Every value is a fixed schema identifier. No prose, code, explanation, or repeated words."
    plan_prompt = (
        "OBJECTIVE_ID=deduplicate_context_reporting_v2_1. Select the only enum value for every required field. "
        "The existing formatter already canonicalizes bytes; this successor must make canonical payload and collapsed duplicate counts explicit while retaining legacy header compatibility. "
        "Bounded SToE evidence follows: " + json.dumps(context, ensure_ascii=False, sort_keys=True)
    )

    def plan_call(call_id: str, prompt: str) -> dict:
        result = cycle.call(call_id, GEMMA, plan_system, prompt, fixed_plan_schema(), PLAN_OUTPUT_TOKENS, 2301 if not call_id.endswith("repair_1") else 2302)
        if result["diagnosis"] != "COMPLETE_STRUCTURED_OUTPUT":
            cycle.state["format_failures"].append({
                "call_id": call_id,
                "diagnosis": result["diagnosis"],
                "raw_path": result["raw_path"],
                "raw_sha256": result["raw_sha256"],
                "failure_condition": "model output was truncated or malformed under the fixed schema",
            })
            cycle.save()
        return result

    try:
        plan, plan_attempts = plan_with_one_repair(plan_call, primary_id="real_gemma_plan", primary_prompt=plan_prompt)
        cycle.state["plan"] = plan
        cycle.state["plan_attempt_count"] = len(plan_attempts)
        cycle.state["status"] = "coding"
        cycle.save()

        b_root = ROOT / "agent" / "runtime" / "hermes_ab_v2" / "candidate_B"
        target = b_root / "stoe-integration" / "src" / "stoe_hermes" / "context_renderer.py"
        clean_base = json.loads((ROOT / "agent" / "runtime" / "hermes_ab_v2" / "clean_base.json").read_text(encoding="utf-8"))
        if clean_base["release"]["commit_sha"] != "bb924730743cc05934bf0dfd188abdfdb46c03c2":
            raise SuccessionError("candidate B parent identity changed")
        parent = target.read_text(encoding="utf-8")
        parent_sha = sha256_bytes(parent.encode("utf-8"))
        code_prompt = (
            "FIXED_PLAN=" + json.dumps(plan, sort_keys=True) + "\n"
            "Return one inert stoe.line_patch JSON object for exactly " + EDITABLE_PATH + ". "
            "Keep the existing SHA-256 payload deduplication and every CONNECTION record. Keep legacy payloads= and collapsed= header fields, and additionally report canonical_payloads= and collapsed_duplicates=. "
            "Change only render_retrieved_context. Exact parent SHA-256=" + parent_sha + ". Exact parent source follows once:\n" + parent
        )
        code_result = cycle.call(
            "real_qwen_code", CODER,
            "You are a code-emission instrument with no tools or authority. Return only the inert bounded patch JSON.",
            code_prompt, code_schema(EDITABLE_PATH, parent_sha), 2_400, 2303,
        )
        if code_result["diagnosis"] != "COMPLETE_STRUCTURED_OUTPUT":
            raise SuccessionError(f"single Qwen call failed: {code_result['diagnosis']}")
        sealed, candidate, validation = validate_code(code_result["parsed"], parent, EDITABLE_PATH)
        delta = diff_text(parent, candidate)
        artifact_root = cycle.runtime / "candidate_artifacts"
        artifact_root.mkdir(parents=True, exist_ok=True)
        candidate_path = artifact_root / "context_renderer.py"
        candidate_path.write_text(candidate, encoding="utf-8", newline="\n")
        atomic_json(artifact_root / "sealed_patch.json", sealed)

        inspection = trusted_inspection(parent, candidate, validation, delta, cycle.state["container"])
        atomic_json(artifact_root / "trusted_inspection.json", inspection)
        cycle.state["trusted_inspection"] = inspection
        if not inspection["passed"]:
            raise SuccessionError("trusted inspection rejected candidate before execution")

        target.write_text(candidate, encoding="utf-8", newline="\n")
        env = sanitized_candidate_environment(
            Path(clean_base["profile"]["profile_root"]),
            Path(clean_base["environment"]["environment_root"]),
        )
        env["PYTHONPATH"] = str((b_root / "stoe-integration" / "src").resolve())
        py = clean_base["environment"]["python"]
        check = (
            "from stoe_hermes.context_renderer import render_retrieved_context;import hashlib;"
            "c='same';h=hashlib.sha256(c.encode()).hexdigest();"
            "x=[{'sha256':h,'content':c,'ref':'A','origin':'failure_history','kind':'failure','outcome':'failed','path':'p1','relation':'correction_of','direction':'incoming','provenance':'one'},"
            "{'sha256':h,'content':c,'ref':'B','origin':'runtime_reasoning','kind':'correction','outcome':'supported','path':'p2','relation':'successor','direction':'outgoing','provenance':'two'}];"
            "before=[dict(i) for i in x];r=render_retrieved_context(x,4000);"
            "assert x==before and r.count('PAYLOAD |')==1 and r.count('CONNECTION |')==2 and r.count('same')==1;"
            "assert 'payloads=1' in r and 'collapsed=1' in r and 'canonical_payloads=1' in r and 'collapsed_duplicates=1' in r;"
            "assert len(render_retrieved_context(x,120))<=120"
        )
        focused = [
            run_bounded([py, "-m", "py_compile", str(target)], cwd=b_root / "stoe-integration", env=env, timeout=20, output_limit=100_000),
            run_bounded([py, "-c", check], cwd=b_root / "stoe-integration", env=env, timeout=20, output_limit=100_000),
        ]
        cycle.state["focused_tests"] = focused
        if not all(item["passed"] for item in focused):
            raise SuccessionError("candidate failed bounded focused evaluation")

        review_prompt = (
            "PLAN_ID=" + FIXED_PLAN["behavior_id"] + ". DIFF=" + delta
            + ". TESTS=passed. Select one enum for every review field."
        )
        review_result = cycle.call(
            "real_gemma_review", GEMMA,
            "Return one compact advisory-review JSON object only. No prose or code.",
            review_prompt, compact_review_schema(), 600, 2304,
        )
        if review_result["diagnosis"] != "COMPLETE_STRUCTURED_OUTPUT":
            raise SuccessionError(f"compact review failed: {review_result['diagnosis']}")
        review = validate_compact_review(review_result["parsed"])
        cycle.state.update({
            "status": "awaiting_author_approval",
            "candidate": {
                "path": str(candidate_path),
                "target_in_b": str(target),
                "parent_sha256": parent_sha,
                "candidate_sha256": validation["candidate_sha256"],
                "sealed_patch": str(artifact_root / "sealed_patch.json"),
                "diff_sha256": inspection["diff_sha256"],
            },
            "review": review,
            "activation_status": "inactive",
            "rollback_target": "hermes-a-bb924730743c",
        })
    except Exception as exc:
        cycle.state.update({
            "status": "failed_conserved",
            "failure": f"{type(exc).__name__}: {exc}",
            "activation_status": "inactive",
            "rollback_target": "hermes-a-bb924730743c",
        })
    cycle.save()
    print(json.dumps({
        "status": cycle.state["status"],
        "failure": cycle.state.get("failure"),
        "candidate": cycle.state.get("candidate"),
        "calls": {key: value["status"] for key, value in cycle.state["calls"].items()},
        "field_context": cycle.state.get("field_context"),
        "container": cycle.state.get("container"),
    }, indent=2))
    return 0 if cycle.state["status"] == "awaiting_author_approval" else 2


if __name__ == "__main__":
    raise SystemExit(main())
