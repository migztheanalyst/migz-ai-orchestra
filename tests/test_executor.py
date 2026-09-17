import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from safe_executor import is_allowed


class SafeExecutorTests(unittest.TestCase):

    def test_git_status_allowed(self):
        self.assertTrue(
            is_allowed(["git", "status"])
        )

    def test_exact_compileall_allowed(self):
        self.assertTrue(
            is_allowed([
                "python3",
                "-m",
                "compileall",
                "-q",
                "conductor",
                "tests",
            ])
        )

    def test_compileall_escape_blocked(self):
        self.assertFalse(
            is_allowed([
                "python3",
                "-m",
                "compileall",
                "../../",
            ])
        )

    def test_arbitrary_python_module_blocked(self):
        self.assertFalse(
            is_allowed([
                "python3",
                "-m",
                "http.server",
            ])
        )

    def test_rm_blocked(self):
        self.assertFalse(
            is_allowed([
                "rm",
                "-rf",
                "tests",
            ])
        )

    def test_npm_not_allowed_on_host(self):
        self.assertFalse(
            is_allowed([
                "npm",
                "run",
                "build",
            ])
        )


if __name__ == "__main__":
    unittest.main()
