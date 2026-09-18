import subprocess
import tempfile
import unittest
from pathlib import Path

from conductor.project_registry import ProjectRegistry
from conductor.project_scheduler import ProjectScheduler


class ProjectSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry_path = self.root / "projects.json"
        self.state_root = self.root / "scheduler"
        reg = ProjectRegistry(self.registry_path)
        self.repos = []
        for i in range(5):
            repo = self.root / f"repo{i}"
            repo.mkdir(); subprocess.run(["git", "init", "-q", str(repo)], check=True)
            reg.add_project(f"p{i}", f"Project {i}", repo)
            self.repos.append(repo)
        self.scheduler = ProjectScheduler(self.registry_path, self.state_root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_five_projects_registered(self):
        self.assertEqual(len(self.scheduler.registry.list_projects()), 5)

    def test_isolated_queues(self):
        a = self.scheduler.enqueue("p0", "A", "Do A")
        b = self.scheduler.enqueue("p1", "B", "Do B")
        self.assertNotEqual(a["project_id"], b["project_id"])
        self.assertEqual(len(self.scheduler._load_queue("p0")), 1)
        self.assertEqual(len(self.scheduler._load_queue("p1")), 1)

    def test_round_robin_fairness(self):
        for i in range(3):
            self.scheduler.enqueue(f"p{i}", f"T{i}", f"Do {i}", lane="remote")
        first = self.scheduler.next_eligible()
        self.scheduler.claim(first["project_id"], first["id"])
        self.scheduler.finish(first["project_id"], first["id"])
        second = self.scheduler.next_eligible()
        self.assertNotEqual(first["project_id"], second["project_id"])

    def test_heavy_local_limit_one(self):
        a = self.scheduler.enqueue("p0", "A", "Do A")
        self.scheduler.enqueue("p1", "B", "Do B")
        self.scheduler.claim("p0", a["id"])
        self.assertIsNone(self.scheduler.next_eligible())

    def test_remote_lane_can_progress_while_heavy_busy(self):
        heavy = self.scheduler.enqueue("p0", "A", "Do A")
        self.scheduler.claim("p0", heavy["id"])
        remote = self.scheduler.enqueue("p1", "B", "Do B", lane="remote")
        nxt = self.scheduler.next_eligible()
        self.assertEqual(nxt["id"], remote["id"])

    def test_restart_persistence(self):
        task = self.scheduler.enqueue("p2", "Persist", "Persist me", lane="remote")
        again = ProjectScheduler(self.registry_path, self.state_root)
        ids = [x["id"] for x in again.all_tasks()]
        self.assertIn(task["id"], ids)

    def test_retry_blocked(self):
        task = self.scheduler.enqueue("p3", "Retry", "Retry me", lane="remote")
        self.scheduler.claim("p3", task["id"])
        self.scheduler.finish("p3", task["id"], passed=False)
        retried = self.scheduler.retry("p3", task["id"])
        self.assertEqual(retried["status"], "pending")

    def test_recover_stale_blocks_exhausted_task(self):
        task = self.scheduler.enqueue(
            "p0", "Exhausted", "Do once", lane="remote", max_attempts=1
        )
        self.scheduler.claim("p0", task["id"])
        recovered = self.scheduler.recover_stale()
        self.assertEqual(recovered[0]["status"], "blocked")
        stored = self.scheduler._load_queue("p0")[0]
        self.assertEqual(stored["status"], "blocked")

    def test_summary(self):
        self.scheduler.enqueue("p4", "S", "Summary", lane="remote")
        summary = self.scheduler.summary()
        self.assertEqual(summary["totals"]["pending"], 1)
        self.assertIn("p4", summary["projects"])


if __name__ == "__main__":
    unittest.main()
