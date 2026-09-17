import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from provider_router import as_json, choose_lane, detect_lanes
from runtime_env import resolve_ollama_base


def run_preflight(base_url=None):
    base = base_url or resolve_ollama_base()
    lanes = detect_lanes(base, probe=True, release_after_probe=True)
    selected = choose_lane(lanes, "qwen-reasoning")
    result = {
        "ollama_base": base,
        "selected": vars(selected),
        "lanes": as_json(lanes),
        "fallback_policy": "qwen-coding then qwen-fast when reasoning is unavailable or too slow",
    }
    repo = Path(__file__).resolve().parents[1]
    state_path = repo / "state" / "backend-preflight.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).isoformat()
    state_payload = {
        "schema": "migz.backend-preflight.v1",
        "captured_at": captured_at,
        "source": "provider_preflight",
        "selected": result["selected"],
        "lanes": result["lanes"],
    }
    state_path.write_text(json.dumps(state_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    required = ("qwen-fast", "qwen-coding", "qwen-reasoning")
    passed = all(result["lanes"].get(name, {}).get("status") == "PASS" for name in required)
    final = {
        "schema": "migz.core.provider-preflight.v2",
        "captured_at": captured_at,
        "state": "PASSED" if passed else "BLOCKED",
        "endpoint": base,
        "ollama": "PASS",
        "lanes": result["lanes"],
        "required_lanes": list(required),
        "optional_lanes": {"deepseek": result["lanes"].get("deepseek", {}).get("status", "UNAVAILABLE")},
        "fallback_policy": ["qwen2.5-coder:7b", "qwen2.5-coder:3b"],
        "observed": True,
    }
    final_path = repo / "evidence" / "core-final-closure" / "provider-preflight-final.json"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(json.dumps(final, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    result["backend_state"] = str(state_path)
    result["final_evidence"] = str(final_path)
    if not passed:
        raise RuntimeError("required provider lane did not pass live preflight")
    return result


def main():
    try:
        result = run_preflight(sys.argv[1] if len(sys.argv) > 1 else None)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("PROVIDER_PREFLIGHT: PASS")
    except Exception as exc:
        print(f"PROVIDER_PREFLIGHT: FAIL\nERROR: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
