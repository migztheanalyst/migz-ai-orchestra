import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))
import orchestra_doctor


class DoctorProbeReuseTests(unittest.TestCase):
    def test_live_probe_snapshot_is_reused(self):
        calls = {"lanes": 0}
        snapshot = {
            "qwen-fast": {"status": "PASS", "provider": "ollama", "model": "qwen2.5-coder:3b"},
            "qwen-coding": {"status": "PASS", "provider": "ollama", "model": "qwen2.5-coder:7b"},
            "qwen-reasoning": {"status": "PASS", "provider": "ollama", "model": "qwen3.5:4b"},
            "deepseek": {"status": "UNAVAILABLE", "provider": "ollama", "model": None},
        }
        backends = {
            "native": {"status": "HEALTHY"},
            "aider": {"status": "UNAVAILABLE"},
            "hermes": {"status": "UNAVAILABLE"},
            "deepseek": {"status": "UNAVAILABLE"},
            "openhands": {"status": "UNAVAILABLE"},
        }

        class FakeRouter:
            def __init__(self, **kwargs):
                pass
            def lane_states(self, probe=False):
                calls["lanes"] += 1
                self.assert_probe = probe
                return snapshot
            def as_json(self, probe=False, lanes=None):
                self.assertIs(lanes, snapshot)
                return backends
            def model_states(self, probe=False, lanes=None):
                self.assertIs(lanes, snapshot)
                return snapshot
            def assertIs(self, left, right):
                if left is not right:
                    raise AssertionError("doctor did not reuse the lane snapshot")

        class FakeDecisionLayer:
            def status(self, repo=None):
                return {"status": "READY_FOR_CREDENTIALS", "mode": "shadow", "model": "jev-latest"}

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(orchestra_doctor, "AgentBackendRouter", FakeRouter), \
             patch.object(orchestra_doctor, "DecisionLayer", return_value=FakeDecisionLayer()), \
             patch.object(orchestra_doctor, "diagnose_ollama", return_value={"status": "PASS"}), \
             patch.object(orchestra_doctor, "codex_executable", return_value=None), \
             patch.object(orchestra_doctor, "optional_path", return_value=None), \
             patch.object(orchestra_doctor, "_git", return_value=(0, "worktree /tmp/example", "")):
            report = orchestra_doctor.doctor(tmp, probe=True)

        self.assertEqual(calls["lanes"], 1)
        self.assertEqual(report["overall"], "PASS")


if __name__ == "__main__":
    unittest.main()


class DoctorProbeIsolationTests(unittest.TestCase):
    def test_live_router_releases_each_model_after_probe(self):
        import agent_backend_router
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(agent_backend_router, "detect_lanes", return_value={}) as detect:
            router = agent_backend_router.AgentBackendRouter(repo=tmp)
            router.lane_states(probe=True)
        detect.assert_called_once_with(
            router.ollama_base,
            probe=True,
            release_after_probe=True,
            probe_names={"qwen-fast"},
        )
