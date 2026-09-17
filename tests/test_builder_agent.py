import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from builder_agent import validate_write_path


class BuilderSecurityTests(unittest.TestCase):

    def test_normal_path_allowed(self):
        self.assertEqual(
            validate_write_path(
                "docs/report.md"
            ),
            "docs/report.md",
        )

    def test_traversal_blocked(self):
        with self.assertRaises(
            PermissionError
        ):
            validate_write_path(
                "../../escape.py"
            )

    def test_git_blocked(self):
        with self.assertRaises(
            PermissionError
        ):
            validate_write_path(
                ".git/config"
            )

    def test_env_blocked(self):
        with self.assertRaises(
            PermissionError
        ):
            validate_write_path(
                ".env"
            )

    def test_binary_blocked(self):
        with self.assertRaises(
            PermissionError
        ):
            validate_write_path(
                "payload.exe"
            )


if __name__ == "__main__":
    unittest.main()
