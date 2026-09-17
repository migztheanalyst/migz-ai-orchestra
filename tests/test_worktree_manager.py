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


if __name__ == "__main__":
    unittest.main()
