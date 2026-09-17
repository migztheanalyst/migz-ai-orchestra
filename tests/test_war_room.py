import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from conversation_director import ConversationDirector
from war_room_event_bus import EventBus, make_event


class WarRoomTests(unittest.TestCase):
    def test_event_bus_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(tmp)
            event = make_event("builder.complete", task_id="abc", agent="luna", summary="done")
            bus.publish(event)
            self.assertEqual(bus.recent(1)[0]["id"], event["id"])

    def test_decision_event_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(tmp)
            event = make_event("decision.evaluated", task_id="abc", agent="jev", summary="decision")
            bus.publish(event)
            self.assertEqual(bus.recent(1)[0]["type"], "decision.evaluated")

    def test_quiet_filters_builder(self):
        director = ConversationDirector("quiet")
        event = make_event("builder.complete", summary="done")
        self.assertIsNone(director.render(event))

    def test_normal_surfaces_test_failure(self):
        director = ConversationDirector("normal")
        event = make_event("tester.fail", summary="failed")
        rendered = director.render(event)
        self.assertEqual(rendered["agent"], "terra")
        self.assertEqual(rendered["text"], "failed")

    def test_warroom_adds_reaction_and_typing(self):
        director = ConversationDirector("warroom")
        event = make_event("reviewer.fail", summary="needs changes")
        rendered = director.render(event)
        self.assertEqual(rendered["reaction"], "👀")
        self.assertGreater(rendered["typing_ms"], 0)

    def test_invalid_mode_blocked(self):
        with self.assertRaises(ValueError):
            ConversationDirector("chaos")


if __name__ == "__main__":
    unittest.main()
