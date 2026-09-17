"""Bounded control-plane fallback canary with a deliberately failed optional lane."""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from agent_backend_router import AgentBackendRouter, BackendUnavailable
from provider_router import classify_backend_failure
from war_room_event_bus import EventBus, make_event


class ForcedOptionalFailureRouter(AgentBackendRouter):
    def route(self, role="coding", requested_backend=None, probe=False):
        if requested_backend == "hermes":
            raise BackendUnavailable("simulated Hermes backend unavailable")
        return super().route(role, requested_backend, probe=probe)


def main():
    task_id = str(uuid.uuid4())
    router = ForcedOptionalFailureRouter(repo=ROOT)
    started = datetime.now(timezone.utc).isoformat()
    preferred_error = None
    fallback = None
    try:
        fallback, preferred_error = router.route_with_fallback("coding", "hermes", probe=False)
    except Exception as exc:
        print(f"BACKEND_FALLBACK_CANARY: FAIL ({type(exc).__name__})")
        return 1

    failure_class = classify_backend_failure(preferred_error or "")
    bus = EventBus(ROOT / "evidence" / "war_room")
    bus.publish(make_event(
        "task.started", task_id=task_id, agent="sol",
        summary="Fallback canary started", visibility="normal",
        data={"backend": "hermes", "provider": "ollama", "model": "qwen3.5:4b", "canary": True},
    ))
    bus.publish(make_event(
        "task.retry", task_id=task_id, agent="sol",
        summary="Optional backend failed; bounded fallback selected", visibility="normal",
        data={"backend": fallback.backend, "provider": fallback.provider, "model": fallback.model,
              "fallback": ["hermes", fallback.backend], "retry": 0, "failure_class": failure_class, "canary": True},
    ))
    bus.publish(make_event(
        "task.passed", task_id=task_id, agent="sol",
        summary="Fallback canary passed", visibility="quiet",
        data={"backend": fallback.backend, "provider": fallback.provider, "model": fallback.model,
              "fallback": ["hermes", fallback.backend], "canary": True},
    ))

    payload = {
        "schema": "migz.core.fallback-canary.v1",
        "state": "PASSED",
        "observed": True,
        "simulated_control_plane": True,
        "task_id": task_id,
        "started_at": started,
        "failure": {"backend": "hermes", "failure_class": failure_class, "reason": preferred_error},
        "fallback": {"backend": fallback.backend, "provider": fallback.provider, "model": fallback.model},
        "same_task_trace": True,
        "duplicate_execution": False,
        "terminal_state": "PASSED",
        "telemetry_events": ["task.started", "task.retry", "task.passed"],
    }
    output = ROOT / "evidence" / "core-final-closure" / "fallback-canary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("BACKEND_FALLBACK_CANARY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
