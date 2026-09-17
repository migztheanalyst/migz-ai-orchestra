import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from decision_layer import Decision, DecisionLayer, MODEL, credential_fingerprint

SPEC = importlib.util.spec_from_file_location("jev_canary", ROOT / "scripts" / "jev_canary.py")
jev_canary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(jev_canary)


class FakeLayer:
    min_confidence = 0.65

    def __init__(self, mode="shadow", **kwargs):
        self.mode = mode
    def _credential(self):
        key = os.environ.get("TYPESAFE_API_KEY")
        return key, "environment" if key else None, None
    def decide(self, task):
        if os.environ.get("TYPESAFE_API_KEY"):
            return Decision(
                source="jev",
                recommended_role="triage",
                effective_role="triage",
                operational_risk="low",
                needs_escalation=False,
                needs_review=True,
                confidence=0.91,
                model=MODEL,
                mode="shadow",
                reason="live_decision",
            )
        return Decision(
            source="heuristic",
            recommended_role="triage",
            effective_role="triage",
            operational_risk="low",
            needs_escalation=False,
            needs_review=True,
            confidence=1.0,
            model=None,
            mode="shadow",
            reason="jev_not_configured",
        )
class JevCanaryTests(unittest.TestCase):
    def test_absent_key_reports_external_blocker(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            report = jev_canary.run_live_canary(allow_local_credential=False)
        self.assertEqual(report["status"], "BLOCKED_EXTERNAL_CREDENTIAL")
        self.assertEqual(report["secret_leak_check"], "PASS")

    def test_mocked_live_canary_passes_and_hides_secret(self):
        secret = "canary-secret-do-not-leak"
        with mock.patch.object(jev_canary, "DecisionLayer", FakeLayer):
            with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": secret}, clear=True):
                report = jev_canary.run_live_canary()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["checks"]["live_schema"], "PASS")
        self.assertEqual(report["checks"]["fallback_without_key"], "PASS")
        self.assertNotIn(secret, json.dumps(report))

    def test_active_status_requires_key_and_passing_canary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "jev-canary.json").write_text(
                json.dumps({"status": "PASS", "model": "jev-1.13.0", "captured_at": datetime.now(timezone.utc).isoformat(), "latency_ms": 123.4, "credential_fingerprint": credential_fingerprint("test-key")}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
                status = DecisionLayer().status(root)
            self.assertEqual(status["status"], "ACTIVE")
            self.assertEqual(status["last_latency_ms"], 123.4)


if __name__ == "__main__":
    unittest.main()
