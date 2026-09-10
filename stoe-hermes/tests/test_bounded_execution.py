from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stoe-hermes" / "src"))

from stoe_hermes.bounded_execution import bounded_environment, run_bounded_preserved  # noqa: E402


class PreservedBoundedExecutionTests(unittest.TestCase):
    def run_case(self, root: Path, label: str, program: str, *, timeout: int = 10, output_limit: int = 4096):
        return run_bounded_preserved(
            [sys.executable, "-c", program], cwd=root, env=dict(os.environ),
            artifact_dir=root / "artifacts", label=label, timeout=timeout, output_limit=output_limit,
        )

    def test_stdout_and_stderr_are_preserved_and_attributed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = self.run_case(root, "both", "import sys;print('OUT');sys.stderr.write('ERR\\n')")
            self.assertTrue(result["passed"])
            self.assertEqual("OUT\n", Path(result["stdout"]["path"]).read_text())
            self.assertEqual("ERR\n", Path(result["stderr"]["path"]).read_text())
            self.assertFalse(result["output_truncated"])

    def test_output_resource_failure_is_capped_and_explicit(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = self.run_case(
                root, "capped", "import sys;sys.stdout.write('O'*20000);sys.stderr.write('E'*20000)", output_limit=512,
            )
            self.assertFalse(result["passed"])
            self.assertEqual("output", result["violation"])
            self.assertTrue(result["output_truncated"])
            self.assertLessEqual(result["preserved_output_bytes"], 512)
            self.assertGreater(result["stdout"]["original_bytes"], result["stdout"]["preserved_bytes"])
            self.assertGreater(result["stderr"]["original_bytes"], result["stderr"]["preserved_bytes"])

    def test_timeout_fails_closed_and_retains_prior_output(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = self.run_case(
                root, "timeout", "import time;print('BEFORE',flush=True);time.sleep(10)", timeout=1, output_limit=512,
            )
            self.assertFalse(result["passed"])
            self.assertEqual("timeout", result["violation"])
            self.assertIn("BEFORE", Path(result["stdout"]["path"]).read_text())
            self.assertLessEqual(result["preserved_output_bytes"], 512)

    def test_trusted_test_environment_includes_only_requested_tool_paths(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env, tools = bounded_environment(
                python_executable=sys.executable,
                pythonpath=ROOT / "stoe-hermes" / "src",
                temporary=root / "tmp",
                required_tools=("git",),
            )
            self.assertIn("git", tools)
            entries = env["PATH"].split(os.pathsep)
            self.assertEqual(str(Path(sys.executable).resolve().parent), entries[0])
            self.assertIn(str(Path(tools["git"]).parent), entries)
            self.assertLessEqual(len(entries), 2)


if __name__ == "__main__":
    unittest.main()
