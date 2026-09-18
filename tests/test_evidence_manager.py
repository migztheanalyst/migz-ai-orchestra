import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from evidence_manager import capture_evidence, finalize_evidence
from mission_contracts import validate_evidence_packet


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


class EvidenceManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "MIGZ Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        (self.repo / ".gitignore").write_text("evidence/\n", encoding="utf-8")
        (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", ".gitignore", "tracked.txt")
        git(self.repo, "commit", "-qm", "baseline")
        self.evidence = self.repo / "evidence"
        self.evidence.mkdir()
        (self.evidence / "tester-latest.json").write_text(
            json.dumps({"overall": "PASS", "tests": [
                {"command": ["python3", "-m", "unittest"], "exit_code": 0}
            ]}),
            encoding="utf-8",
        )
        (self.evidence / "reviewer-latest.json").write_text(
            json.dumps({"decision": "PASS"}), encoding="utf-8"
        )
        (self.evidence / "backend-guard.json").write_text(
            json.dumps({"state": "PASSED"}), encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_covers_staged_and_untracked_then_binds_commit(self):
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("new content\n", encoding="utf-8")
        git(self.repo, "add", "tracked.txt")

        task_id = str(uuid.uuid4())
        output, report = capture_evidence(
            self.repo, task_id, self.repo,
            evidence_root=self.base / "snapshots",
        )
        self.assertEqual(report["final_state"], "READY_TO_COMMIT")
        self.assertFalse(report["commit_verified"])
        self.assertEqual(report["task_commit"], "UNAVAILABLE")
        self.assertEqual(report["changed_files"], ["new.txt", "tracked.txt"])
        self.assertIn("new.txt", report["untracked_sha256"])
        self.assertEqual(set(report["content_sha256"]), {"new.txt", "tracked.txt"})
        self.assertEqual(len(report["change_sha256"]), 64)

        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "task commit")
        head = git(self.repo, "rev-parse", "HEAD")
        _, finalized = finalize_evidence(output, self.repo, head)
        self.assertTrue(finalized["commit_verified"])
        self.assertEqual(finalized["task_commit"], head)
        self.assertEqual(finalized["final_state"], "PASSED")
        packet = validate_evidence_packet(finalized["evidence_packet"])
        self.assertEqual(packet["commit"], head)
        self.assertEqual(packet["final_state"], "PASSED")

    def test_snapshot_is_not_ready_without_passing_backend_guard(self):
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        (self.evidence / "backend-guard.json").unlink()
        task_id = str(uuid.uuid4())
        _, report = capture_evidence(
            self.repo, task_id, self.repo,
            evidence_root=self.base / "snapshots",
        )
        self.assertFalse(report["precommit_ready"])
        self.assertEqual(report["final_state"], "UNAVAILABLE")
        guard_check = next(
            item for item in report["evidence_packet"]["checks"]
            if item["name"] == "backend change guard"
        )
        self.assertNotEqual(guard_check["state"], "PASSED")

    def test_finalize_rejects_same_files_with_changed_content(self):
        (self.repo / "tracked.txt").write_text("captured content\n", encoding="utf-8")
        task_id = str(uuid.uuid4())
        output, _ = capture_evidence(
            self.repo, task_id, self.repo,
            evidence_root=self.base / "snapshots",
        )

        (self.repo / "tracked.txt").write_text("different committed content\n", encoding="utf-8")
        git(self.repo, "add", "tracked.txt")
        git(self.repo, "commit", "-qm", "mutated task commit")
        head = git(self.repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "content does not match"):
            finalize_evidence(output, self.repo, head)

    def test_finalize_rejects_commit_file_mismatch(self):
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("new content\n", encoding="utf-8")
        task_id = str(uuid.uuid4())
        output, _ = capture_evidence(
            self.repo, task_id, self.repo,
            evidence_root=self.base / "snapshots",
        )

        git(self.repo, "add", "tracked.txt")
        git(self.repo, "commit", "-qm", "incomplete task commit")
        head = git(self.repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "do not match captured evidence"):
            finalize_evidence(output, self.repo, head)


if __name__ == "__main__":
    unittest.main()
