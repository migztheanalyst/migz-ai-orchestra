import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from decomposition import bounded_subtasks, should_decompose, split_objective
from mission_contracts import evidence_packet, mission_manifest
from provider_router import ProviderLane, choose_lane, retry_class


class ClosureContractTests(unittest.TestCase):
    def test_manifest_and_evidence(self):
        manifest = mission_manifest("m1", "p1", "close it", [{"title": "a"}])
        self.assertEqual(manifest["schema"], "migz.mission.v1")
        packet = evidence_packet("m1", "t1", "PASS", [{"name": "tests", "passed": True}])
        self.assertEqual(len(packet["sha256"]), 64)

    def test_decomposition(self):
        text = "A" * 1500 + ". " + "B" * 1500
        parts = split_objective(text, max_chars=1000)
        self.assertGreater(len(parts), 1)
        self.assertTrue(should_decompose("Builder output truncated"))
        self.assertGreater(len(bounded_subtasks("big", text)), 1)

    def test_provider_fallback(self):
        lanes = {
            "deepseek": ProviderLane("deepseek", "UNAVAILABLE", "ollama"),
            "qwen-reasoning": ProviderLane("qwen-reasoning", "PASS", "ollama", "qwen3.5:4b"),
        }
        self.assertEqual(choose_lane(lanes, "deepseek").name, "qwen-reasoning")
        self.assertEqual(retry_class("503 temporarily unavailable"), "transient")
        self.assertEqual(retry_class("invalid schema"), "terminal")
