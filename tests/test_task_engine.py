import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from task_engine import TaskStore


class TaskEngineTests(unittest.TestCase):

    def test_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(tmp)

            task = store.create(
                "Probe",
                "Verify lifecycle",
                "coding",
            )

            task = store.transition(
                task["id"],
                "running",
                "claimed",
            )

            self.assertEqual(
                task["attempts"],
                1,
            )

            task = store.transition(
                task["id"],
                "review",
                "implementation complete",
            )

            task = store.transition(
                task["id"],
                "passed",
                "verified",
            )

            self.assertEqual(
                task["status"],
                "passed",
            )

    def test_invalid_transition_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(tmp)

            task = store.create(
                "Probe",
                "Verify transition safety",
                "coding",
            )

            with self.assertRaises(ValueError):
                store.transition(
                    task["id"],
                    "passed",
                )

    def test_attempt_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(tmp)

            task = store.create(
                "Retry Probe",
                "Verify retry limit",
                "coding",
                max_attempts=1,
            )

            task = store.transition(
                task["id"],
                "running",
            )

            task = store.transition(
                task["id"],
                "pending",
            )

            with self.assertRaises(RuntimeError):
                store.transition(
                    task["id"],
                    "running",
                )

    def test_repair_stale_blocks_exhausted_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(tmp)
            task = store.create(
                "Exhausted", "Only one attempt", "coding", max_attempts=1
            )
            store.transition(task["id"], "running")
            with mock.patch("task_engine.os.kill", side_effect=OSError("gone")):
                repaired = store.repair_stale()
            self.assertEqual(repaired[0]["status"], "blocked")
            self.assertEqual(store.find(task["id"])[1]["status"], "blocked")

    def test_next_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(tmp)

            created = store.create(
                "Next Probe",
                "Verify queue",
                "fast",
            )

            found = store.next_pending()

            self.assertEqual(
                found["id"],
                created["id"],
            )


if __name__ == "__main__":
    unittest.main()
