import argparse
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

try:
    from .project_registry import ProjectRegistry
except ImportError:
    from project_registry import ProjectRegistry

TERMINAL = {"passed", "blocked"}
ACTIVE = {"running", "review"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="state-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class ProjectScheduler:
    def __init__(self, registry_path, state_root):
        self.registry = ProjectRegistry(registry_path)
        self.state_root = Path(state_root).expanduser().resolve()
        self.cursor_path = self.state_root / "scheduler.json"
        self.lock_path = self.state_root / ".scheduler.lock"
        self.cursor = self._load_cursor()

    @contextmanager
    def _locked(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _load_cursor(self):
        if not self.cursor_path.exists():
            return {"last_project": None}
        return json.loads(self.cursor_path.read_text(encoding="utf-8"))

    def _queue_path(self, project_id):
        return self.state_root / "projects" / project_id / "tasks.json"

    def _load_queue(self, project_id):
        path = self._queue_path(project_id)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Project task queue must be a list")
        return data

    def _save_queue(self, project_id, queue):
        atomic_json(self._queue_path(project_id), queue)

    def enqueue(self, project_id, title, objective, role="coding", lane="local-heavy", max_attempts=3, task_id=None, metadata=None):
        project = self.registry.get_project(project_id)
        if not project or project.get("status") != "ready" or not project.get("enabled"):
            raise ValueError("Project is not enabled and ready")
        if not str(title).strip() or not str(objective).strip():
            raise ValueError("Title and objective are required")
        if not isinstance(max_attempts, int) or not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be 1-10")
        task = {
            "id": str(task_id or uuid.uuid4()), "project_id": project_id,
            "title": str(title).strip()[:200], "objective": str(objective).strip()[:5000],
            "role": role, "lane": lane, "status": "pending", "attempts": 0,
            "max_attempts": max_attempts, "metadata": dict(metadata or {}),
            "created_at": utc_now(), "updated_at": utc_now(),
        }
        with self._locked():
            queue = self._load_queue(project_id)
            if any(item.get("id") == task["id"] for item in queue):
                raise ValueError("Task ID already exists in project queue")
            queue.append(task)
            self._save_queue(project_id, queue)
        return dict(task)

    def all_tasks(self):
        rows = []
        for project in self.registry.list_projects():
            rows.extend(self._load_queue(project["id"]))
        return rows

    def _heavy_busy(self):
        return any(
            task.get("lane") == "local-heavy" and task.get("status") in ACTIVE
            for task in self.all_tasks()
        )

    def _next_eligible_unlocked(self):
        projects = [p for p in self.registry.list_projects() if p.get("enabled") and p.get("status") == "ready"]
        if not projects:
            return None
        ids = [p["id"] for p in projects]
        last = self.cursor.get("last_project")
        if last in ids:
            idx = (ids.index(last) + 1) % len(ids)
            ids = ids[idx:] + ids[:idx]
        heavy_busy = self._heavy_busy()
        for project_id in ids:
            for task in self._load_queue(project_id):
                if task.get("status") != "pending":
                    continue
                if task.get("lane") == "local-heavy" and heavy_busy:
                    continue
                self.cursor = {"last_project": project_id}
                atomic_json(self.cursor_path, self.cursor)
                return dict(task)
        return None

    def next_eligible(self):
        with self._locked():
            return self._next_eligible_unlocked()

    def _mutate_unlocked(self, project_id, task_id, new_status):
        queue = self._load_queue(project_id)
        for task in queue:
            if task.get("id") != task_id:
                continue
            allowed = {
                "running": {"pending"}, "review": {"running"},
                "passed": {"running", "review"}, "blocked": {"running", "review"},
            }
            if task.get("status") not in allowed.get(new_status, set()):
                raise ValueError(f"Invalid project task transition to {new_status}")
            if new_status == "running" and task.get("lane") == "local-heavy" and self._heavy_busy():
                raise RuntimeError("Heavy local lane is already busy")
            task["status"] = new_status
            task["updated_at"] = utc_now()
            if new_status == "running":
                task["attempts"] = int(task.get("attempts", 0)) + 1
                task["claimed_at"] = utc_now()
            if new_status in TERMINAL:
                task["finished_at"] = utc_now()
            self._save_queue(project_id, queue)
            return dict(task)
        raise FileNotFoundError("Task not found")

    def _mutate(self, project_id, task_id, new_status):
        with self._locked():
            return self._mutate_unlocked(project_id, task_id, new_status)

    def claim(self, project_id, task_id):
        return self._mutate(project_id, task_id, "running")

    def claim_next(self):
        """Atomically select, advance fairness, and claim one task."""
        with self._locked():
            task = self._next_eligible_unlocked()
            if task is None:
                return None
            return self._mutate_unlocked(task["project_id"], task["id"], "running")

    def review(self, project_id, task_id):
        return self._mutate(project_id, task_id, "review")

    def finish(self, project_id, task_id, passed=True):
        return self._mutate(project_id, task_id, "passed" if passed else "blocked")

    def retry(self, project_id, task_id):
        with self._locked():
            queue = self._load_queue(project_id)
            for task in queue:
                if task.get("id") == task_id:
                    if task.get("status") != "blocked":
                        raise ValueError("Only blocked tasks can be retried")
                    if int(task.get("attempts", 0)) >= int(task.get("max_attempts", 3)):
                        raise RuntimeError("Maximum project task attempts reached")
                    task["status"] = "pending"
                    task["updated_at"] = utc_now()
                    self._save_queue(project_id, queue)
                    return dict(task)
        raise FileNotFoundError("Task not found")

    def recover_stale(self, active_ids=None):
        """Return orphaned active tasks to pending after a controlled restart."""
        active_ids = set(active_ids or [])
        recovered = []
        with self._locked():
            for project in self.registry.list_projects():
                queue = self._load_queue(project["id"])
                changed = False
                for task in queue:
                    if task.get("status") in ACTIVE and task.get("id") not in active_ids:
                        task["status"] = "pending"
                        task["updated_at"] = utc_now()
                        task["recovery_note"] = "active task returned to pending after restart"
                        recovered.append(dict(task))
                        changed = True
                if changed:
                    self._save_queue(project["id"], queue)
        return recovered

    def summary(self):
        counts = {k: 0 for k in ["pending", "running", "review", "passed", "blocked"]}
        per_project = {}
        for project in self.registry.list_projects():
            q = self._load_queue(project["id"])
            local = {k: 0 for k in counts}
            for task in q:
                status = task.get("status")
                if status in counts:
                    counts[status] += 1; local[status] += 1
            per_project[project["id"]] = local
        return {"totals": counts, "projects": per_project, "heavy_local_busy": self._heavy_busy()}


def defaults():
    root = Path(__file__).resolve().parents[1]
    return root / "state" / "projects.json", root / "state" / "scheduler"


def main():
    registry, state = defaults()
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default=str(registry))
    parser.add_argument("--state-root", default=str(state))
    sub = parser.add_subparsers(dest="command", required=True)
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("project_id"); enqueue.add_argument("title"); enqueue.add_argument("objective")
    enqueue.add_argument("--role", default="coding"); enqueue.add_argument("--lane", default="local-heavy")
    sub.add_parser("next")
    sub.add_parser("status")
    claim = sub.add_parser("claim"); claim.add_argument("project_id"); claim.add_argument("task_id")
    finish = sub.add_parser("finish"); finish.add_argument("project_id"); finish.add_argument("task_id")
    finish.add_argument("--blocked", action="store_true")
    retry = sub.add_parser("retry"); retry.add_argument("project_id"); retry.add_argument("task_id")
    args = parser.parse_args()
    scheduler = ProjectScheduler(args.registry, args.state_root)
    if args.command == "enqueue":
        out = scheduler.enqueue(args.project_id, args.title, args.objective, args.role, args.lane)
    elif args.command == "next":
        out = scheduler.next_eligible()
    elif args.command == "status":
        out = scheduler.summary()
    elif args.command == "claim":
        out = scheduler.claim(args.project_id, args.task_id)
    elif args.command == "finish":
        out = scheduler.finish(args.project_id, args.task_id, not args.blocked)
    else:
        out = scheduler.retry(args.project_id, args.task_id)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
