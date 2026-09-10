from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT_SRC = ROOT / "agent" / "src"
HERMES_SRC = ROOT / "stoe-hermes" / "src"
sys.path[:0] = [str(AGENT_SRC), str(HERMES_SRC)]

from stoe_agent.local_development import LocalDevelopmentError, _ensure_ip, _ensure_relation, control_schema  # noqa: E402
from stoe_agent.local_development_pipeline import field_store, record_routing_evidence  # noqa: E402
from stoe_hermes.development_governor import task_scope_schema, validate_task_scope  # noqa: E402


RUNNER_PATH = ROOT / "stoe-hermes" / "tools" / "run_development_governor_v1.py"
SPEC = importlib.util.spec_from_file_location("stoe_governor_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("qualified governor runner unavailable")
gov = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gov)

RUNTIME = ROOT / "agent" / "runtime" / "hermes_standalone_v1"
STATE_PATH = RUNTIME / "state.json"
TARGET = "stoe-hermes/README.md"
HEADING = "Standalone Hermes Development Runtime v1"
DEFAULT_OBJECTIVE = (
    "Document the standalone Hermes Development Runtime v1 command, restart recovery, "
    "trusted execution boundary, and SToE Memory continuity in stoe-hermes/README.md."
)
SESSION = "development:hermes-standalone-v1"
PARENT_OBSERVER = "STATE_b8fdd5504ce442d2"
PARENT_REFS = ["IP_hermesgovernorqualified01", "IP_hermesgovernornext02"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def load_state() -> dict:
    if not STATE_PATH.is_file():
        return {
            "format": "stoe.hermes.standalone_state.v1",
            "observer": PARENT_OBSERVER,
            "status": "idle",
            "objective": DEFAULT_OBJECTIVE,
            "active_action": None,
            "closed_actions": [],
            "pending_next": "develop",
            "applied": False,
            "commit": None,
            "pushed": False,
        }
    value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if value.get("format") != "stoe.hermes.standalone_state.v1":
        raise RuntimeError("incompatible standalone state")
    return value


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=False,
    )
    if check and result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {(result.stderr or result.stdout)[-800:]}")
    return result.stdout.strip()


def branch_and_head() -> tuple[str, str]:
    return git("branch", "--show-current"), git("rev-parse", "HEAD")


def validate_objective(value: str) -> str:
    if not isinstance(value, str) or not 20 <= len(value) <= 400 or any(ch in value for ch in "\r\n\x00"):
        raise ValueError("objective must be one bounded line")
    folded = value.casefold()
    if "stoe-hermes/readme.md" not in folded or not any(word in folded for word in ("document", "documentation")):
        raise ValueError("standalone v1 accepts only a bounded stoe-hermes/README.md documentation objective")
    return value


def exact_scope(objective: str, task_id: str) -> dict:
    gov.OBJECTIVE, gov.TASK_ID, gov.TARGET, gov.HEADING = objective, task_id, TARGET, HEADING
    gov.PARENT_REFS = list(PARENT_REFS)
    return gov.exact_scope()


def patch_schema(parent_sha: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "control": control_schema(),
            "patch": {
                "type": "object",
                "properties": {
                    "format": {"type": "string", "enum": ["stoe.documentation_sentences.v1"]},
                    "path": {"type": "string", "enum": [TARGET]},
                    "parent_sha256": {"type": "string", "enum": [parent_sha]},
                    "heading": {"type": "string", "enum": [HEADING]},
                    "sentences": {"type": "array", "minItems": 4, "maxItems": 7, "items": {"type": "string", "minLength": 55, "maxLength": 240, "pattern": "^[^#\\r\\n]+$"}},
                },
                "required": ["format", "path", "parent_sha256", "heading", "sentences"],
                "additionalProperties": False,
            },
        },
        "required": ["control", "patch"],
        "additionalProperties": False,
    }


def validate_patch(value: dict, parent_sha: str) -> dict:
    required = {"format", "path", "parent_sha256", "heading", "sentences"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("patch fields mismatch")
    if value["format"] != "stoe.documentation_sentences.v1" or value["path"] != TARGET:
        raise ValueError("patch target mismatch")
    if value["parent_sha256"] != parent_sha or value["heading"] != HEADING:
        raise ValueError("patch identity mismatch")
    sentences = value["sentences"]
    if (not isinstance(sentences, list) or not 4 <= len(sentences) <= 7
            or any(not isinstance(item, str) or not 55 <= len(item) <= 240 or "\n" in item or "\r" in item or item.lstrip().startswith("#") for item in sentences)):
        raise ValueError("sentence table outside bounds")
    body = " ".join(sentences)
    if not 300 <= len(body) <= 1200 or "\x00" in body:
        raise ValueError("assembled body outside bounds")
    required_terms = ("hermes", "stoe memory", "taskscope", "restart", "trusted", "model")
    if any(term not in body.casefold() for term in required_terms):
        raise ValueError("patch omits required runtime semantics")
    forbidden = ("force push", "merge to main", "unrestricted", "codex approval", "credential access")
    if any(term in body.casefold() for term in forbidden):
        raise ValueError("patch contains forbidden authority claim")
    return value


def configure_runner(objective: str, task_id: str) -> None:
    gov.RUNTIME = RUNTIME
    gov.SESSION = SESSION
    gov.OBJECTIVE = objective
    gov.TASK_ID = task_id
    gov.TARGET = TARGET
    gov.HEADING = HEADING
    gov.PARENT_REFS = list(PARENT_REFS)


def run_model(action_id: str, role: str, prompt: dict, schema: dict, output_tokens: int) -> tuple[dict, dict]:
    parsed, manifest, meta = gov.model_call(
        action_id=action_id, role=role, prompt_value=prompt, schema=schema,
        difficulty="high" if role in {"governor", "coder", "reviewer"} else "medium",
        output_tokens=output_tokens,
    )
    if parsed.get("status") == "deferred":
        raise RuntimeError(f"resource governor deferred {role}: {meta}")
    return parsed, manifest


def record_worker(role: str, action_id: str, manifest: dict, control: dict, objective: str, artifact: dict | None = None) -> dict:
    return gov.record_control(action_id=action_id, role=role, manifest=manifest, control=control, goal=objective, artifact=artifact)


def run_tests() -> dict:
    commands = [
        ([sys.executable, "-m", "unittest", "discover", "-s", "stoe-hermes/tests", "-q"], str(HERMES_SRC)),
        ([sys.executable, "-m", "unittest", "agent.tests.test_hermes_standalone", "-q"], str(AGENT_SRC)),
    ]
    results = []
    for command, pythonpath in commands:
        env = os.environ.copy()
        env["PYTHONPATH"] = pythonpath
        completed = subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180, check=False)
        results.append({"command": command, "returncode": completed.returncode, "output": (completed.stdout + completed.stderr)[-3000:]})
        if completed.returncode:
            raise RuntimeError(f"deterministic tests failed: {results[-1]}")
    cli_sha = sha256((ROOT / "agent" / "src" / "stoe_agent" / "cli.py").read_bytes())
    if cli_sha != "fca641b2bc136e01441f2f22b36fa493cd662da082ece5ec38d3cfae306567e7":
        raise RuntimeError("frozen CLI hash changed")
    return {"commands": results, "frozen_cli_sha256": cli_sha}


def ensure_clean_feature_branch() -> tuple[str, str]:
    branch, head = branch_and_head()
    if not branch.startswith("feature/") or branch == "main":
        raise RuntimeError("standalone trusted executor requires a feature branch")
    if git("status", "--porcelain=v1"):
        raise RuntimeError("working tree must be clean before standalone develop")
    return branch, head


def finish_committed(state: dict) -> dict:
    branch, head = branch_and_head()
    if branch != state["branch"] or head != state["commit"] or not branch.startswith("feature/"):
        raise RuntimeError("committed recovery identity mismatch")
    if git("status", "--porcelain=v1"):
        raise RuntimeError("committed recovery requires a clean tree")
    git("push", "origin", branch)
    state.update({"pushed": True, "status": "completed", "pending_next": "next_observer"})
    observer = conserve_completion(state, state["task_scope_ref"], state["worker_refs"], state["evaluation"])
    state.update({"observer": observer, "pending_next": "bounded_objective"})
    atomic_json(STATE_PATH, state)
    return state


def finish_applied(state: dict) -> dict:
    branch, head = branch_and_head()
    if branch != state["branch"] or head != state["parent_head"] or not branch.startswith("feature/"):
        raise RuntimeError("applied recovery identity mismatch")
    target = ROOT / TARGET
    if sha256(target.read_bytes()) != state["candidate_sha256"]:
        raise RuntimeError("applied candidate identity mismatch")
    changed = [line for line in git("status", "--porcelain=v1").splitlines() if line]
    if changed != [f" M {TARGET}"]:
        raise RuntimeError(f"trusted scope violation before tests: {changed}")
    evaluation = run_tests()
    if git("diff", "--check", check=False):
        raise RuntimeError("git diff --check failed")
    state["evaluation"] = {"candidate_sha256": state["candidate_sha256"], "tests": "passed", "details": evaluation}
    atomic_json(STATE_PATH, state)
    git("add", "--", TARGET)
    git("commit", "-m", "Document standalone Hermes development runtime v1")
    state.update({"commit": git("rev-parse", "HEAD"), "status": "committed", "pending_next": "push"})
    atomic_json(STATE_PATH, state)
    return finish_committed(state)


def rollback_applied(state: dict) -> None:
    target = ROOT / TARGET
    parent = git("show", f"{state['parent_head']}:{TARGET}") + "\n"
    if sha256(parent.encode()) != state["parent_sha256"]:
        raise RuntimeError("rollback parent identity mismatch")
    target.write_text(parent, encoding="utf-8", newline="\n")
    state.update({"applied": False, "status": "failed", "pending_next": "stopped_after_rollback"})
    atomic_json(STATE_PATH, state)


def conserve_completion(state: dict, scope_ref: str, refs: dict, evaluation: dict) -> str:
    store = field_store()
    commit = state["commit"]
    nodes = {
        "IP_hermesstandaloneruntime01": ("Standalone Hermes Development Runtime v1 runs without Codex session state or approval UI.", "StandaloneRuntimeIP", "supported", {}),
        "IP_hermesstandaloneobjective01": (state["objective"], "DevelopmentObjectiveIP", "supported", {}),
        "IP_hermesstandaloneevaluation01": ("Standalone governed candidate passed deterministic tests and exact scoped-apply verification.", "evaluation", "passed", evaluation),
        "IP_hermesstandalonecommit01": (f"Standalone trusted executor created commit {commit}.", "CommitIP", "supported", {"commit": commit}),
        "IP_hermesstandalonepush01": (f"Standalone trusted executor pushed {commit} to {state['branch']}.", "PushIP", "supported", {"commit": commit, "branch": state["branch"]}),
        "IP_hermesstandalonenext01": ("Hermes standalone runtime selects the next bounded documentation objective from SToE state or accepts one from the operator.", "NextActionIP", "active", {}),
    }
    for ref, (content, kind, outcome, metadata) in nodes.items():
        _ensure_ip(store, ref=ref, identity={"content": content, "kind": kind, "metadata": metadata}, create={"content": content, "kind": kind, "origin": "runtime_reasoning", "outcome": outcome, "failure_condition": "", "session_id": SESSION, "metadata": metadata, "visible": True})
    links = [
        ("IP_hermesstandaloneruntime01", PARENT_OBSERVER, "follows", "Standalone runtime resumes the qualified governor observer."),
        ("IP_hermesstandaloneobjective01", "IP_hermesstandaloneruntime01", "generated_by", "Runtime selected or received the bounded objective."),
        (scope_ref, "IP_hermesstandaloneobjective01", "scopes", "Validated TaskScope bounds all worker and executor authority."),
        (refs["planner"]["result"], scope_ref, "depends_on", "Planner operates under TaskScope."),
        (refs["coder"]["result"], refs["planner"]["result"], "follows", "Coder implements the accepted plan as inert data."),
        (refs["reviewer"]["result"], refs["coder"]["artifact"], "evaluates", "Independent reviewer evaluates the exact candidate artifact."),
        ("IP_hermesstandaloneevaluation01", refs["coder"]["artifact"], "evaluates", "Trusted tests evaluate the exact candidate."),
        ("IP_hermesstandalonecommit01", "IP_hermesstandaloneevaluation01", "depends_on", "Commit requires green deterministic evaluation."),
        ("IP_hermesstandalonepush01", "IP_hermesstandalonecommit01", "follows", "Normal feature push follows commit."),
        ("IP_hermesstandalonenext01", "IP_hermesstandalonepush01", "follows", "Next observer becomes active after push."),
    ]
    for source, target, relation, note in links:
        _ensure_relation(store, source_ref=source, target_ref=target, relation=relation, note=note)
    result = store.set_observer_state(
        goal="Run the next bounded standalone Hermes development objective.",
        question="Which allowed documentation objective should standalone Hermes govern next?",
        active_constraints=["Feature branch only", "Exact TaskScope before workers", "Models have no trusted executor authority"],
        changed_constraints=["Standalone runtime completed a full governed commit and push without Codex runtime dependency."],
        evidence=[f"Commit {commit} pushed", "Deterministic tests passed"],
        open_questions=["Next operator-supplied or field-selected bounded documentation objective"],
        recent_refs=["IP_hermesstandaloneruntime01", "IP_hermesstandaloneevaluation01", "IP_hermesstandalonenext01"],
        current_reasoning_ref="IP_hermesstandalonenext01",
        session_id=SESSION,
    )
    return result["observer_state_ref"]


def develop(objective_arg: str | None) -> dict:
    state = load_state()
    if state["status"] == "completed":
        return state
    if state["status"] == "committed":
        return finish_committed(state)
    if state["status"] == "running" and state.get("applied"):
        try:
            return finish_applied(state)
        except Exception:
            rollback_applied(state)
            raise
    objective = validate_objective(objective_arg or state.get("objective") or DEFAULT_OBJECTIVE)
    branch, parent_head = ensure_clean_feature_branch()
    task_key = sha256(objective.encode())[:12]
    task_id = f"hermes:standalone-v1:{task_key}"
    configure_runner(objective, task_id)
    state.update({"objective": objective, "branch": branch, "parent_head": parent_head, "task_id": task_id, "status": "running", "pending_next": "governor"})
    atomic_json(STATE_PATH, state)
    scope_expected = exact_scope(objective, task_id)
    scope_wrapper = {"type": "object", "properties": {"control": control_schema(), "task_scope": task_scope_schema(task_id=task_id, objective=objective, read_scope=[TARGET], write_scope=[TARGET], parent_refs=PARENT_REFS, role="coder")}, "required": ["control", "task_scope"], "additionalProperties": False}
    governed, governor_manifest = run_model(f"worker:hermes-standalone-v1:{task_key}:governor-1", "governor", {"current_observer": PARENT_OBSERVER, "objective": objective, "required_scope": scope_expected}, scope_wrapper, 950)
    scope = validate_task_scope(governed["task_scope"], exact=scope_expected)
    scope_path = gov.action_dir(governor_manifest["action_id"]) / "task_scope.json"
    atomic_json(scope_path, scope)
    store = field_store()
    scope_ref = "IP_hermes_standalone_scope_" + sha256(scope_path.read_bytes())[:12]
    try:
        store.get_ip(scope_ref)
    except KeyError:
        store.add_ip(ref=scope_ref, content=f"Standalone TaskScope {task_id} sha256={sha256(scope_path.read_bytes())}", kind="TaskScopeIP", origin="runtime_reasoning", outcome="active", session_id=SESSION, metadata={"path": str(scope_path.relative_to(ROOT)).replace('\\', '/'), "sha256": sha256(scope_path.read_bytes())})
    try:
        governor_refs = record_worker("governor", governor_manifest["action_id"], governor_manifest, governed["control"], objective)
    except LocalDevelopmentError as exc:
        failure_ref = f"IP_hermes_standalone_governor_control_{task_key}"
        failure_content = f"Governor TaskScope validated but compact control failed: {exc}"
        _ensure_ip(store, ref=failure_ref, identity={"content": failure_content, "kind": "FailureIP", "metadata": {"action_id": governor_manifest["action_id"]}}, create={"content": failure_content, "kind": "FailureIP", "origin": "failure_history", "outcome": "failed", "failure_condition": str(exc), "session_id": SESSION, "metadata": {"action_id": governor_manifest["action_id"]}, "visible": True})
        governor_refs = {"result": failure_ref}
    state.update({"active_action": governor_manifest["action_id"], "closed_actions": [governor_manifest["action_id"]], "pending_next": "planner", "task_scope_ref": scope_ref})
    atomic_json(STATE_PATH, state)
    parent = (ROOT / TARGET).read_text(encoding="utf-8")
    parent_sha = sha256(parent.encode())
    planned, planner_manifest = run_model(f"worker:hermes-standalone-v1:{task_key}:planner-1", "planner", {"task_scope": scope, "source_tail": parent[-2200:], "instruction": "Plan only one concise appended section; do not implement."}, control_schema(), 550)
    planner_refs = record_worker("planner", planner_manifest["action_id"], planner_manifest, planned, objective)
    state["closed_actions"].append(planner_manifest["action_id"]); state["active_action"] = planner_manifest["action_id"]; state["pending_next"] = "coder"; atomic_json(STATE_PATH, state)
    defects: list[str] = []
    coder_refs = None
    candidate = None
    coder_manifest = None
    for attempt in range(1, 4):
        action_id = f"worker:hermes-standalone-v1:{task_key}:coder-{attempt}"
        prompt = {"task_scope": scope, "accepted_plan": planned, "source_tail": parent[-2200:], "artifact_contract": "Return 4-7 plain sentences, 55-240 chars each. Across them include Hermes, SToE Memory, TaskScope, restart, trusted, model. No Markdown, paths, hashes, test counts, or authority claims.", "prior_exact_defects": defects}
        try:
            coded, coder_manifest = run_model(action_id, "coder", prompt, patch_schema(parent_sha), 900)
        except Exception as exc:
            manifest_path = gov.action_dir(action_id) / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            exact_defect = manifest.get("failure") or str(exc)
            defects.append(exact_defect)
            failure_ref = f"IP_hermes_standalone_coder_{task_key}_{attempt:02d}"
            failure_content = f"Closed coder action failed before artifact validation: {exact_defect}"
            failure_metadata = {"action_id": action_id, "raw_sha256": manifest.get("raw_sha256")}
            _ensure_ip(store, ref=failure_ref, identity={"content": failure_content, "kind": "FailureIP", "metadata": failure_metadata}, create={"content": failure_content, "kind": "FailureIP", "origin": "failure_history", "outcome": "failed", "failure_condition": exact_defect, "session_id": SESSION, "metadata": failure_metadata, "visible": True})
            if manifest.get("model") and manifest.get("digest"):
                record_routing_evidence(model=manifest["model"], digest=manifest["digest"], role="coder", score=0.1, observation=f"Standalone sentence-table coder failed before validation: {exact_defect}")
            state["closed_actions"].append(action_id); state["active_action"] = action_id; state["pending_next"] = "coder_correction"; atomic_json(STATE_PATH, state)
            continue
        try:
            patch = validate_patch(coded["patch"], parent_sha)
            body = " ".join(sentence.strip() for sentence in patch["sentences"])
            candidate = parent.rstrip() + f"\n\n## {HEADING}\n\n" + body + "\n"
            candidate_path = gov.action_dir(action_id) / "candidate_README.md"
            candidate_path.write_text(candidate, encoding="utf-8", newline="\n")
            patch_path = gov.action_dir(action_id) / "candidate_patch.json"
            atomic_json(patch_path, patch)
            artifact = {"path": str(patch_path.relative_to(ROOT / "agent" / "runtime")).replace('\\', '/'), "sha256": sha256(patch_path.read_bytes()), "size_bytes": patch_path.stat().st_size}
            coder_refs = record_worker("coder", action_id, coder_manifest, coded["control"], objective, artifact)
            break
        except (ValueError, LocalDevelopmentError) as exc:
            defects.append(str(exc))
            failure_ref = f"IP_hermes_standalone_coder_{task_key}_{attempt:02d}"
            failure_content = f"Closed coder action failed deterministic validation: {exc}"
            failure_metadata = {"action_id": action_id, "raw_sha256": coder_manifest.get("raw_sha256")}
            _ensure_ip(store, ref=failure_ref, identity={"content": failure_content, "kind": "FailureIP", "metadata": failure_metadata}, create={"content": failure_content, "kind": "FailureIP", "origin": "failure_history", "outcome": "failed", "failure_condition": str(exc), "session_id": SESSION, "metadata": failure_metadata, "visible": True})
            state["closed_actions"].append(action_id); state["active_action"] = action_id; state["pending_next"] = "coder_correction"; atomic_json(STATE_PATH, state)
    if candidate is None or coder_refs is None or coder_manifest is None:
        state.update({"status": "failed", "pending_next": "successor_format_correction", "failure": f"coder recovery exhausted: {defects}"})
        atomic_json(STATE_PATH, state)
        failure_ref = f"IP_hermes_standalone_exhausted_{task_key}"
        failure_metadata = {"task_id": task_id, "closed_actions": state["closed_actions"]}
        _ensure_ip(store, ref=failure_ref, identity={"content": state["failure"], "kind": "FailureIP", "metadata": failure_metadata}, create={"content": state["failure"], "kind": "FailureIP", "origin": "failure_history", "outcome": "failed", "failure_condition": "; ".join(defects), "session_id": SESSION, "metadata": failure_metadata, "visible": True})
        for attempt in range(1, 4):
            _ensure_relation(store, source_ref=failure_ref, target_ref=f"IP_hermes_standalone_coder_{task_key}_{attempt:02d}", relation="summarizes", note="Recovery exhaustion conserves each exact closed coder defect.")
        raise RuntimeError(f"coder recovery exhausted: {defects}")
    state["closed_actions"].append(coder_manifest["action_id"]); state["active_action"] = coder_manifest["action_id"]; state["pending_next"] = "reviewer"; atomic_json(STATE_PATH, state)
    reviewed, reviewer_manifest = run_model(f"worker:hermes-standalone-v1:{task_key}:reviewer-1", "reviewer", {"task_scope": scope, "plan": planned, "candidate_append": candidate[len(parent.rstrip()):], "deterministic": {"identity": "passed", "grammar": "passed", "authority": "unchanged"}}, control_schema(), 600)
    reviewer_refs = record_worker("reviewer", reviewer_manifest["action_id"], reviewer_manifest, reviewed, objective)
    if reviewed["status"] != "success":
        raise RuntimeError("independent reviewer rejected candidate")
    state["closed_actions"].append(reviewer_manifest["action_id"]); state["active_action"] = reviewer_manifest["action_id"]; state["pending_next"] = "trusted_apply"; atomic_json(STATE_PATH, state)
    target = ROOT / TARGET
    if sha256(target.read_bytes()) != parent_sha:
        raise RuntimeError("stale parent before trusted apply")
    refs = {"governor": governor_refs, "planner": planner_refs, "coder": coder_refs, "reviewer": reviewer_refs}
    state.update({"worker_refs": refs, "candidate_path": str(candidate_path), "candidate_sha256": sha256(candidate.encode()), "parent_sha256": parent_sha})
    atomic_json(STATE_PATH, state)
    target.write_text(candidate, encoding="utf-8", newline="\n")
    state["applied"] = True; state["pending_next"] = "tests"; atomic_json(STATE_PATH, state)
    try:
        return finish_applied(state)
    except Exception:
        if git("rev-parse", "HEAD") == parent_head and target.exists():
            rollback_applied(state)
        raise


def status() -> dict:
    state = load_state()
    branch, head = branch_and_head()
    return {"observer": state["observer"], "objective": state["objective"], "active_or_closed_action": state["active_action"], "branch": branch, "HEAD": head, "pending_next": state["pending_next"], "status": state["status"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    develop_parser = commands.add_parser("develop")
    develop_parser.add_argument("--objective")
    args = parser.parse_args(argv)
    result = status() if args.command == "status" else develop(args.objective)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
