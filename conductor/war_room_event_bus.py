import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = {
    "mission.started", "task.started", "builder.started", "builder.complete",
    "tester.pass", "tester.fail", "reviewer.pass", "reviewer.fail",
    "task.retry", "task.blocked", "task.passed", "mission.complete",
    "agent.message", "agent.reaction", "system.notice",
    "phase.progress", "heartbeat", "tester.started", "tester.command",
    "reviewer.started", "evidence.started", "evidence.complete",
    "commit.started", "commit.complete", "backend.guard", "decision.evaluated",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def make_event(event_type, task_id=None, agent=None, summary="", data=None,
               visibility="normal", reply_to=None):
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported event type: {event_type}")
    if visibility not in {"quiet", "normal", "warroom"}:
        raise ValueError("Invalid visibility")
    return {
        "id": str(uuid.uuid4()),
        "at": utc_now(),
        "type": event_type,
        "task_id": task_id,        "agent": agent,
        "summary": str(summary).strip(),
        "data": data or {},
        "visibility": visibility,
        "reply_to": reply_to,
    }


class EventBus:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "events.jsonl"

    def publish(self, event):
        if event.get("type") not in EVENT_TYPES:
            raise ValueError("Invalid event")
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def recent(self, limit=50):
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(x) for x in lines[-max(1, int(limit)):]]
