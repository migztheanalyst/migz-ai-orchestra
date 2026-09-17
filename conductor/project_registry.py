import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
PROJECT_STATUSES = {"ready", "pending_path"}


def canonical_path(value):
    if value is None:
        return None
    return str(Path(value).expanduser().resolve())


def is_git_root(path):
    root = Path(path)
    if not root.is_dir():
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=root,
        capture_output=True, text=True, timeout=20, shell=False,
    )
    if result.returncode != 0:
        return False
    return Path(result.stdout.strip()).resolve() == root.resolve()


def _default_policy(value=None):
    policy = {"heavy_local_limit": 1}
    if isinstance(value, dict):
        policy.update(value)
    limit = policy.get("heavy_local_limit")
    if not isinstance(limit, int) or limit < 1 or limit > 1:
        raise ValueError("heavy_local_limit must be exactly 1 for local execution")
    return policy


class ProjectRegistry:
    def __init__(self, registry_path):
        self.registry_path = Path(registry_path).expanduser().resolve()
        self.projects = {}
        self.load()

    def _validate_record(self, project_id, item):
        if not isinstance(item, dict):
            raise ValueError(f"Project {project_id} must be an object")
        if item.get("id") != project_id:
            raise ValueError(f"Project {project_id} has unstable id")
        if not PROJECT_ID_RE.fullmatch(str(project_id)):
            raise ValueError(f"Invalid project ID: {project_id}")
        if not str(item.get("name", "")).strip():
            raise ValueError(f"Project {project_id} has no name")
        status = item.get("status")
        if status not in PROJECT_STATUSES:
            raise ValueError(f"Project {project_id} has invalid status")
        path = item.get("repository_path")
        if status == "ready":
            if not path or not is_git_root(path):
                raise ValueError(f"Ready project {project_id} is not a Git root")
        elif path is not None and not isinstance(path, str):
            raise ValueError(f"Pending project {project_id} has invalid path")
        _default_policy(item.get("execution_policy"))
        if not isinstance(item.get("enabled"), bool):
            raise ValueError(f"Project {project_id} enabled must be boolean")
        if status != "ready" and item.get("enabled"):
            raise ValueError(f"Pending project {project_id} cannot be enabled")

    def load(self):
        if not self.registry_path.exists():
            self.projects = {}
            return
        data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Project registry must contain an object")
        for project_id, item in data.items():
            self._validate_record(project_id, item)
        self.projects = data

    def save(self):
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="projects-", suffix=".json", dir=self.registry_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.projects, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.registry_path)
        finally:
            Path(name).unlink(missing_ok=True)

    def _validate_id(self, project_id):
        project_id = str(project_id).strip().lower()
        if not PROJECT_ID_RE.fullmatch(project_id):
            raise ValueError("Invalid project ID")
        return project_id

    def _canonical_ready_path(self, repository_path):
        path = canonical_path(repository_path)
        if not is_git_root(path):
            raise ValueError("Repository path must be an existing Git root")
        return path

    def _ensure_unique_path(self, repo, exclude=None):
        for key, item in self.projects.items():
            if key != exclude and item.get("repository_path") == repo:
                raise ValueError(f"Repository path {repo} already exists")

    def add_project(self, project_id, name, repository_path, default_branch="main",
                    enabled=True, execution_policy=None, metadata=None):
        project_id = self._validate_id(project_id)
        if project_id in self.projects:
            raise ValueError(f"Project ID {project_id} already exists")
        repo = self._canonical_ready_path(repository_path)
        self._ensure_unique_path(repo)
        if not enabled:
            raise ValueError("A Git-backed project must be enabled when added")
        self.projects[project_id] = {
            "id": project_id,
            "name": str(name).strip() or project_id,
            "repository_path": repo,
            "default_branch": str(default_branch).strip() or "main",
            "enabled": True,
            "execution_policy": _default_policy(execution_policy),
            "metadata": dict(metadata or {}),
            "status": "ready",
        }
        self.save()
        return dict(self.projects[project_id])

    def add_pending(self, project_id, name, repository_path=None, metadata=None):
        project_id = self._validate_id(project_id)
        if project_id in self.projects:
            raise ValueError(f"Project ID {project_id} already exists")
        path = canonical_path(repository_path) if repository_path else None
        if path:
            self._ensure_unique_path(path)
        self.projects[project_id] = {
            "id": project_id, "name": str(name).strip() or project_id,
            "repository_path": path, "default_branch": "main", "enabled": False,
            "execution_policy": _default_policy(), "metadata": dict(metadata or {}),
            "status": "pending_path",
        }
        self.save()
        return dict(self.projects[project_id])

    def list_projects(self):
        return [dict(self.projects[key]) for key in sorted(self.projects)]

    def get_project(self, project_id):
        project_id = self._validate_id(project_id)
        item = self.projects.get(project_id)
        return dict(item) if item else None

    def resolve(self, project_ref):
        ref = str(project_ref or "").strip().lower()
        if not ref:
            return None
        if ref in self.projects:
            return dict(self.projects[ref])
        path = canonical_path(project_ref)
        for item in self.projects.values():
            if item.get("repository_path") == path or str(item.get("name", "")).strip().lower() == ref:
                return dict(item)
        return None

    def _set_enabled(self, project_id, enabled):
        project_id = self._validate_id(project_id)
        if project_id not in self.projects:
            raise ValueError(f"Project ID {project_id} does not exist")
        if enabled and self.projects[project_id].get("status") != "ready":
            raise ValueError("Pending project cannot be enabled")
        self.projects[project_id]["enabled"] = bool(enabled)
        self.save()
        return dict(self.projects[project_id])

    def enable_project(self, project_id):
        return self._set_enabled(project_id, True)

    def disable_project(self, project_id):
        return self._set_enabled(project_id, False)

    def remove_project(self, project_id):
        project_id = self._validate_id(project_id)
        item = self.projects.get(project_id)
        if not item:
            raise ValueError(f"Project ID {project_id} does not exist")
        if item.get("enabled"):
            raise ValueError("Disable project before removal")
        self.projects.pop(project_id)
        self.save()
        return item

    def is_enabled(self, project_id):
        item = self.get_project(project_id)
        return bool(item and item.get("status") == "ready" and item.get("enabled"))

    def resolve_pending(self, project_id, repository_path, default_branch="main"):
        project_id = self._validate_id(project_id)
        if project_id not in self.projects:
            raise ValueError(f"Project ID {project_id} does not exist")
        repo = self._canonical_ready_path(repository_path)
        self._ensure_unique_path(repo, exclude=project_id)
        item = self.projects[project_id]
        item.update({"repository_path": repo, "default_branch": str(default_branch).strip() or "main",
                     "status": "ready", "enabled": True})
        self.save()
        return dict(item)

    def reconcile(self):
        """Return live readiness without silently rewriting persisted owner state."""
        result = []
        for item in self.list_projects():
            live = bool(item.get("repository_path") and is_git_root(item["repository_path"]))
            copy = dict(item)
            copy["live_ready"] = live
            if item.get("status") == "ready" and not live:
                copy["effective_status"] = "pending_path"
            else:
                copy["effective_status"] = item.get("status")
            result.append(copy)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default=str(Path(__file__).resolve().parents[1] / "state" / "projects.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("project_id"); add.add_argument("name"); add.add_argument("repository_path")
    add.add_argument("--branch", default="main")
    pending = sub.add_parser("add-pending")
    pending.add_argument("project_id"); pending.add_argument("name")
    pending.add_argument("--path")
    sub.add_parser("list")
    show = sub.add_parser("show", aliases=["inspect"]); show.add_argument("project_id")
    resolve = sub.add_parser("resolve"); resolve.add_argument("project_ref")
    enable = sub.add_parser("enable"); enable.add_argument("project_id")
    disable = sub.add_parser("disable"); disable.add_argument("project_id")
    remove = sub.add_parser("remove"); remove.add_argument("project_id")
    args = parser.parse_args()
    registry = ProjectRegistry(args.registry)
    if args.command == "add":
        out = registry.add_project(args.project_id, args.name, args.repository_path, args.branch)
    elif args.command == "add-pending":
        out = registry.add_pending(args.project_id, args.name, args.path)
    elif args.command == "list":
        out = registry.list_projects()
    elif args.command in {"show", "inspect"}:
        out = registry.get_project(args.project_id)
    elif args.command == "resolve":
        out = registry.resolve(args.project_ref)
    elif args.command == "enable":
        out = registry.enable_project(args.project_id)
    elif args.command == "remove":
        out = registry.remove_project(args.project_id)
    else:
        out = registry.disable_project(args.project_id)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
