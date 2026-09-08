from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))
sys.path.insert(0, str(ROOT / "agent" / "src"))
sys.path.insert(0, str(ROOT / "plugins" / "stoe-memory"))

from core import FieldStore
from stoe_agent.self_code_cycle_v2 import atomic_json
from stoe_hermes.split_cycle import (
    ACTION_ID, CODER, EDITABLE_PATH, GEMMA, LocalModelClient, SuccessionError,
    budget_call, code_schema, diff_text, plan_schema, review_schema, sha256_bytes,
    validate_code, validate_plan, validate_review,
)
from stoe_hermes.succession import run_bounded, sanitized_candidate_environment


OBSERVER_REF = "STATE_480a6c6a3a6b4b4a"


class Cycle:
    def __init__(self, runtime: Path):
        self.runtime = runtime
        self.state_path = runtime / "split_cycle.json"
        self.client = LocalModelClient()
        self.state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {"action_id": ACTION_ID, "status": "new", "calls": {}}

    def save(self):
        atomic_json(self.state_path, self.state)

    def call(self, call_id, model, system, prompt, schema, reserve, seed):
        if call_id in self.state["calls"]:
            raise SuccessionError(f"closed or interrupted call cannot repeat: {call_id}")
        budget = budget_call(system, prompt, reserve)
        raw = self.runtime / "raw" / f"{call_id}.ndjson"
        self.state["calls"][call_id] = {"status": "started", "budget": budget, "raw_path": str(raw)}
        self.save()
        result = self.client.generate(name=model[0], digest=model[1], system=system, prompt=prompt, schema=schema, raw_path=raw, num_predict=reserve, seed=seed)
        self.state["calls"][call_id] = {"status": "completed" if result["diagnosis"] == "COMPLETE_STRUCTURED_OUTPUT" else "failed", "budget": budget, "result": result}
        self.save()
        if result["diagnosis"] != "COMPLETE_STRUCTURED_OUTPUT":
            raise SuccessionError(f"{call_id}: {result['diagnosis']}")
        return result["parsed"]


def field_context() -> dict:
    store = FieldStore()
    result = store.navigate(observer_state_ref=OBSERVER_REF, limit=8, max_depth=4, include_failures=True, include_seed=False, per_item_chars=350, total_chars=2800, run_label="hermes_ab_v2_split_cycle")
    payloads = []
    connections = []
    seen = set()
    for item in result["selected_items"]:
        content = item["content"]
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest not in seen:
            seen.add(digest)
            payloads.append({"sha256": digest, "content": content})
        connections.append({"ref": item["ref"], "payload_sha256": digest, "origin": item["origin"], "kind": item["kind"], "outcome": item["outcome"], "path": item["path"]})
    return {"retrieval_run_id": result["run_id"], "canonical_payloads": payloads, "connections": connections, "collapsed": len(result["selected_items"]) - len(payloads)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=ROOT / "agent" / "runtime" / "hermes_ab_v2")
    args = parser.parse_args()
    cycle = Cycle(args.runtime)
    if cycle.state["status"] != "new":
        raise SuccessionError("split cycle stable action already started")
    cycle.state["models"] = {"planner_reviewer": cycle.client.verify(*GEMMA), "coder": cycle.client.verify(*CODER)}
    cycle.state["status"] = "qualifying"
    cycle.save()
    system_plan = "Return only bounded JSON. You are a planner/reviewer, not a code emitter. Never include executable code."
    try:
        qp = cycle.call(
            "qualification_gemma_plan", GEMMA, system_plan,
            "Disclosed format fixture. Plan a two-line change to exactly stoe-hermes/src/stoe_hermes/context_renderer.py that reports a count. Do not emit code.",
            plan_schema(EDITABLE_PATH), 700, 2101,
        )
        validate_plan(qp, EDITABLE_PATH)
        qparent = (ROOT / EDITABLE_PATH).read_text(encoding="utf-8")
        qsha = sha256_bytes(qparent.encode("utf-8"))
        qc = cycle.call(
            "qualification_qwen_code", CODER,
            "Return only the inert JSON patch. No tools or authority.",
            "Disclosed format fixture. Replace the renderer with exactly two lines: the same def signature, then four spaces plus return str(len(items))[:max_chars].",
            code_schema(EDITABLE_PATH, qsha), 900, 2102,
        )
        validate_code(qc, qparent, EDITABLE_PATH)
        qr = cycle.call(
            "qualification_gemma_review", GEMMA,
            "Return only bounded advisory review JSON. Do not emit code.",
            "Disclosed fixture: plan says report count; candidate returns item count under max_chars. Review the match and mention any regression.",
            review_schema(), 500, 2103,
        )
        validate_review(qr)
    except Exception as exc:
        cycle.state.update({"status": "qualification_failed", "failure": f"{type(exc).__name__}: {exc}"})
        cycle.save()
        print(json.dumps({"status": cycle.state["status"], "failure": cycle.state["failure"]}, indent=2))
        return 2
    cycle.state["qualification"] = "passed_3_of_3"
    cycle.state["status"] = "real_running"
    context = field_context()
    cycle.state["field_context"] = {"retrieval_run_id": context["retrieval_run_id"], "payload_count": len(context["canonical_payloads"]), "connection_count": len(context["connections"]), "collapsed": context["collapsed"]}
    cycle.save()
    b_root = args.runtime / "candidate_B"
    target = b_root / "stoe-integration" / "src" / "stoe_hermes" / "context_renderer.py"
    parent = target.read_text(encoding="utf-8")
    parent_sha = sha256_bytes(parent.encode("utf-8"))
    objective = "Improve the stoe-hermes adapter so identical artifact content enters model context once by canonical SHA-256 while every observer, provenance, failure, correction and succession connection remains available; report canonical payload and collapsed duplicate counts."
    plan_prompt = objective + "\nExact editable file: " + EDITABLE_PATH + "\nBounded SToE context:\n" + json.dumps(context, ensure_ascii=False, sort_keys=True)
    try:
        plan = validate_plan(cycle.call("real_gemma_plan", GEMMA, system_plan, plan_prompt, plan_schema(EDITABLE_PATH), 900, 2201), EDITABLE_PATH)
        code_prompt = "Accepted plan:\n" + json.dumps(plan, ensure_ascii=False, sort_keys=True) + "\nExact parent source (once), SHA-256 " + parent_sha + ":\n" + parent + "\nInterfaces: render_retrieved_context(items,max_chars) is called only after bounded MCP retrieval. Existing focused test requires one PAYLOAD line, two CONNECTION lines, collapsed=1. Return only the inert patch."
        proposal = cycle.call("real_qwen_code", CODER, "You are a code-specialized instrument with no tools. Return only the bounded inert patch JSON.", code_prompt, code_schema(EDITABLE_PATH, parent_sha), max(1800, len(parent.encode("utf-8")) // 2), 2202)
        sealed, candidate, validation = validate_code(proposal, parent, EDITABLE_PATH)
        candidate_artifact = args.runtime / "candidate_artifacts" / "context_renderer.py"
        candidate_artifact.parent.mkdir(parents=True, exist_ok=True)
        candidate_artifact.write_text(candidate, encoding="utf-8", newline="\n")
        atomic_json(args.runtime / "candidate_artifacts" / "sealed_patch.json", sealed)
        target.write_text(candidate, encoding="utf-8", newline="\n")
        clean_base = json.loads((args.runtime / "clean_base.json").read_text(encoding="utf-8"))
        py = clean_base["environment"]["python"]
        env = sanitized_candidate_environment(Path(clean_base["profile"]["profile_root"]), Path(clean_base["environment"]["environment_root"]))
        env["PYTHONPATH"] = str((b_root / "stoe-integration" / "src").resolve())
        check = "from stoe_hermes.context_renderer import render_retrieved_context;import hashlib;c='same';h=hashlib.sha256(c.encode()).hexdigest();x=[{'sha256':h,'content':c,'ref':'A','relation':'failure','provenance':'p1'},{'sha256':h,'content':c,'ref':'B','relation':'correction','provenance':'p2'}];r=render_retrieved_context(x,4000);assert r.count('PAYLOAD |')==1 and r.count('CONNECTION |')==2 and 'collapsed=1' in r"
        tests = [run_bounded([py, "-m", "py_compile", str(target)], cwd=b_root / "stoe-integration", env=env), run_bounded([py, "-c", check], cwd=b_root / "stoe-integration", env=env)]
        if not all(item["passed"] for item in tests):
            raise SuccessionError("focused candidate evaluation failed")
        delta = diff_text(parent, candidate)
        review_prompt = "Plan:\n" + json.dumps(plan, ensure_ascii=False, sort_keys=True) + "\nCandidate diff:\n" + delta + "\nMeasured focused tests:\n" + json.dumps([{k:v for k,v in t.items() if k not in {'stdout','stderr'}} for t in tests], sort_keys=True)
        review = validate_review(cycle.call("real_gemma_review", GEMMA, "Advisory reviewer only. Return review JSON; never issue commands or code.", review_prompt, review_schema(), 700, 2203))
        cycle.state.update({"status": "awaiting_author_approval", "plan": plan, "candidate": {"path": str(candidate_artifact), "parent_sha256": parent_sha, "candidate_sha256": validation["candidate_sha256"], "sealed_patch": str(args.runtime / "candidate_artifacts" / "sealed_patch.json")}, "focused_tests": tests, "review": review, "activation_status": "inactive"})
    except Exception as exc:
        cycle.state.update({"status": "real_failed", "failure": f"{type(exc).__name__}: {exc}", "activation_status": "inactive"})
    cycle.save()
    print(json.dumps({"status": cycle.state["status"], "failure": cycle.state.get("failure"), "candidate": cycle.state.get("candidate"), "calls": {k:v["status"] for k,v in cycle.state["calls"].items()}}, indent=2))
    return 0 if cycle.state["status"] == "awaiting_author_approval" else 2


if __name__ == "__main__":
    raise SystemExit(main())
