import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from worktree_manager import (
    create_worktree,
    recover_stale_worktrees,
    remove_worktree,
)


def git(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


class WorktreeTests(unittest.TestCase):

    def test_create_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            repo = base / "repo"
            repo.mkdir()

            git(
                repo,
                "init",
                "-b",
                "main",
            )

            git(
                repo,
                "config",
                "user.name",
                "MIGZ Test",
            )

            git(
                repo,
                "config",
                "user.email",
                "test@example.invalid",
            )

            (repo / "README.md").write_text(
                "probe\n"
            )

            git(
                repo,
                "add",
                "README.md",
            )

            git(
                repo,
                "commit",
                "-m",
                "initial",
            )

            task_id = str(
                uuid.uuid4()
            )

            root = base / "worktrees"

            created = create_worktree(
                repo,
                task_id,
                root=root,
            )

            target = Path(
                created["workspace"]
            )

            self.assertTrue(
                target.exists()
            )

            self.assertTrue(
                (target / ".git").exists()
            )

            removed = remove_worktree(
                repo,
                task_id,
                root=root,
            )

            self.assertEqual(
                removed["status"],
                "REMOVED",
            )

            self.assertFalse(
                target.exists()
            )


class WorktreeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "MIGZ Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        (self.repo / "README.md").write_text("probe\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial")
        self.root = self.base / "worktrees"

    def tearDown(self):
        self.tmp.cleanup()

    def test_recovery_removes_clean_stale_worktree(self):
        task_id = str(uuid.uuid4())
        created = create_worktree(self.repo, task_id, root=self.root)
        target = Path(created["workspace"])
        actions = recover_stale_worktrees(self.repo, root=self.root)
        self.assertEqual(actions[0]["action"], "REMOVED_CLEAN")
        self.assertFalse(target.exists())

    def test_recovery_preserves_dirty_stale_worktree(self):
        task_id = str(uuid.uuid4())
        created = create_worktree(self.repo, task_id, root=self.root)
        target = Path(created["workspace"])
        (target / "README.md").write_text("dirty\n", encoding="utf-8")
        actions = recover_stale_worktrees(self.repo, root=self.root)
        self.assertEqual(actions[0]["action"], "BLOCKED_DIRTY")
        self.assertTrue(target.exists())

    def test_recovery_preserves_clean_diverged_worktree(self):
        task_id = str(uuid.uuid4())
        created = create_worktree(self.repo, task_id, root=self.root)
        target = Path(created["workspace"])
        (target / "README.md").write_text("committed task work\n", encoding="utf-8")
        git(target, "add", "README.md")
        git(target, "commit", "-m", "task progress")
        actions = recover_stale_worktrees(self.repo, root=self.root)
        self.assertEqual(actions[0]["action"], "BLOCKED_COMMITTED")
        self.assertTrue(actions[0]["unique_commits"])
        self.assertTrue(target.exists())

    def test_retry_refuses_to_reset_unattached_diverged_branch(self):
        task_id = str(uuid.uuid4())
        created = create_worktree(self.repo, task_id, root=self.root)
        target = Path(created["workspace"])
        (target / "README.md").write_text("committed task work\n", encoding="utf-8")
        git(target, "add", "README.md")
        git(target, "commit", "-m", "task progress")
        remove_worktree(self.repo, task_id, root=self.root)
        with self.assertRaisesRegex(RuntimeError, "preserved commits"):
            create_worktree(self.repo, task_id, root=self.root)

    def test_retry_allows_old_branch_when_source_advanced(self):
        task_id = str(uuid.uuid4())
        created = create_worktree(self.repo, task_id, root=self.root)
        remove_worktree(self.repo, task_id, root=self.root)
        (self.repo / "README.md").write_text("source advanced\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "advance source")
        retried = create_worktree(self.repo, task_id, root=self.root)
        self.assertTrue(Path(retried["workspace"]).exists())

    def test_recovery_preserves_active_worktree(self):
        task_id = str(uuid.uuid4())
        created = create_worktree(self.repo, task_id, root=self.root)
        target = Path(created["workspace"])
        actions = recover_stale_worktrees(
            self.repo, active_task_ids={task_id}, root=self.root
        )
        self.assertEqual(actions[0]["action"], "PRESERVED_ACTIVE")
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
