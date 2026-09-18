import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from agent_backend_router import AgentBackendRouter, BackendUnavailable, HEALTHY


class Completed:
    def __init__(self, stdout="HERMES_OK\n", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class HermesActivationTests(unittest.TestCase):
    def make_router(self, root):
        router = AgentBackendRouter(repo=root, ollama_base="http://127.0.0.1:11434")
        router.hermes_executable = "/fake/hermes"
        return router

    def test_probe_uses_isolated_empty_toolset_and_records_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            router = self.make_router(root)
            with mock.patch("agent_backend_router.run_bounded", return_value=Completed()) as run:
                result = router.bounded_hermes_probe(timeout=1)
            self.assertEqual(result["status"], HEALTHY)
            command = run.call_args.args[0]
            self.assertIn("--in", command)
            self.assertIn("context_engine", command)
            self.assertNotIn("--ignore-user-config", command)
            self.assertNotIn("", command)
            evidence = json.loads((root / "evidence" / "core-final-closure" / "hermes-final-probe.json").read_text())
            self.assertEqual(evidence["state"], "PASSED")
            self.assertTrue(router._canary_passed("hermes"))

    def test_passed_probe_promotes_hermes_to_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence" / "core-final-closure"
            evidence.mkdir(parents=True)
            (evidence / "hermes-final-probe.json").write_text(json.dumps({"state": "PASSED", "model": "qwen3.5:4b"}))
            router = self.make_router(root)
            with mock.patch.object(router, "_lane_states", return_value={}):
                state = router.states()["hermes"]
            self.assertEqual(state.status, HEALTHY)
            self.assertEqual(state.model, "qwen3.5:4b")

    def test_advisory_requires_canary_then_returns_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            router = self.make_router(root)
            with self.assertRaises(BackendUnavailable):
                router.run_hermes_advisory("test", timeout=1)
            evidence = root / "evidence" / "core-final-closure"
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / "hermes-final-probe.json").write_text(json.dumps({"state": "PASSED", "model": "qwen3.5:4b"}))
            with mock.patch("agent_backend_router.run_bounded", return_value=Completed(stdout="Useful advisory\n")):
                result = router.run_hermes_advisory("test", timeout=1)
            self.assertEqual(result["response"], "Useful advisory")
            self.assertEqual(result["status"], HEALTHY)


if __name__ == "__main__":
    unittest.main()
