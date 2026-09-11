import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verification_policy import (
    final_verification_commands,
    install_verification_policy,
    verification_plan,
    worker_verification_commands,
)


class DummyCoder:
    def _verification_commands(self, touched):
        return [["legacy"]]


class VerificationPolicyTests(unittest.TestCase):
    def test_stoecoder_plan_is_single_source_for_worker_and_final_verifier(self):
        worker = worker_verification_commands(["StoeCoder/README.md"], python_executable="PYTHON")
        final = final_verification_commands(["StoeCoder/README.md"], python_executable="PYTHON")
        self.assertEqual(
            [["PYTHON", "-m", "unittest", "discover", "-s", "StoeCoder/tests", "-q"]],
            worker,
        )
        self.assertEqual(
            [
                ["git", "diff", "--check"],
                ["PYTHON", "-m", "unittest", "discover", "-s", "StoeCoder/tests", "-q"],
            ],
            final,
        )

    def test_multi_project_plan_has_stable_rule_order(self):
        plan = verification_plan(
            ["stoe-hermes/adapter.py", "agent/runtime.py", "StoeCoder/server.py"],
            python_executable="PY",
        )
        self.assertEqual(
            ["diff-check", "stoecoder-tests", "agent-tests", "stoe-hermes-tests"],
            [step.key for step in plan],
        )

    def test_unknown_path_needs_no_worker_suite_but_keeps_final_diff_check(self):
        self.assertEqual([], worker_verification_commands(["README.md"], python_executable="PY"))
        self.assertEqual([["git", "diff", "--check"]], final_verification_commands(["README.md"], python_executable="PY"))

    def test_runtime_installer_routes_core_verifier_through_policy(self):
        coder = DummyCoder()
        install_verification_policy(coder)
        self.assertEqual(
            final_verification_commands(["StoeCoder/server.py"]),
            coder._verification_commands(["StoeCoder/server.py"]),
        )
        self.assertEqual(sys.executable, coder._verification_commands(["StoeCoder/server.py"])[1][0])


if __name__ == "__main__":
    unittest.main()
