"""MIGZ AI Orchestra V4 public-core smoke gate."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from decision_layer import DecisionLayer
from orchestra_doctor import doctor
from version import ORCHESTRA_CODENAME, ORCHESTRA_NAME, ORCHESTRA_VERSION

def check(name, fn, results):
    try:
        fn()
        results[name] = "PASS"
    except Exception as exc:
        results[name] = f"FAIL:{type(exc).__name__}:{exc}"

def main():
    results = {}
    def identity():
        assert ORCHESTRA_NAME == "MIGZ AI ORCHESTRA"
        assert ORCHESTRA_VERSION == "4.0.0"
        assert ORCHESTRA_CODENAME == "OPEN ORCHESTRA"

    def fallback():
        key = os.environ.pop("TYPESAFE_API_KEY", None)
        try:
            layer = DecisionLayer(mode="shadow", allow_local_credential=False)
            status = layer.status()
            assert status["status"] == "READY_FOR_CREDENTIALS"
            decision = layer.decide({"title": "Fix code", "objective": "Implement tests", "role": "coding"})
            assert decision.source == "heuristic"
            assert decision.effective_role == "coding"
            assert decision.needs_review is True
        finally:
            if key is not None:
                os.environ["TYPESAFE_API_KEY"] = key

    def status_cli():
        env = os.environ.copy()
        env.pop("TYPESAFE_API_KEY", None)
        proc = subprocess.run(["python3", "conductor/orchestra.py", str(ROOT), "status"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, proc.stderr
        assert "MIGZ AI ORCHESTRA V4.0.0 STATUS" in proc.stdout
        expected = DecisionLayer(mode="shadow").status(ROOT)["status"]
        assert f"JEV      : {expected}" in proc.stdout

    def doctor_v4():
        report = doctor(ROOT, probe=False)
        assert report["schema"] == "migz.orchestra.doctor.v4"
        assert report["identity"]["version"] == "4.0.0"
        assert report["providers"]["jev_optional"]["model"] == "jev-latest"
        authority = report["control"]["authority"]
        assert authority["recommended_brain"] == "codex"
        assert authority["recommended_final_reviewer"] == "codex"
        assert authority["independent_qa"] == "terra"

    check("identity", identity, results)
    check("fallback", fallback, results)
    check("status_cli", status_cli, results)
    check("doctor_v4", doctor_v4, results)

    passed = all(value == "PASS" for value in results.values())
    report = {
        "schema": "migz.orchestra.v4-smoke.v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "identity": {"name": ORCHESTRA_NAME, "version": ORCHESTRA_VERSION, "codename": ORCHESTRA_CODENAME},
        "results": results,
        "status": "PASS" if passed else "FAIL",
    }
    evidence = ROOT / "evidence" / "v4-smoke.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("V4_SMOKE: " + report["status"])
    return 0 if passed else 1

if __name__ == "__main__":
    raise SystemExit(main())
