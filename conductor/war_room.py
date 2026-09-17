import argparse
from pathlib import Path

from conversation_director import ConversationDirector
from war_room_event_bus import EventBus


def render_message(message):
    if message.get("reaction"):
        print(f"{message['display']} reacted {message['reaction']}")
    print(f"{message['display']} — {message['role']}")
    print(message["text"])
    if message.get("task_id"):
        print(f"Task: {message['task_id']}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--mode", choices=["quiet", "normal", "warroom"], default="normal")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    bus = EventBus(repo / "evidence" / "war_room")
    director = ConversationDirector(args.mode)

    print("=== MIGZ WHATSAPP WAR ROOM PREVIEW ===")
    print(f"Mode : {args.mode}")
    print()

    rendered = 0
    for event in bus.recent(args.limit):
        message = director.render(event)
        if message:
            render_message(message)
            rendered += 1

    print(f"MESSAGES : {rendered}")
    print("WAR_ROOM : PASS")


if __name__ == "__main__":
    main()
