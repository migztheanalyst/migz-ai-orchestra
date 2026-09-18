import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackageImportTests(unittest.TestCase):
    def test_core_modules_import_in_fresh_process(self):
        modules = [
            "conductor.project_registry",
            "conductor.project_scheduler",
            "conductor.project_orchestrator",
            "conductor.evidence_manager",
            "conductor.worktree_manager",
            "conductor.provider_router",
            "conductor.runtime_env",
            "conductor.backend_change_guard",
            "conductor.release_reviewer",
            "conductor.safe_executor",
            "conductor.tester_agent",
        ]
        code = "; ".join(f"import {name}" for name in modules)
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env={},
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
