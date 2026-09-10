import json
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import shutil
from pathlib import Path

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
        scratch = Path(__file__).resolve().parents[3] / "agent" / "runtime" / "stoe_coder_tests"
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

    def test_navigator_exposes_coder_routes_and_rejects_remote_clients(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("Flask dependency is not installed in this test environment")
        import server
        rules = {rule.rule for rule in server.app.url_map.iter_rules()}
        self.assertIn("/api/coder/task", rules)
        self.assertIn("/api/coder/chat", rules)
        self.assertNotIn("/api/shell", rules)
        response = server.app.test_client().get("/api/coder/status", environ_base={"REMOTE_ADDR": "192.0.2.10"})
        self.assertEqual(403, response.status_code)


if __name__ == "__main__":
    unittest.main()
