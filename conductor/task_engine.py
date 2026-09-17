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
except ImportError:  # pragma: no cover - Windows fallback keeps API usable.
    fcntl = None

STATUSES = {
    "pending",
    "running",
    "review",
    "passed",
    "blocked",
}

ROLES = {
    "fast",
    "triage",
    "coding",
    "review",
    "reasoning",
    "general",
}

TRANSITIONS = {
    "pending": {"running", "blocked"},
    "running": {"review", "blocked", "pending"},
    "review": {"passed", "blocked", "running", "pending"},
    "blocked": {"pending"},
    "passed": set(),
}


def now():
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

        for status in STATUSES:
            (self.root / status).mkdir(
                parents=True,
                exist_ok=True,
            )
        self.lock_path = self.root / ".task-store.lock"

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

    def _validate_id(self, task_id):
        try:
            uuid.UUID(task_id)
        except Exception:
            raise ValueError("Invalid task ID")

    def _path(self, status, task_id):
        if status not in STATUSES:
            raise ValueError("Invalid status")

        self._validate_id(task_id)

        return self.root / status / f"{task_id}.json"

    def _write_atomic(self, path, data):
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as temp:
            json.dump(
                data,
                temp,
                indent=2,
                ensure_ascii=False,
            )
            temp.write("\n")
            temp_path = Path(temp.name)

        os.replace(temp_path, path)

    def create(
        self,
        title,
        objective,
        role,
        max_attempts=3,
        task_id=None,
        project_id=None,
        metadata=None,
    ):
        title = title.strip()
        objective = objective.strip()
        role = role.strip().lower()

        if not title:
            raise ValueError("Title cannot be empty")

        if not objective:
            raise ValueError(
                "Objective cannot be empty"
            )

        if len(title) > 200:
            raise ValueError("Title too long")

        if len(objective) > 5000:
            raise ValueError("Objective too long")

        if role not in ROLES:
            raise ValueError(
                f"Invalid role: {role}"
            )

        if max_attempts < 1 or max_attempts > 10:
            raise ValueError(
                "max_attempts must be 1-10"
            )

        task_id = str(task_id or uuid.uuid4())
        self._validate_id(task_id)
        timestamp = now()

        task = {
            "id": task_id,
            "title": title,
            "objective": objective,
            "role": role,
            "status": "pending",
            "attempts": 0,
            "max_attempts": max_attempts,
            "created_at": timestamp,
            "updated_at": timestamp,
            "project_id": project_id,
            "metadata": dict(metadata or {}),
            "owner_pid": None,
            "history": [
                {
                    "at": timestamp,
                    "from": None,
                    "to": "pending",
                    "note": "task created",
                }
            ],
        }

        with self._locked():
            if any(self._path(status, task_id).exists() for status in STATUSES):
                raise ValueError("Task ID already exists")
            self._write_atomic(self._path("pending", task_id), task)

        return task

    def find(self, task_id):
        self._validate_id(task_id)

        matches = []

        for status in STATUSES:
            path = self._path(
                status,
                task_id,
            )

            if path.exists():
                matches.append(path)

        if not matches:
            raise FileNotFoundError(
                "Task not found"
            )

        if len(matches) != 1:
            raise RuntimeError(
                "Task exists in multiple states"
            )

        path = matches[0]

        return (
            path,
            json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            ),
        )

    def transition(
        self,
        task_id,
        new_status,
        note="",
    ):
        if new_status not in STATUSES:
            raise ValueError(
                "Invalid destination status"
            )

        with self._locked():
            old_path, task = self.find(task_id)
            old_status = task["status"]

            if new_status not in TRANSITIONS[old_status]:
                raise ValueError(
                    f"Transition forbidden: "
                    f"{old_status} -> {new_status}"
                )

            if new_status == "running":
                if task["attempts"] >= task["max_attempts"]:
                    raise RuntimeError("Maximum attempts reached")

                task["attempts"] += 1
                task["owner_pid"] = os.getpid()
                task["started_at"] = now()
            elif new_status in {"passed", "blocked"}:
                task["finished_at"] = now()
                task["owner_pid"] = None

            timestamp = now()

            task["status"] = new_status
            task["updated_at"] = timestamp

            task["history"].append({
                "at": timestamp,
                "from": old_status,
                "to": new_status,
                "note": note.strip(),
            })

            new_path = self._path(new_status, task_id)

            self._write_atomic(new_path, task)

            if old_path != new_path:
                old_path.unlink()

            return task

    def repair_stale(self):
        """Recover active records whose owner process is no longer alive."""
        repaired = []
        for status in ("running", "review"):
            for path in (self.root / status).glob("*.json"):
                task = json.loads(path.read_text(encoding="utf-8"))
                pid = task.get("owner_pid")
                alive = False
                if isinstance(pid, int) and pid > 0:
                    try:
                        os.kill(pid, 0)
                        alive = True
                    except OSError:
                        alive = False
                if not alive:
                    try:
                        repaired.append(self.transition(task["id"], "pending", "stale active task recovered after restart"))
                    except (FileNotFoundError, ValueError):
                        pass
        return repaired

    def next_pending(self):
        candidates = []

        for path in (
            self.root / "pending"
        ).glob("*.json"):
            task = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            candidates.append(task)

        if not candidates:
            return None

        return sorted(
            candidates,
            key=lambda item: item["created_at"],
        )[0]


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
)

DEFAULT_TASK_ROOT = PROJECT_ROOT / "tasks"


def print_task(task):
    print(
        json.dumps(
            task,
            indent=2,
            ensure_ascii=False,
        )
    )


def main():
    parser = argparse.ArgumentParser()

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    create = sub.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--role", required=True)
    create.add_argument(
        "--max-attempts",
        type=int,
        default=3,
    )

    transition = sub.add_parser("transition")
    transition.add_argument("task_id")
    transition.add_argument("status")
    transition.add_argument(
        "--note",
        default="",
    )

    show = sub.add_parser("show")
    show.add_argument("task_id")

    sub.add_parser("next")

    args = parser.parse_args()

    store = TaskStore(DEFAULT_TASK_ROOT)

    try:
        if args.command == "create":
            task = store.create(
                args.title,
                args.objective,
                args.role,
                args.max_attempts,
            )

            print(
                f"TASK_ID={task['id']}"
            )
            print_task(task)

        elif args.command == "transition":
            task = store.transition(
                args.task_id,
                args.status,
                args.note,
            )

            print_task(task)

        elif args.command == "show":
            _, task = store.find(
                args.task_id
            )

            print_task(task)

        elif args.command == "next":
            task = store.next_pending()

            if task is None:
                print("NO_PENDING_TASKS")
            else:
                print_task(task)

    except Exception as exc:
        print(f"TASK_ENGINE: FAIL")
        print(f"ERROR: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
