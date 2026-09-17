import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from decision_layer import DecisionLayer, model_matches
from version import ORCHESTRA_VERSION


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def live_payload(*, role="reasoning", confidence=0.91, risk_score=1.1, escalation=0.2):
    return {
        "model": "jev-latest",
        "answers": {
            "recommended_role": {
                "type": "choice",
                "choice": role,
                "confidence": confidence,
                "probabilities": {role: confidence},
            },
            "operational_risk": {
                "type": "score",
                "score": risk_score,
                "confidence": 0.8,
            },
            "needs_escalation": {"type": "noul", "noul": escalation},
            "needs_review": {"type": "noul", "noul": 0.95},
        },
    }


class DecisionLayerTests(unittest.TestCase):
    def test_model_alias_accepts_resolved_version(self):
        self.assertTrue(model_matches("jev-latest", "jev-1.13.0"))
        self.assertTrue(model_matches("jev-latest", "jev-latest"))
        self.assertFalse(model_matches("jev-latest", "other-1.13.0"))
        self.assertFalse(model_matches("jev-latest", "jev-1.13"))

    def base_task(self, **overrides):
        task = {
            "title": "Implement a router change",
            "objective": "Add a safe routing feature and tests",
            "role": "coding",
            "metadata": {},
        }
        task.update(overrides)
        return task

    def test_v3_identity(self):
        self.assertEqual(ORCHESTRA_VERSION, "4.0.0")

    def test_no_key_uses_fail_safe_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = DecisionLayer(allow_local_credential=False).decide(self.base_task())
        self.assertEqual(result.source, "heuristic")
        self.assertEqual(result.effective_role, "coding")
        self.assertTrue(result.needs_review)

    def test_shadow_mode_preserves_explicit_role(self):
        def opener(request, timeout):
            return FakeResponse(json.dumps(live_payload(role="reasoning")).encode())

        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
            result = DecisionLayer(urlopen=opener).decide(self.base_task())
        self.assertEqual(result.source, "jev")
        self.assertEqual(result.recommended_role, "reasoning")
        self.assertEqual(result.effective_role, "coding")

    def test_assist_auto_can_use_live_recommendation(self):
        def opener(request, timeout):
            return FakeResponse(json.dumps(live_payload(role="reasoning")).encode())

        task = self.base_task(metadata={"decision_mode": "auto"})
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
            result = DecisionLayer(mode="assist", urlopen=opener).decide(task)
        self.assertEqual(result.effective_role, "reasoning")
        self.assertEqual(result.operational_risk, "moderate")
        self.assertFalse(result.needs_escalation)
        self.assertTrue(result.needs_review)

    def test_auto_reroute_is_blocked_for_high_risk(self):
        def opener(request, timeout):
            return FakeResponse(json.dumps(live_payload(role="reasoning", risk_score=1.9)).encode())

        task = self.base_task(metadata={"decision_mode": "auto"})
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
            result = DecisionLayer(mode="assist", urlopen=opener).decide(task)
        self.assertEqual(result.recommended_role, "reasoning")
        self.assertEqual(result.operational_risk, "high")
        self.assertEqual(result.effective_role, "coding")

    def test_low_confidence_falls_back(self):
        def opener(request, timeout):
            return FakeResponse(json.dumps(live_payload(confidence=0.2)).encode())

        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
            result = DecisionLayer(min_confidence=0.65, urlopen=opener).decide(self.base_task())
        self.assertEqual(result.source, "heuristic")
        self.assertEqual(result.reason, "jev_low_confidence")

    def test_request_uses_official_schema_and_excludes_metadata_secrets(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(json.dumps(live_payload(role="coding")).encode())

        task = self.base_task(metadata={"backend": "native", "secret": "DO_NOT_SEND"})
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
            result = DecisionLayer(urlopen=opener).decide(task)
        self.assertEqual(result.source, "jev")
        self.assertEqual(captured["url"], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(captured["body"]["model"], "jev-latest")
        self.assertEqual(captured["body"]["questions"]["recommended_role"]["type"], "choice")
        self.assertNotIn("DO_NOT_SEND", json.dumps(captured["body"]["state"]))

    def test_secret_never_leaks_into_failure_result(self):
        secret = "ultra-secret-key"

        def opener(request, timeout):
            raise RuntimeError(secret)

        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": secret}, clear=True):
            result = DecisionLayer(urlopen=opener).decide(self.base_task())
        serialized = json.dumps(result.as_dict())
        self.assertNotIn(secret, serialized)
        self.assertEqual(result.source, "heuristic")
        self.assertEqual(result.reason, "jev_unavailable:RuntimeError")


    def test_malformed_response_falls_back(self):
        def opener(request, timeout):
            return FakeResponse(json.dumps({"model": "jev-latest", "answers": {}}).encode())

        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
            result = DecisionLayer(urlopen=opener).decide(self.base_task())
        self.assertEqual(result.source, "heuristic")
        self.assertEqual(result.effective_role, "coding")
        self.assertEqual(result.reason, "jev_unavailable:ValueError")

    def test_configured_status_is_not_misreported_as_verified(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
            status = DecisionLayer().status()
        self.assertEqual(status["status"], "CONFIGURED_UNVERIFIED")
        self.assertEqual(status["model"], "jev-latest")


    def test_secure_local_credential_is_used_when_env_absent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            keyfile = Path(tmp) / "typesafe.key"
            keyfile.write_text("local-test-key\n", encoding="utf-8")
            keyfile.chmod(0o600)
            with mock.patch.dict(os.environ, {}, clear=True):
                status = DecisionLayer(credential_path=keyfile).status()
            self.assertEqual(status["status"], "CONFIGURED_UNVERIFIED")
            self.assertEqual(status["credential_source"], "local_file")

    def test_insecure_local_credential_permissions_fail_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            keyfile = Path(tmp) / "typesafe.key"
            keyfile.write_text("local-test-key\n", encoding="utf-8")
            keyfile.chmod(0o644)
            with mock.patch.dict(os.environ, {}, clear=True):
                status = DecisionLayer(credential_path=keyfile).status()
            self.assertEqual(status["status"], "CREDENTIAL_BLOCKED")



if __name__ == "__main__":
    unittest.main()
