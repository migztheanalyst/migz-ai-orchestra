"""Live Jev canary for MIGZ AI Orchestra V3.

Runs one bounded shadow decision against TypeSafe when a credential is present.
Never prints or stores the API key. Writes sanitized evidence only.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from decision_layer import DecisionLayer, MODEL, credential_fingerprint, model_matches

EVIDENCE = ROOT / "evidence" / "jev-canary.json"
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_evidence(report: dict) -> None:
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def blocked_report() -> dict:
    return {
        "schema": "migz.jev.canary.v1",
        "captured_at": utc_now(),
        "status": "BLOCKED_EXTERNAL_CREDENTIAL",
        "provider": "typesafe-jev",
        "model": MODEL,
        "mode": "shadow",
        "secret_leak_check": "PASS",
    }
def run_live_canary(*, allow_local_credential: bool = True) -> dict:
    layer = DecisionLayer(mode="shadow", allow_local_credential=allow_local_credential)
    key, credential_source, credential_error = layer._credential()
    if not key:
        report = blocked_report()
        if credential_error:
            report["reason"] = credential_error
        return report

    task = {
        "title": "V3 Jev shadow canary",
        "objective": "Classify this safe read-only validation task without changing execution.",
        "role": "triage",
        "metadata": {"decision_mode": "shadow", "lane": "canary"},
    }
    started = time.monotonic()
    decision = layer.decide(task)
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)

    live_pass = decision.source == "jev" and model_matches(MODEL, decision.model)
    shadow_pass = decision.effective_role == "triage"
    confidence_pass = decision.confidence >= layer.min_confidence
    saved = os.environ.pop("TYPESAFE_API_KEY", None)
    try:
        fallback = DecisionLayer(mode="shadow", allow_local_credential=False).decide(task)
    finally:
        if saved is not None:
            os.environ["TYPESAFE_API_KEY"] = saved

    fallback_pass = fallback.source == "heuristic" and fallback.effective_role == "triage"
    report = {
        "schema": "migz.jev.canary.v1",
        "captured_at": utc_now(),
        "status": "PASS" if all((live_pass, shadow_pass, confidence_pass, fallback_pass)) else "FAIL",
        "provider": "typesafe-jev",
        "model": decision.model,
        "mode": decision.mode,
        "latency_ms": elapsed_ms,
        "credential_source": credential_source,
        "credential_fingerprint": credential_fingerprint(key),
        "decision": decision.as_dict(),
        "checks": {
            "live_schema": "PASS" if live_pass else "FAIL",
            "confidence_gate": "PASS" if confidence_pass else "FAIL",
            "shadow_role_preserved": "PASS" if shadow_pass else "FAIL",
            "fallback_without_key": "PASS" if fallback_pass else "FAIL",
        },
    }
    serialized = json.dumps(report, ensure_ascii=False)
    leak_free = key not in serialized
    report["secret_leak_check"] = "PASS" if leak_free else "FAIL"
    if not leak_free:
        report["status"] = "FAIL"
        report.pop("decision", None)

    return report


def main() -> int:
    report = run_live_canary()
    write_evidence(report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("JEV_CANARY: " + report["status"])
    if report["status"] == "PASS":
        return 0
    if report["status"] == "BLOCKED_EXTERNAL_CREDENTIAL":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
