import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

from project_scheduler import ProjectScheduler
from task_engine import TaskStore


def paths(repo):
    repo = Path(repo).expanduser().resolve()
    return repo / "state" / "projects.json", repo / "state" / "scheduler", repo / "tasks"


def enqueue(repo, project_id, title, objective, role="coding", lane="local-heavy", max_attempts=3, backend="native", allowed_scope=None):
    registry, state, tasks = paths(repo)
    task_id = str(uuid.uuid4())
    scheduler = ProjectScheduler(registry, state)
    metadata = {
        "scheduler": "project-scoped",
        "lane": lane,
        "backend": backend,
    }
    if allowed_scope:
        metadata["allowed_scope"] = list(allowed_scope)
    task = scheduler.enqueue(project_id, title, objective, role, lane, max_attempts=max_attempts, task_id=task_id, metadata=metadata)
    try:
        TaskStore(tasks).create(title, objective, role, max_attempts, task_id=task_id, project_id=project_id,
                                metadata=metadata)
    except Exception:
        raise
    return task


def run_next(repo):
    repo = Path(repo).expanduser().resolve()
    registry, state, tasks = paths(repo)
    scheduler = ProjectScheduler(registry, state)
    task = scheduler.claim_next()
    if task is None:
        print("NO_PROJECT_PENDING_TASKS")
        return 0
    print(f"PROJECT TASK: {task['id']} | {task['project_id']} | {task['title']}")
    command = ["python3", str(repo / "conductor" / "maestro.py"), str(repo), task["id"]]
    result = subprocess.run(command, cwd=repo, text=True, shell=False)
    store = TaskStore(tasks)
    try:
        _, latest = store.find(task["id"])
        passed = latest.get("status") == "passed"
    except Exception:
        passed = False
    scheduler.finish(task["project_id"], task["id"], passed=passed)
    return result.returncode if passed else (result.returncode or 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("enqueue")
    add.add_argument("project_id"); add.add_argument("title"); add.add_argument("objective")
    add.add_argument("--role", default="coding"); add.add_argument("--lane", default="local-heavy")
    add.add_argument("--backend", choices=["native", "aider"], default="native")
    add.add_argument("--allowed-scope", action="append", default=[])
    add.add_argument("--max-attempts", type=int, default=3)
    sub.add_parser("run-next")
    sub.add_parser("status")
    sub.add_parser("recover")
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    registry, state, tasks = paths(repo)
    scheduler = ProjectScheduler(registry, state)
    if args.command == "enqueue":
        out = enqueue(repo, args.project_id, args.title, args.objective, args.role, args.lane, args.max_attempts, args.backend, args.allowed_scope)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.command == "run-next":
        raise SystemExit(run_next(repo))
    elif args.command == "recover":
        print(json.dumps(scheduler.recover_stale(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(scheduler.summary(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
