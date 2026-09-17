import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from model_router import route_model
from safe_writer import safe_write


class ModelRouterTests(unittest.TestCase):

    def test_fast_route(self):
        self.assertEqual(
            route_model("fast"),
            "qwen2.5-coder:3b"
        )

    def test_coding_route(self):
        self.assertEqual(
            route_model("coding"),
            "qwen2.5-coder:7b"
        )

    def test_reasoning_route(self):
        self.assertEqual(
            route_model("reasoning"),
            "qwen3.5:4b"
        )

    def test_unknown_role_blocked(self):
        with self.assertRaises(ValueError):
            route_model("unknown-role")


class SafeWriterTests(unittest.TestCase):

    def test_write_inside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            safe_write(
                tmp,
                "sample.txt",
                "SAFE"
            )

            target = Path(tmp) / "sample.txt"

            self.assertTrue(target.exists())
            self.assertEqual(
                target.read_text(),
                "SAFE"
            )

    def test_escape_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PermissionError):
                safe_write(
                    tmp,
                    "../../escape.txt",
                    "BAD"
                )

    def test_env_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PermissionError):
                safe_write(
                    tmp,
                    ".env",
                    "SECRET"
                )


if __name__ == "__main__":
    unittest.main()
