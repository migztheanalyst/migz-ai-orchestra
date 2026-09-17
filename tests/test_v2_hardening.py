import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from decomposition import bounded_subtasks, split_objective
from mission_contracts import evidence_packet, mission_manifest, validate_evidence_packet, validate_manifest
from provider_router import classify_failure
from safe_executor import is_allowed
from safe_writer import safe_write
from task_engine import TaskStore


class V2ContractHardeningTests(unittest.TestCase):
    def test_decomposition_is_bounded_and_traceable(self):
        objective = "word " * 4000
        parts = split_objective(objective, max_chars=256, max_parts=100)
        self.assertTrue(parts)
        self.assertTrue(all(len(part) <= 256 for part in parts))
        children = bounded_subtasks("Large", objective, parent_task_id="parent")
        self.assertEqual(children[0]["parent_task_id"], "parent")
        self.assertEqual(" ".join(x["objective"] for x in children), " ".join(objective.split()))

    def test_manifest_rejects_missing_contract_fields(self):
        manifest = mission_manifest("m1", "p1", "close it", [{"title": "a", "objective": "do a"}])
        self.assertEqual(validate_manifest(manifest)["project"], "p1")
        with self.assertRaises(ValueError):
            validate_manifest({"schema": "migz.mission.v1"})

    def test_evidence_hash_and_states(self):
        packet = evidence_packet("m1", "t1", "PASS", [{"name": "tests", "passed": True}], project="p1", commit="abc")
        self.assertEqual(validate_evidence_packet(packet)["final_state"], "PASSED")
        packet["notes"] = "tampered"
        with self.assertRaises(ValueError):
            validate_evidence_packet(packet)

    def test_failure_classes(self):
        self.assertEqual(classify_failure("provider timeout 503"), "TRANSIENT")
        self.assertEqual(classify_failure("malformed JSON output"), "IMPLEMENTATION_FAILURE")
        self.assertEqual(classify_failure("401 missing API key"), "EXTERNAL_CREDENTIAL")
        self.assertEqual(classify_failure("unsafe arbitrary command"), "SAFETY_BLOCKER")


class V2BoundaryHardeningTests(unittest.TestCase):
    def test_writer_blocks_sensitive_and_escape_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("../escape.txt", "/tmp/escape.txt", ".git/config", ".env.local", "api_key.txt"):
                with self.assertRaises(PermissionError):
                    safe_write(tmp, name, "blocked")
            outside = Path(tmp).parent / "outside-v2"
            outside.mkdir(exist_ok=True)
            (Path(tmp) / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(PermissionError):
                safe_write(tmp, "link/file.txt", "blocked")

    def test_executor_allows_only_exact_read_only_commands(self):
        self.assertFalse(is_allowed(["git", "status", ";", "rm", "-rf", "."]))
        self.assertFalse(is_allowed(["powershell", "-Command", "Remove-Item", "."]))
        self.assertFalse(is_allowed(["bash", "-lc", "git status"]))
        self.assertFalse(is_allowed(["git", "reset", "--hard"]))

    def test_task_project_identity_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(tmp)
            task = store.create("Project task", "safe objective", "coding", project_id="p1", metadata={"lane": "local-heavy"})
            loaded = TaskStore(tmp).find(task["id"])[1]
            self.assertEqual(loaded["project_id"], "p1")
            self.assertEqual(loaded["metadata"]["lane"], "local-heavy")


if __name__ == "__main__":
    unittest.main()
