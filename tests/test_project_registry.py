import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from conductor.project_registry import ProjectRegistry


class ProjectRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry_path = self.root / "state" / "projects.json"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.registry = ProjectRegistry(self.registry_path)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, project_id="alpha"):
        return self.registry.add_project(project_id, "Alpha", self.repo)

    def test_create_list_get(self):
        item = self.add()
        self.assertEqual(item["status"], "ready")
        self.assertEqual(self.registry.get_project("alpha")["name"], "Alpha")
        self.assertEqual(len(self.registry.list_projects()), 1)

    def test_duplicate_id_rejected(self):
        self.add()
        other = self.root / "other"; other.mkdir()
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        with self.assertRaises(ValueError):
            self.registry.add_project("alpha", "Other", other)

    def test_duplicate_canonical_path_rejected(self):
        self.add()
        with self.assertRaises(ValueError):
            self.registry.add_project("beta", "Beta", self.repo / ".")

    def test_invalid_non_git_path_rejected(self):
        plain = self.root / "plain"; plain.mkdir()
        with self.assertRaises(ValueError):
            self.registry.add_project("beta", "Beta", plain)

    def test_persistence_reload(self):
        self.add()
        loaded = ProjectRegistry(self.registry_path)
        self.assertEqual(loaded.get_project("alpha")["repository_path"], str(self.repo.resolve()))

    def test_enable_disable(self):
        self.add()
        self.registry.disable_project("alpha")
        self.assertFalse(self.registry.get_project("alpha")["enabled"])
        self.registry.enable_project("alpha")
        self.assertTrue(self.registry.get_project("alpha")["enabled"])

    def test_atomic_json_persistence(self):
        self.add()
        data = json.loads(self.registry_path.read_text())
        self.assertIn("alpha", data)
        leftovers = list(self.registry_path.parent.glob("projects-*.json"))
        self.assertEqual(leftovers, [])

    def test_pending_project_cannot_enable(self):
        self.registry.add_pending("pending", "Pending", self.root / "missing")
        with self.assertRaises(ValueError):
            self.registry.enable_project("pending")

    def test_resolve_pending(self):
        self.registry.add_pending("pending", "Pending")
        item = self.registry.resolve_pending("pending", self.repo)
        self.assertEqual(item["status"], "ready")
        self.assertTrue(item["enabled"])


if __name__ == "__main__":
    unittest.main()
