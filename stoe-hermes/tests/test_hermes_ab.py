from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))
sys.path.insert(0, str(ROOT / "plugins" / "stoe-memory"))

from core import FieldStore  # noqa: E402
from stoe_hermes.context_renderer import render_retrieved_context  # noqa: E402
from stoe_hermes.plugin import SToEHermesAdapter, register  # noqa: E402
from stoe_hermes.succession import (  # noqa: E402
    EDITABLE_PATH,
    ReleaseRecord,
    SuccessionError,
    SuccessionSupervisor,
    create_isolated_profile,
    expose_integration_plugin,
    inspect_checkout,
    materialize_commit,
    reconstruct_candidate,
    run_bounded,
    sanitized_candidate_environment,
    sha256_bytes,
    validate_candidate_source,
    validate_patch_envelope,
    verify_clean_parent,
)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "body.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, "add", "body.py")
    git(repo, "commit", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


class FakeHermesContext:
    def __init__(self, store: FieldStore):
        self.store = store

    def call_mcp(self, server, tool, arguments, timeout=30):
        assert server == "stoe_memory" and timeout == 30
        mapping = {
            "stoe_field_status": self.store.status,
            "stoe_list_recent": self.store.list_recent,
            "stoe_set_observer_state": self.store.set_observer_state,
            "stoe_navigate": self.store.navigate,
            "stoe_add_ip": self.store.add_ip,
            "stoe_add_relation": self.store.add_relation,
        }
        return {"ok": True, "structuredContent": mapping[tool](**arguments)}


class RegistrationContext:
    def __init__(self):
        self.skills = []
        self.hooks = []
        self.tools = []

    def register_skill(self, *args, **kwargs):
        self.skills.append((args, kwargs))

    def register_hook(self, *args, **kwargs):
        self.hooks.append((args, kwargs))

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


class HermesABQualificationTests(unittest.TestCase):
    def test_fixture_candidate_creation_and_active_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo, commit = make_repo(root)
            before = hashlib.sha256((repo / "body.py").read_bytes()).hexdigest()
            result = materialize_commit(repo, commit, root / "candidate")
            self.assertEqual(commit, result["candidate_checkout"]["head_sha"])
            self.assertEqual(before, hashlib.sha256((repo / "body.py").read_bytes()).hexdigest())

    def test_clean_stale_and_dirty_parent_checks(self):
        with tempfile.TemporaryDirectory() as raw:
            repo, commit = make_repo(Path(raw))
            self.assertTrue(verify_clean_parent(repo, commit)["clean"])
            with self.assertRaisesRegex(SuccessionError, "stale"):
                verify_clean_parent(repo, "0" * 40)
            (repo / "body.py").write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(SuccessionError, "dirty"):
                verify_clean_parent(repo, commit)

    def test_divergent_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            seed, _ = make_repo(root)
            bare = root / "remote.git"
            git(root, "clone", "--bare", str(seed), str(bare))
            git(seed, "remote", "add", "origin", str(bare))
            git(seed, "push", "-u", "origin", "HEAD:main")
            git(seed, "branch", "--set-upstream-to=origin/main")
            (seed / "local.txt").write_text("local\n", encoding="utf-8")
            git(seed, "add", "local.txt")
            git(seed, "commit", "-m", "local")
            other = root / "other"
            git(root, "clone", str(bare), str(other))
            git(other, "config", "user.name", "fixture")
            git(other, "config", "user.email", "fixture@example.invalid")
            (other / "remote.txt").write_text("remote\n", encoding="utf-8")
            git(other, "add", "remote.txt")
            git(other, "commit", "-m", "remote")
            git(other, "push", "origin", "HEAD:main")
            git(seed, "fetch", "origin")
            state = inspect_checkout(seed)
            self.assertEqual("divergent", state["upstream_relation"])
            with self.assertRaisesRegex(SuccessionError, "divergent"):
                verify_clean_parent(seed, state["head_sha"])

    def test_allowlisted_patch_and_capability_rejections(self):
        parent_path = ROOT / EDITABLE_PATH
        parent = parent_path.read_text(encoding="utf-8")
        parent_hash = sha256_bytes(parent.encode("utf-8"))
        patch = {
            "format": "stoe.line_patch",
            "version": 3,
            "path": EDITABLE_PATH,
            "parent_sha256": parent_hash,
            "replacement_lines": [
                "def render_retrieved_context(items, max_chars):",
                "    return str(len(items))[:max_chars]",
            ],
        }
        validate_patch_envelope(patch, parent_sha256=parent_hash)
        candidate = reconstruct_candidate(parent, patch)
        self.assertEqual(64, len(validate_candidate_source(parent, candidate)["candidate_sha256"]))
        for path in ("../escape.py", "stoe-hermes/src/stoe_hermes/succession.py", "requirements.txt"):
            attack = dict(patch, path=path)
            with self.assertRaises(SuccessionError):
                validate_patch_envelope(attack, parent_sha256=parent_hash)
        authority = dict(patch, replacement_lines=[
            "def render_retrieved_context(items, max_chars):",
            "    return open('active_release.json').read()",
        ])
        with self.assertRaisesRegex(SuccessionError, "capability"):
            validate_candidate_source(parent, reconstruct_candidate(parent, authority))
        leaked = dict(patch, replacement_lines=[
            "def render_retrieved_context(items, max_chars):",
            "    api_key = 'sk_abcdefghijklmnopqrstuvwxyz'",
            "    return api_key",
        ])
        with self.assertRaisesRegex(SuccessionError, "secret"):
            validate_candidate_source(parent, reconstruct_candidate(parent, leaked))

    def test_isolated_profile_has_no_credentials_or_gateways(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile = create_isolated_profile(
                root / "profile",
                candidate_cwd=root / "candidate",
                python_command=sys.executable,
                mcp_server=ROOT / "plugins" / "stoe-memory" / "server.py",
                skill_dir=ROOT,
            )
            config = (root / "profile" / "config.yaml").read_text(encoding="utf-8")
            self.assertFalse(profile["credentials_present"])
            self.assertIn("enabled: false", config)
            self.assertNotIn("api_key", config.lower())
            loader = expose_integration_plugin(root / "profile", ROOT / "stoe-hermes")
            self.assertTrue(Path(loader["loader_path"]).is_dir())
            env = sanitized_candidate_environment(root / "profile", root / "venv")
            for key in os.environ:
                if any(word in key.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
                    self.assertNotIn(key, env)

    def test_exact_hermes_registration_surface_and_external_skill(self):
        with tempfile.TemporaryDirectory() as raw:
            skill = Path(raw) / "canonical-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text("canonical\n", encoding="utf-8")
            previous = os.environ.get("STOE_REASONING_SKILL_DIR")
            os.environ["STOE_REASONING_SKILL_DIR"] = str(skill.resolve())
            try:
                ctx = RegistrationContext()
                register(ctx)
            finally:
                if previous is None:
                    os.environ.pop("STOE_REASONING_SKILL_DIR", None)
                else:
                    os.environ["STOE_REASONING_SKILL_DIR"] = previous
            self.assertEqual(["on_session_start", "pre_llm_call", "on_session_end"], [item[0][0] for item in ctx.hooks])
            self.assertEqual(["stoe_retrieve", "stoe_conserve"], [item["name"] for item in ctx.tools])
            self.assertEqual(skill.resolve(), ctx.skills[0][0][1])

    def test_interrupted_build_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo, commit = make_repo(root)
            destination = root / "candidate"
            destination.mkdir()
            (destination / "partial").write_text("interrupted", encoding="utf-8")
            with self.assertRaisesRegex(SuccessionError, "already exists"):
                materialize_commit(repo, commit, destination)

    def test_launch_failure_crash_and_timeout_are_bounded(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env = dict(os.environ)
            crash = run_bounded([sys.executable, "-c", "raise SystemExit(7)"], cwd=root, env=env)
            self.assertFalse(crash["passed"])
            self.assertEqual(7, crash["returncode"])
            missing = run_bounded([sys.executable, "-c", "raise RuntimeError('launch')"], cwd=root, env=env)
            self.assertFalse(missing["passed"])
            timeout = run_bounded([sys.executable, "-c", "while True: pass"], cwd=root, env=env, timeout=1)
            self.assertEqual("timeout", timeout["violation"])

    def test_approval_atomic_switch_and_failed_health_rollback(self):
        with tempfile.TemporaryDirectory() as raw:
            pointer = Path(raw) / "active.json"
            pointer.write_text('{"release_id":"A","environment_fingerprint":"a"}\n', encoding="utf-8")
            record = ReleaseRecord(
                release_id="B", source_repository="fixture", commit_sha="b" * 40,
                parent_release="A", hermes_version="0.20.3", integration_plugin_version="0.1.0",
                model_configuration={"model": "gemma4:26b"}, configuration_hash="c" * 64,
                environment_fingerprint="d" * 64, candidate_status="approved",
            )
            supervisor = SuccessionSupervisor(pointer)
            with self.assertRaisesRegex(SuccessionError, "approval"):
                supervisor.activate(record, approval="wrong", requested_by="Mykola Voronin", health_check=lambda: True)
            result = supervisor.activate(record, approval=supervisor.approval_token(record), requested_by="Mykola Voronin", health_check=lambda: False)
            self.assertEqual("rolled_back", result["status"])
            self.assertEqual("A", supervisor.read_pointer()["release_id"])
            result = supervisor.activate(record, approval=supervisor.approval_token(record), requested_by="Mykola Voronin", health_check=lambda: True)
            self.assertEqual("active", result["status"])
            self.assertEqual("B", supervisor.read_pointer()["release_id"])

    def test_activation_blocker_cannot_be_overridden_by_approval(self):
        with tempfile.TemporaryDirectory() as raw:
            pointer = Path(raw) / "active.json"
            pointer.write_text('{"release_id":"A"}\n', encoding="utf-8")
            record = ReleaseRecord(
                release_id="B", source_repository="fixture", commit_sha="b" * 40,
                parent_release="A", hermes_version="0.20.3", integration_plugin_version="0.1.0",
                model_configuration={}, configuration_hash="c" * 64, environment_fingerprint="d" * 64,
                candidate_status="approved", activation_blockers=["active_source_dirty"],
            )
            supervisor = SuccessionSupervisor(pointer)
            with self.assertRaisesRegex(SuccessionError, "blocked"):
                supervisor.activate(record, approval=supervisor.approval_token(record), requested_by="Mykola Voronin", health_check=lambda: True)

    def test_stoe_memory_survives_fresh_hermes_adapter_session(self):
        with tempfile.TemporaryDirectory() as raw:
            store = FieldStore(Path(raw) / "field.sqlite3")
            store.initialize()
            first = SToEHermesAdapter(FakeHermesContext(store))
            first.on_session_start(session_id="one")
            conserved = json.loads(first.conserve({"session_id": "one", "kind": "DecisionIP", "outcome": "supported", "content": "preserve this exact decision"}))
            first.on_session_end(session_id="one", completed=True, interrupted=False, model="fixture")
            second = SToEHermesAdapter(FakeHermesContext(store))
            second.on_session_start(session_id="two")
            retrieved = second.retrieve({"session_id": "two", "limit": 12})
            self.assertIn("preserve this exact decision", retrieved)
            self.assertTrue(store.get_ip(conserved["ref"])["edges"])

    def test_duplicate_payload_is_rendered_once_and_all_connections_survive(self):
        content = "canonical payload"
        digest = hashlib.sha256(content.encode()).hexdigest()
        items = [
            {"sha256": digest, "content": content, "ref": "A", "relation": "evaluates", "direction": "outgoing", "provenance": "test-1"},
            {"sha256": digest, "content": content, "ref": "B", "relation": "correction_of", "direction": "incoming", "provenance": "test-2"},
        ]
        rendered = render_retrieved_context(items, 4000)
        self.assertEqual(1, rendered.count("PAYLOAD |"))
        self.assertEqual(2, rendered.count("CONNECTION |"))
        self.assertIn("collapsed=1", rendered)
        self.assertIn("evaluates", rendered)
        self.assertIn("correction_of", rendered)


if __name__ == "__main__":
    unittest.main()
