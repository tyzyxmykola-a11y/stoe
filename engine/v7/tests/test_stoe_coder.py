import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import shutil
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stoe_coder import FullLocalRunner, OllamaWorker, StoeCoderRuntime, _git, _ollama_schema, _validate_bounds


class FakeOllama:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def models(self):
        return [{"name": "local-test", "digest": "d" * 64, "size": 1}]

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        return reply, {"action_id": kwargs["action_id"], "model": "local-test", "digest": "d" * 64,
                       "prompt_tokens": 10, "output_tokens": 5, "prompt_chars": 10,
                       "output_chars": 5, "artifact_bytes": 1, "duration_seconds": .01,
                       "raw_sha256": "a" * 64, "result_path": "fake"}


def action(kind, **values):
    result = {"kind": kind, "path": "", "destination": "", "query": "", "content": "",
              "command": [], "cwd": ".", "summary": ""}
    result.update(values)
    return result


class StoeCoderTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ.get("STOE_TEST_SCRATCH", Path(__file__).resolve().parents[3] / "agent" / "runtime" / "stoe_coder_tests"))
        scratch.mkdir(parents=True, exist_ok=True)
        self.test_root = scratch / uuid.uuid4().hex
        self.test_root.mkdir()
        self.repo = self.test_root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        (self.repo / "sample.py").write_text("def value():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "branch", "-M", "feature/test"], cwd=self.repo, check=True)
        self.runtime_root = self.test_root / "runtime"

    def tearDown(self):
        shutil.rmtree(self.test_root, ignore_errors=True)

    def runtime(self, replies=None):
        return StoeCoderRuntime(self.repo, ollama=FakeOllama(replies or []), runtime_root=self.runtime_root)

    def qualify(self, runtime, *, clean=False, status="completed"):
        snapshot = runtime._git_snapshot()
        fingerprint = None if clean else runtime._working_fingerprint()
        state = runtime._load_state()
        state.update({
            "status": status, "tests": "passed", "tests_head": snapshot["head"] if clean else None,
            "tests_fingerprint": fingerprint, "review_status": "accepted",
            "review_head": snapshot["head"] if clean else None, "review_fingerprint": fingerprint,
            "reviewed_paths": snapshot["changed_paths"] if not clean else ["sample.py"],
        })
        runtime._save_state(state)

    def add_remote(self):
        subprocess.run(["git", "branch", "main"], cwd=self.repo, check=True, capture_output=True)
        remote = self.test_root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=self.repo, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "--set-upstream", "origin", "feature/test"], cwd=self.repo, check=True, capture_output=True)
        return remote

    def remote_writer(self, remote):
        other = self.test_root / ("other-" + uuid.uuid4().hex)
        subprocess.run(["git", "clone", "--branch", "feature/test", str(remote), str(other)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "other@example.invalid"], cwd=other, check=True)
        subprocess.run(["git", "config", "user.name", "Other"], cwd=other, check=True)
        return other

    def test_chat_cannot_mutate_repository(self):
        worker = FakeOllama([{"answer": "State is clean."}])
        runtime = StoeCoderRuntime(self.repo, ollama=worker, runtime_root=self.runtime_root)
        before = _git(self.repo, "status", "--porcelain=v1").stdout
        self.assertFalse(runtime.chat("status?")["mutated"])
        self.assertEqual(before, _git(self.repo, "status", "--porcelain=v1").stdout)

    def test_tool_loop_changes_isolated_candidate_and_integrates_after_review(self):
        source = "def value():\n    return 2\n"
        worker = FakeOllama([
            action("inspect", path="sample.py"),
            action("write", path="sample.py", content=source),
            action("run", command=[sys.executable, "-c", "compile(open('sample.py', encoding='utf-8').read(), 'sample.py', 'exec')"]),
            action("finish", summary="changed and checked"),
            {"verdict": "accept", "summary": "bounded change", "defects": []},
        ])
        runtime = StoeCoderRuntime(self.repo, ollama=worker, runtime_root=self.runtime_root)
        accepted = runtime.submit_task("Change value to two", allowed_paths=["sample.py"])
        deadline = time.time() + 15
        while time.time() < deadline and runtime.status()["status"] not in {"completed", "failed"}:
            time.sleep(.05)
        self.assertEqual("completed", runtime.status()["status"], runtime.status().get("last_result"))
        self.assertEqual(source, (self.repo / "sample.py").read_text(encoding="utf-8"))
        self.assertTrue(accepted["task_id"].startswith("TASK_"))

    def test_trusted_integration_accounts_for_new_untracked_file(self):
        runtime = StoeCoderRuntime(self.repo, ollama=FakeOllama([]), runtime_root=self.runtime_root)
        candidate = self.test_root / "candidate"
        candidate.mkdir()
        (candidate / "new.py").write_text("VALUE = 1\n", encoding="utf-8")
        runtime._integrate("TASK_new", _git(self.repo, "rev-parse", "HEAD").stdout.strip(), candidate, ["new.py"])
        self.assertTrue((self.repo / "new.py").is_file())

    def test_resume_gets_linked_new_identity(self):
        first = StoeCoderRuntime.task_identity("x", "h", "s")
        second = StoeCoderRuntime.task_identity("x", "h", "s", first)
        self.assertNotEqual(first, second)

    def test_unsupported_grammar_bounds_are_enforced_after_parse(self):
        schema = {"type": "object", "properties": {"x": {"type": "string", "maxLength": 2}}}
        self.assertNotIn("maxLength", _ollama_schema(schema)["properties"]["x"])
        with self.assertRaises(ValueError):
            _validate_bounds({"x": "too long"}, schema)

    def test_repeated_length_failures_route_away_from_model(self):
        root = self.runtime_root / "routing"
        for index in range(2):
            path = root / str(index)
            path.mkdir(parents=True)
            (path / "raw_response.json").write_text(json.dumps({"model": "qwen3-coder:latest", "done_reason": "length"}), encoding="utf-8")
        worker = OllamaWorker(artifact_root=root)
        worker.models = lambda: [
            {"name": "qwen3-coder:latest", "digest": "q", "size": 20},
            {"name": "gemma4:26b", "digest": "g", "size": 19},
        ]
        self.assertEqual("gemma4:26b", worker.choose("coder")[0])

    def test_tool_budget_exhaustion_routes_away_from_model(self):
        root = self.runtime_root / "exhausted" / "artifacts"
        root.mkdir(parents=True)
        (root.parent / "state.json").write_text(json.dumps({"last_result": {"error": "local worker exhausted tool-step budget", "metrics": [{"model": "qwen3-coder:latest"}]}}), encoding="utf-8")
        worker = OllamaWorker(artifact_root=root)
        worker.models = lambda: [
            {"name": "qwen3-coder:latest", "digest": "q", "size": 20},
            {"name": "gemma4:26b", "digest": "g", "size": 19},
        ]
        self.assertEqual("gemma4:26b", worker.choose("coder")[0])

    def test_runner_preserves_bounded_output_and_denies_destructive_git(self):
        runner = FullLocalRunner(self.runtime_root / "commands")
        result = runner.run(action_id="output", command=[sys.executable, "-c", "print('ok')"], cwd=self.repo)
        self.assertEqual(0, result.exit_code)
        self.assertIn("ok", result.stdout)
        self.assertTrue(Path(result.stdout_artifact).is_file())
        missing = runner.run(action_id="missing", command=["definitely-not-a-real-command"], cwd=self.repo)
        self.assertEqual(-1, missing.exit_code)
        self.assertIn("command launch failed", missing.stderr)
        with self.assertRaises(PermissionError):
            runner.run(action_id="bad", command=["git", "reset", "--hard"], cwd=self.repo)

    def test_missing_run_command_is_worker_feedback_not_task_abort(self):
        runtime = StoeCoderRuntime(self.repo, ollama=FakeOllama([]), runtime_root=self.runtime_root)
        feedback = runtime._execute_tool("TASK_test", 1, self.repo, action("run"), None)
        self.assertFalse(feedback["ok"])
        self.assertIn("non-empty", feedback["error"])
        script = self.repo / "check.py"
        script.write_text("print('checked')\n", encoding="utf-8")
        feedback = runtime._execute_tool("TASK_test", 2, self.repo, action("run", path="check.py"), None)
        self.assertTrue(feedback["exit_code"] == 0)

    def test_navigator_exposes_coder_routes_and_rejects_remote_clients(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("Flask dependency is not installed in this test environment")
        import server
        rules = {rule.rule for rule in server.app.url_map.iter_rules()}
        self.assertIn("/api/coder/task", rules)
        self.assertIn("/api/coder/chat", rules)
        for route in ("/api/coder/git/diff", "/api/coder/git/commit", "/api/coder/git/pull", "/api/coder/git/push", "/api/coder/git/merge"):
            self.assertIn(route, rules)
        self.assertNotIn("/api/shell", rules)
        response = server.app.test_client().get("/api/coder/status", environ_base={"REMOTE_ADDR": "192.0.2.10"})
        self.assertEqual(403, response.status_code)

    def test_objective_words_do_not_grant_model_git_authority(self):
        runtime = self.runtime()
        with mock.patch.object(runtime, "_task_main", return_value=None) as task_main:
            runtime.submit_task("commit and push this change")
            runtime._thread.join(2)
        options = runtime._load_state()["task_options"]
        self.assertFalse(options["allow_commit"])
        self.assertFalse(options["allow_push"])
        self.assertFalse(task_main.call_args.args[2])
        self.assertFalse(task_main.call_args.args[3])

    def test_explicit_run_controls_preserve_model_commit_capability(self):
        source = "def value():\n    return 2\n"
        runtime = self.runtime([
            action("inspect", path="sample.py"), action("write", path="sample.py", content=source),
            action("run", command=[sys.executable, "-c", "compile(open('sample.py', encoding='utf-8').read(), 'sample.py', 'exec')"]),
            action("finish", summary="changed and checked"),
            {"verdict": "accept", "summary": "bounded change", "defects": []},
        ])
        parent = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        runtime.submit_task("Change value", allow_commit=True, allowed_paths=["sample.py"])
        deadline = time.time() + 15
        while time.time() < deadline and runtime.status()["status"] not in {"completed", "failed"}:
            time.sleep(.05)
        state = runtime.status()
        self.assertEqual("completed", state["status"], state.get("last_result"))
        self.assertNotEqual(parent, state["head"])
        self.assertTrue(state["clean"])

    def test_explicit_run_push_control_preserves_model_feature_push(self):
        self.add_remote()
        source = "def value():\n    return 4\n"
        runtime = self.runtime([
            action("inspect", path="sample.py"), action("write", path="sample.py", content=source),
            action("run", command=[sys.executable, "-c", "compile(open('sample.py', encoding='utf-8').read(), 'sample.py', 'exec')"]),
            action("finish", summary="changed and checked"),
            {"verdict": "accept", "summary": "bounded change", "defects": []},
        ])
        runtime.submit_task("Change value", allow_push=True, allowed_paths=["sample.py"])
        deadline = time.time() + 15
        while time.time() < deadline and runtime.status()["status"] not in {"completed", "failed"}:
            time.sleep(.05)
        state = runtime.status()
        self.assertEqual("completed", state["status"], state.get("last_result"))
        self.assertEqual(state["head"], _git(self.repo, "rev-parse", "origin/feature/test").stdout.strip())

    def test_dirty_tree_blocks_run_but_not_diff_or_qualified_commit(self):
        runtime = self.runtime()
        (self.repo / "sample.py").write_text("def value():\n    return 2\n", encoding="utf-8")
        before_head = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        with self.assertRaisesRegex(RuntimeError, "clean"):
            runtime.submit_task("another run")
        viewed = runtime.git_diff()
        self.assertIn("return 2", viewed["diff"])
        self.assertEqual(before_head, _git(self.repo, "rev-parse", "HEAD").stdout.strip())
        self.assertFalse(viewed["clean"])
        self.qualify(runtime)
        committed = runtime.git_commit("Operator accepts candidate")
        self.assertNotEqual(before_head, committed["commit"])
        self.assertTrue(committed["clean"])

    def test_commit_rejects_unreviewed_or_empty_tree_and_bad_message(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(RuntimeError, "nothing"):
            runtime.git_commit("No change")
        (self.repo / "sample.py").write_text("def value():\n    return 3\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "tested and reviewed"):
            runtime.git_commit("Not qualified")
        self.qualify(runtime)
        with self.assertRaisesRegex(ValueError, "single line"):
            runtime.git_commit("bad\nmessage")
        (self.repo / "sample.py").write_text("def value():\n    return 5\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "tested and reviewed"):
            runtime.git_commit("Stale qualification")

    def test_pull_is_ff_only_and_rejects_dirty_or_diverged_state(self):
        remote = self.add_remote()
        runtime = self.runtime()
        other = self.remote_writer(remote)
        (other / "remote.txt").write_text("remote\n", encoding="utf-8")
        subprocess.run(["git", "add", "remote.txt"], cwd=other, check=True)
        subprocess.run(["git", "commit", "-m", "remote"], cwd=other, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=other, check=True, capture_output=True)
        self.assertEqual("succeeded", runtime.git_pull()["outcome"])
        self.assertTrue((self.repo / "remote.txt").is_file())
        (self.repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "clean"):
            runtime.git_pull()
        (self.repo / "dirty.txt").unlink()
        (self.repo / "local.txt").write_text("local\n", encoding="utf-8")
        subprocess.run(["git", "add", "local.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "local"], cwd=self.repo, check=True, capture_output=True)
        (other / "remote2.txt").write_text("remote2\n", encoding="utf-8")
        subprocess.run(["git", "add", "remote2.txt"], cwd=other, check=True)
        subprocess.run(["git", "commit", "-m", "remote2"], cwd=other, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=other, check=True, capture_output=True)
        with self.assertRaises(RuntimeError):
            runtime.git_pull()
        self.assertEqual("local", (self.repo / "local.txt").read_text(encoding="utf-8").strip())

    def test_push_is_feature_only_and_confirms_remote_identity(self):
        self.add_remote()
        runtime = self.runtime()
        (self.repo / "feature.txt").write_text("feature\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "feature"], cwd=self.repo, check=True, capture_output=True)
        pushed = runtime.git_push()
        self.assertTrue(pushed["head_pushed"])
        subprocess.run(["git", "checkout", "main"], cwd=self.repo, check=True, capture_output=True)
        with self.assertRaisesRegex(PermissionError, "refuses main"):
            runtime.git_push()

    def test_merge_to_main_requires_exact_qualified_pushed_lineage(self):
        self.add_remote()
        runtime = self.runtime()
        (self.repo / "feature.txt").write_text("feature\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "feature"], cwd=self.repo, check=True, capture_output=True)
        feature_head = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.qualify(runtime, clean=True)
        with self.assertRaisesRegex(RuntimeError, "not confirmed"):
            runtime.git_merge()
        runtime.git_push()
        self.qualify(runtime, clean=True)
        merged = runtime.git_merge()
        self.assertEqual(feature_head, merged["feature_head"])
        self.assertEqual(0, _git(self.repo, "merge-base", "--is-ancestor", feature_head, "main", check=False).returncode)
        self.assertEqual("feature/test", _git(self.repo, "branch", "--show-current").stdout.strip())
        self.assertNotEqual(merged["main_head"], _git(self.repo, "rev-parse", "origin/main").stdout.strip())

    def test_merge_rejects_stale_tests_review_and_unresolved_failure(self):
        self.add_remote()
        runtime = self.runtime()
        with self.assertRaisesRegex(RuntimeError, "passed tests"):
            runtime.git_merge()
        self.qualify(runtime, clean=True, status="failed")
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            runtime.git_merge()

    def test_git_status_exposes_branch_sync_and_validity(self):
        self.add_remote()
        runtime = self.runtime()
        status = runtime.status()
        for key in ("branch", "head", "ahead", "behind", "dirty_count", "tests_status", "reviewed_candidate_status", "head_pushed"):
            self.assertIn(key, status)
        self.assertEqual("feature/test", status["branch"])
        self.assertTrue(status["head_pushed"])

    def test_changed_path_identity_handles_spaces_without_porcelain_quoting(self):
        runtime = self.runtime()
        target = self.repo / "file with spaces.txt"
        target.write_text("content\n", encoding="utf-8")
        self.assertEqual(["file with spaces.txt"], runtime._changed_paths())
        viewed = runtime.git_diff()
        self.assertIn("file with spaces.txt", viewed["diff"])

    def test_failed_git_action_records_exact_condition(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(RuntimeError, "nothing to commit"):
            runtime.git_commit("Empty")
        events = runtime.events()
        failed = [item for item in events if item["source"] == "Git" and item["metadata"].get("outcome") == "failed"]
        self.assertTrue(failed)
        self.assertIn("nothing to commit", failed[-1]["message"])


if __name__ == "__main__":
    unittest.main()
