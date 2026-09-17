import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from project_registry import ProjectRegistry
from project_scheduler import ProjectScheduler


class V2StressTests(unittest.TestCase):
    def _repo(self, root, name):
        path = root / name
        path.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
        return path

    def test_five_project_fairness_failure_retry_restart(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            registry_path = base / "projects.json"
            state_root = base / "state"
            registry = ProjectRegistry(registry_path)
            ids = ["shiletna", "dose-lens", "nutrition", "sharm-derma", "migz-course"]
            for pid in ids:
                registry.add_project(pid, pid, self._repo(base, pid))
            scheduler = ProjectScheduler(registry_path, state_root)
            tasks = {pid: scheduler.enqueue(pid, f"task-{pid}", "isolated simulation") for pid in ids}
            order = []
            for _ in ids:
                nxt = scheduler.next_eligible()
                self.assertIsNotNone(nxt)
                order.append(nxt["project_id"])
                scheduler.claim(nxt["project_id"], nxt["id"])
                scheduler.finish(nxt["project_id"], nxt["id"], passed=True)
            self.assertEqual(set(order), set(ids))

            # Deliberate failure, retry, and restart persistence.
            failed = scheduler.enqueue(ids[0], "deliberate-failure", "simulate provider/test failure", lane="local-light")
            scheduler.claim(ids[0], failed["id"])
            scheduler.finish(ids[0], failed["id"], passed=False)
            scheduler.retry(ids[0], failed["id"])
            restarted = ProjectScheduler(registry_path, state_root)
            recovered = [t for t in restarted.all_tasks() if t["id"] == failed["id"]][0]
            self.assertEqual(recovered["status"], "pending")
            claimed = restarted.next_eligible()
            self.assertEqual(claimed["id"], failed["id"])
            restarted.claim(ids[0], failed["id"])
            restarted.finish(ids[0], failed["id"], passed=True)
            summary = ProjectScheduler(registry_path, state_root).summary()
            self.assertEqual(summary["totals"]["running"], 0)
            self.assertEqual(summary["totals"]["review"], 0)
            self.assertEqual(summary["totals"]["blocked"], 0)
            self.assertEqual(summary["totals"]["passed"], 6)
