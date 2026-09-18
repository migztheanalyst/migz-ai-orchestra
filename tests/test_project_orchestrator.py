import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from project_orchestrator import enqueue, enqueue_batch, recover
from project_registry import ProjectRegistry
from project_scheduler import ProjectScheduler
from task_engine import TaskStore


class ProjectOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / "target"
        self.target.mkdir()
        subprocess.run(["git", "init", "-q", str(self.target)], check=True)
        registry = self.root / "state" / "projects.json"
        ProjectRegistry(registry).add_project("p1", "Project 1", self.target)
        self.registry = registry
        self.scheduler_root = self.root / "state" / "scheduler"

    def tearDown(self):
        self.tmp.cleanup()

    def scheduler(self):
        return ProjectScheduler(self.registry, self.scheduler_root)

    def store(self):
        return TaskStore(self.root / "tasks")

    def test_enqueue_keeps_both_stores_in_sync(self):
        task = enqueue(
            self.root, "p1", "Child", "Do child",
            metadata={"parent_task_id": "parent"},
            allowed_scope=["README.md"],
        )
        global_task = self.store().find(task["id"])[1]
        scheduled = self.scheduler()._load_queue("p1")[0]
        self.assertEqual(global_task["id"], scheduled["id"])
        self.assertEqual(global_task["metadata"], scheduled["metadata"])
        self.assertEqual(global_task["metadata"]["parent_task_id"], "parent")
        self.assertEqual(global_task["metadata"]["allowed_scope"], ["README.md"])

    def test_enqueue_rolls_back_global_store_on_scheduler_failure(self):
        with mock.patch.object(
            ProjectScheduler, "enqueue", side_effect=RuntimeError("scheduler failed")
        ):
            with self.assertRaises(RuntimeError):
                enqueue(self.root, "p1", "Child", "Do child")
        pending = list((self.root / "tasks" / "pending").glob("*.json"))
        self.assertEqual(pending, [])
        self.assertEqual(self.scheduler()._load_queue("p1"), [])

    def test_batch_rolls_back_prior_children_on_partial_failure(self):
        original = ProjectScheduler.enqueue
        calls = {"count": 0}

        def flaky(instance, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("second child failed")
            return original(instance, *args, **kwargs)

        specs = [
            {"title": "A", "objective": "Do A", "role": "coding", "parent_task_id": "p"},
            {"title": "B", "objective": "Do B", "role": "coding", "parent_task_id": "p"},
        ]
        with mock.patch.object(ProjectScheduler, "enqueue", new=flaky):
            with self.assertRaises(RuntimeError):
                enqueue_batch(self.root, "p1", specs)

        pending = list((self.root / "tasks" / "pending").glob("*.json"))
        self.assertEqual(pending, [])
        self.assertEqual(self.scheduler()._load_queue("p1"), [])

    def test_recover_blocks_task_when_stale_worktree_is_dirty(self):
        task = enqueue(self.root, "p1", "Dirty", "Preserve crash work")

        def fake_recover(repo, active_task_ids=None, root=None):
            if Path(repo).resolve() != self.target.resolve():
                return []
            return [{
                "task_id": task["id"],
                "workspace": str(self.target.parent / "managed" / task["id"]),
                "branch": f"refs/heads/task/{task['id']}",
                "exists": True,
                "dirty": True,
                "action": "BLOCKED_DIRTY",
            }]

        with mock.patch("project_orchestrator.recover_stale_worktrees", side_effect=fake_recover):
            report = recover(self.root)

        self.assertEqual(report["worktree_actions"][0]["task_state"], "blocked")
        self.assertEqual(self.store().find(task["id"])[1]["status"], "blocked")
        scheduled = self.scheduler()._load_queue("p1")[0]
        self.assertEqual(scheduled["status"], "blocked")

    def test_recover_skips_pending_project_paths(self):
        pending_path = self.root / "not-a-git-repository"
        ProjectRegistry(self.registry).add_pending("p2", "Pending", pending_path)
        seen = []

        def record(repo, active_task_ids=None, root=None):
            seen.append(Path(repo).resolve())
            return []

        with mock.patch("project_orchestrator.recover_stale_worktrees", side_effect=record):
            recover(self.root)

        self.assertNotIn(pending_path.resolve(), seen)
        self.assertIn(self.target.resolve(), seen)

    def test_recover_closes_scheduler_claim_before_global_claim_race(self):
        task = enqueue(
            self.root, "p1", "Crash window", "Crash before global claim",
            max_attempts=1,
        )
        self.scheduler().claim("p1", task["id"])
        self.assertEqual(self.store().find(task["id"])[1]["status"], "pending")

        with mock.patch("project_orchestrator.recover_stale_worktrees", return_value=[]):
            recover(self.root)

        self.assertEqual(self.store().find(task["id"])[1]["status"], "blocked")
        self.assertEqual(self.scheduler()._load_queue("p1")[0]["status"], "blocked")

    def test_recover_rolls_back_global_block_if_scheduler_sync_fails(self):
        task = enqueue(self.root, "p1", "Dirty", "Preserve crash work")

        def fake_recover(repo, active_task_ids=None, root=None):
            if Path(repo).resolve() != self.target.resolve():
                return []
            return [{
                "task_id": task["id"], "workspace": "managed", "branch": "task",
                "exists": True, "dirty": True, "action": "BLOCKED_DIRTY",
            }]

        with mock.patch("project_orchestrator.recover_stale_worktrees", side_effect=fake_recover), \
             mock.patch.object(ProjectScheduler, "finish", side_effect=RuntimeError("sync failed")):
            with self.assertRaisesRegex(RuntimeError, "Could not synchronize"):
                recover(self.root)

        self.assertEqual(self.store().find(task["id"])[1]["status"], "pending")
        self.assertEqual(self.scheduler()._load_queue("p1")[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
