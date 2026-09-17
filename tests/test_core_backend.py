import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from agent_backend_router import AgentBackendRouter, BackendPlan, BackendUnavailable
from backend_change_guard import inspect_changes
from model_router import route_healthy_model
from provider_router import classify_backend_failure


def init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=10)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=path, check=True, timeout=10)
    subprocess.run(["git", "config", "user.name", "MIGZ Tests"], cwd=path, check=True, timeout=10)
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, timeout=10)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=path, check=True, timeout=10)


class BackendRouterTests(unittest.TestCase):
    def test_healthy_model_prefers_live_coding_lane(self):
        self.assertEqual(
            route_healthy_model(
                "coding",
                {"qwen2.5-coder:3b", "qwen2.5-coder:7b"},
                {"qwen2.5-coder:7b"},
            ),
            "qwen2.5-coder:7b",
        )

    def test_backend_states_do_not_promote_installation_to_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = AgentBackendRouter(repo=tmp, ollama_base="http://127.0.0.1:1")
            states = router.states(probe=False)
            self.assertIn(states["aider"].status, {"AVAILABLE", "UNAVAILABLE"})
            self.assertNotEqual(states["aider"].status, "HEALTHY")

    def test_aider_requires_explicit_scope(self):
        router = AgentBackendRouter(repo=ROOT)
        plan = BackendPlan("aider", "ollama", "qwen2.5-coder:7b", "coding", "test")
        if router.aider_executable:
            with self.assertRaises(BackendUnavailable):
                router.command(plan, ROOT, "make a harmless change", allowed_scope=[])

    def test_aider_route_uses_healthy_local_fallback(self):
        router = AgentBackendRouter(repo=ROOT)
        if router.aider_executable:
            plan = router.route("coding", "aider", probe=False)
            self.assertIn(plan.model, {"qwen2.5-coder:7b", "qwen2.5-coder:3b"})
            command, _ = router.command(plan, ROOT, "make a harmless change", allowed_scope=["README.md"])
            self.assertIn("--input-history-file", command)
            self.assertIn("/dev/null", command)

    def test_failure_classes_are_machine_readable(self):
        cases = {
            "bounded backend timeout": "MODEL_TIMEOUT",
            "unexpected malformed json": "MALFORMED_OUTPUT",
            "output truncated at context limit": "OUTPUT_TRUNCATED",
            "provider unavailable": "TRANSIENT_PROVIDER",
            "no model installed": "MODEL_UNAVAILABLE",
            "security blocker": "SECURITY_BLOCKER",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(classify_backend_failure(message), expected)


class BackendGuardTests(unittest.TestCase):
    def test_clean_repo_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            result = inspect_changes(root, backend="native")
            self.assertTrue(result.passed)

    def test_scope_and_sensitive_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "allowed.txt").write_text("safe\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=redacted\n", encoding="utf-8")
            result = inspect_changes(root, backend="aider", allowed_scope=["allowed.txt"])
            self.assertFalse(result.passed)
            self.assertTrue(any("protected path" in item for item in result.violations))

    def test_traversal_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            outside = root.parent / "outside-core-guard.txt"
            outside.write_text("outside\n", encoding="utf-8")
            link = root / "link.txt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            result = inspect_changes(root, backend="aider", allowed_scope=["link.txt"])
            self.assertFalse(result.passed)
            self.assertTrue(any("symlink" in item for item in result.violations))


if __name__ == "__main__":
    unittest.main()
