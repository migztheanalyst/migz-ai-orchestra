from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

import provider_router


class ProviderProbeTests(unittest.TestCase):
    def test_probe_uses_openai_compatible_chat_endpoint(self):
        seen = {}

        def fake(url, payload, timeout):
            seen.update(url=url, timeout=timeout, payload=payload)
            return {"choices": [{"message": {"content": "PROVIDER_OK"}}]}

        with patch.object(provider_router, "_post_json_bounded", side_effect=fake):
            result = provider_router.probe_model(
                "http://ollama:11434", "qwen2.5-coder:7b", timeout=42
            )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(seen["url"].endswith("/v1/chat/completions"))
        self.assertEqual(seen["timeout"], 42)
        self.assertFalse(seen["payload"]["stream"])

    def test_reasoning_probe_disables_reasoning_on_wire(self):
        seen = {}

        def fake(url, payload, timeout):
            seen.update(payload=payload)
            return {"choices": [{"message": {"content": "PROVIDER_OK"}}]}

        with patch.object(provider_router, "_post_json_bounded", side_effect=fake):
            result = provider_router.probe_model(
                "http://ollama:11434", "qwen3.5:4b", disable_reasoning=True
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            seen["payload"]["reasoning"], {"enabled": False, "effort": "none"}
        )

    def test_preflight_releases_models_between_live_probes(self):
        models = {
            "qwen2.5-coder:3b", "qwen2.5-coder:7b",
            "qwen3.5:4b", "deepseek-r1:1.5b",
        }
        live = {"status": "PASS", "elapsed_seconds": 0.1, "reason": "ok"}
        with patch.object(provider_router, "ollama_models", return_value=models), \
             patch.object(provider_router, "probe_model", return_value=live), \
             patch.object(provider_router, "_release_model", return_value=True) as release:
            provider_router.detect_lanes(
                "http://ollama:11434", probe=True, release_after_probe=True
            )
        self.assertEqual(release.call_count, 4)

    def test_core_probe_only_executes_fast_lane(self):
        models = {"qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:4b"}
        live = {"status": "PASS", "elapsed_seconds": 0.1, "reason": "ok"}
        with patch.object(provider_router, "ollama_models", return_value=models), \
             patch.object(provider_router, "probe_model", return_value=live) as probe, \
             patch.object(provider_router, "_release_model", return_value=True) as release:
            lanes = provider_router.detect_lanes(
                "http://ollama:11434", probe=True, release_after_probe=True,
                probe_names={"qwen-fast"},
            )
        probe.assert_called_once()
        self.assertEqual(probe.call_args.args[1], "qwen2.5-coder:3b")
        self.assertEqual(probe.call_args.kwargs["timeout"], 120)
        self.assertEqual(release.call_count, 1)
        self.assertEqual(lanes["qwen-fast"].status, "PASS")
        self.assertEqual(lanes["qwen-coding"].status, "AVAILABLE")
        self.assertEqual(lanes["qwen-reasoning"].status, "AVAILABLE")

    def test_fast_probe_keeps_longer_explicit_timeout(self):
        models = {"qwen2.5-coder:3b"}
        live = {"status": "PASS", "elapsed_seconds": 0.1, "reason": "ok"}
        with patch.object(provider_router, "ollama_models", return_value=models), \
             patch.object(provider_router, "probe_model", return_value=live) as probe:
            provider_router.detect_lanes(
                "http://ollama:11434", probe=True, timeout=180,
                probe_names={"qwen-fast"},
            )
        self.assertEqual(probe.call_args.kwargs["timeout"], 180)

    def test_missing_optional_local_deepseek_does_not_create_hosted_lane(self):
        models = {"qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:4b"}
        with patch.object(provider_router, "ollama_models", return_value=models):
            lanes = provider_router.detect_lanes("http://ollama:11434", probe=False)
        self.assertEqual(set(lanes), {
            "qwen-fast", "qwen-coding", "qwen-reasoning", "deepseek"
        })
        self.assertEqual(lanes["deepseek"].status, "UNAVAILABLE")
        self.assertEqual(lanes["deepseek"].provider, "ollama")

    def test_local_deepseek_remains_optional_advisory_lane(self):
        models = {
            "qwen2.5-coder:3b", "qwen2.5-coder:7b",
            "qwen3.5:4b", "deepseek-r1:1.5b",
        }
        with patch.object(provider_router, "ollama_models", return_value=models):
            lanes = provider_router.detect_lanes("http://ollama:11434", probe=False)
        self.assertEqual(lanes["deepseek"].status, "PASS")
        self.assertEqual(lanes["deepseek"].provider, "ollama")

    def test_advisory_probe_tolerates_non_exact_response(self):
        response = {"choices": [{"message": {"content": "hello"}}]}
        with patch.object(provider_router, "_post_json_bounded", return_value=response):
            result = provider_router.probe_model(
                "http://ollama:11434", "deepseek-r1:1.5b", require_exact=False
            )
        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
