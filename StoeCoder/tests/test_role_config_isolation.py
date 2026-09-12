import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from role_config_isolation import install_role_config_isolation
from roles import RoleRegistry


class DummyOllama:
    def models(self):
        return [{"name": "local-test", "digest": "d" * 64, "size": 1}]


class DummyCoder:
    def __init__(self, repo_root: Path, runtime_root: Path):
        self.repo_root = repo_root
        self.runtime_root = runtime_root
        self.ollama = DummyOllama()
        self.events = []
        self.calls = []
        self.roles = RoleRegistry(repo_root / "StoeCoder" / "roles.json", self.ollama.models, self._role_transition)
        self.roles.initialize()

    def _role_transition(self, action, before, after):
        self.events.append((action, before, after))

    def _execute_tool(self, task_id, step, worktree, request, allowed_paths):
        self.calls.append((task_id, step, dict(request)))
        return {"ok": True, "kind": request.get("kind")}


class RoleConfigIsolationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        config = self.repo / "StoeCoder"
        config.mkdir()
        RoleRegistry(config / "roles.json", DummyOllama().models, lambda *args: None).initialize()
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=self.repo, check=True, capture_output=True)
        self.runtime = self.root / "runtime"

    def _manual_coder(self, registry: RoleRegistry):
        role = next(item for item in registry.load()["roles"] if item["name"] == "coder")
        role = dict(role)
        role.update({"model_mode": "manual", "model": "local-test"})
        registry.save(role, "coder")

    def test_runtime_role_changes_do_not_dirty_repository(self):
        legacy = self.repo / "StoeCoder" / "roles.json"
        baseline = legacy.read_bytes()
        coder = DummyCoder(self.repo, self.runtime)
        install_role_config_isolation(coder)

        self._manual_coder(coder.roles)

        self.assertEqual(self.runtime / "roles.json", coder.roles.path)
        self.assertEqual(baseline, legacy.read_bytes())
        status = subprocess.run(
            ["git", "status", "--porcelain=v1"], cwd=self.repo,
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual("", status)

    def test_existing_legacy_role_choice_seeds_runtime_once(self):
        legacy_registry = RoleRegistry(
            self.repo / "StoeCoder" / "roles.json", DummyOllama().models, lambda *args: None,
        )
        self._manual_coder(legacy_registry)
        legacy_bytes = legacy_registry.path.read_bytes()

        coder = DummyCoder(self.repo, self.runtime)
        install_role_config_isolation(coder)

        selected = next(item for item in coder.roles.load()["roles"] if item["name"] == "coder")
        self.assertEqual("manual", selected["model_mode"])
        self.assertEqual("local-test", selected["model"])
        self.assertEqual(legacy_bytes, legacy_registry.path.read_bytes())

    def test_candidate_runtime_registry_copy_is_restored_to_head_before_worker_action(self):
        coder = DummyCoder(self.repo, self.runtime)
        install_role_config_isolation(coder)
        self._manual_coder(coder.roles)

        candidate = self.root / "candidate"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(candidate), "HEAD"],
            cwd=self.repo, check=True, capture_output=True,
        )
        try:
            target = candidate / "StoeCoder" / "roles.json"
            target.write_text(coder.roles.path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
            dirty_before = subprocess.run(
                ["git", "diff", "--name-only"], cwd=candidate,
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertIn("StoeCoder/roles.json", dirty_before)

            coder._execute_tool("TASK_x", 1, candidate, {"kind": "inspect", "path": "README.md"}, None)

            dirty_after = subprocess.run(
                ["git", "diff", "--name-only"], cwd=candidate,
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertNotIn("StoeCoder/roles.json", dirty_after)
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(candidate)],
                cwd=self.repo, check=False, capture_output=True,
            )


if __name__ == "__main__":
    unittest.main()
