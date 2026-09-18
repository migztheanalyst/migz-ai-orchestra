import argparse
import json
import sys
import uuid
from pathlib import Path

try:
    from .process_runner import run_bounded
    from .project_scheduler import ProjectScheduler
    from .task_engine import TaskStore
    from .worktree_manager import recover_stale_worktrees
except ImportError:
    from process_runner import run_bounded
    from project_scheduler import ProjectScheduler
    from task_engine import TaskStore
    from worktree_manager import recover_stale_worktrees


def paths(repo):
    repo = Path(repo).expanduser().resolve()
    return repo / "state" / "projects.json", repo / "state" / "scheduler", repo / "tasks"


def enqueue(repo, project_id, title, objective, role="coding", lane="local-heavy", max_attempts=3,
            backend="native", allowed_scope=None, metadata=None, task_id=None):
    """Create one project task in both stores, rolling back on partial failure."""
    registry, state, tasks = paths(repo)
    task_id = str(task_id or uuid.uuid4())
    scheduler = ProjectScheduler(registry, state)
    store = TaskStore(tasks)
    task_metadata = dict(metadata or {})
    task_metadata.update({
        "scheduler": "project-scoped",
        "lane": lane,
        "backend": backend,
    })
    if allowed_scope:
        task_metadata["allowed_scope"] = list(allowed_scope)

    store.create(
        title, objective, role, max_attempts, task_id=task_id,
        project_id=project_id, metadata=task_metadata,
    )
    try:
        return scheduler.enqueue(
            project_id, title, objective, role, lane,
            max_attempts=max_attempts, task_id=task_id, metadata=task_metadata,
        )
    except Exception:
        store.remove_pending(task_id)
        raise


def remove_pending(repo, project_id, task_id):
    """Remove a coordinated pending task from scheduler and global task store."""
    registry, state, tasks = paths(repo)
    scheduler = ProjectScheduler(registry, state)
    store = TaskStore(tasks)
    scheduler.remove_pending(project_id, task_id)
    try:
        store.remove_pending(task_id)
    except Exception:
        # Restore scheduler visibility if the global rollback cannot complete.
        _, task = store.find(task_id)
        scheduler.enqueue(
            project_id, task["title"], task["objective"], task["role"],
            task.get("metadata", {}).get("lane", "local-heavy"),
            max_attempts=task.get("max_attempts", 3), task_id=task_id,
            metadata=task.get("metadata", {}),
        )
        raise


def enqueue_batch(repo, project_id, specs, lane="local-heavy", max_attempts=3,
                  backend="native", allowed_scope=None):
    """Create a bounded project-task batch without leaving a partial split."""
    created = []
    try:
        for spec in specs:
            created.append(enqueue(
                repo, project_id, spec["title"], spec["objective"],
                spec.get("role", "coding"), lane, max_attempts, backend,
                allowed_scope, metadata=spec,
            ))
        return created
    except Exception as exc:
        rollback_errors = []
        for task in reversed(created):
            try:
                remove_pending(repo, project_id, task["id"])
            except Exception as rollback_exc:
                rollback_errors.append(f"{task['id']}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "Project batch enqueue failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def recover(repo):
    """Reconcile stale task state and managed worktrees without data loss."""
    repo = Path(repo).expanduser().resolve()
    registry, state, tasks = paths(repo)
    store = TaskStore(tasks)
    global_recovered = store.repair_stale()
    scheduler = ProjectScheduler(registry, state)
    active_ids = store.active_ids()
    project_recovered = scheduler.recover_stale(active_ids=active_ids)

    # A crash can happen after the scheduler claim but before TaskStore moves
    # the same task to running. Reconcile terminal scheduler recovery back to
    # the global task so the two persistence layers cannot split.
    for recovered in project_recovered:
        if recovered.get("status") != "blocked":
            continue
        try:
            _, global_task = store.find(recovered["id"])
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Recovered project task {recovered['id']} is missing from TaskStore"
            ) from exc
        if global_task.get("status") == "pending":
            store.transition(
                recovered["id"],
                "blocked",
                "scheduler recovery reached maximum attempts before global claim",
            )
        elif global_task.get("status") != "blocked":
            raise RuntimeError(
                f"Recovered project task {recovered['id']} disagrees with TaskStore state"
            )

    worktree_actions = []
    repositories = {str(repo): repo}
    for project in scheduler.registry.list_projects():
        if project.get("status") != "ready":
            continue
        path = project.get("repository_path")
        if path:
            repositories[str(Path(path).expanduser().resolve())] = Path(path).expanduser().resolve()

    for target_repo in repositories.values():
        for action in recover_stale_worktrees(target_repo, active_task_ids=active_ids):
            action = dict(action)
            action["repository"] = str(target_repo)
            if action["action"] in {"BLOCKED_DIRTY", "BLOCKED_COMMITTED", "BLOCKED_MISSING_METADATA"}:
                task_id = action["task_id"]
                try:
                    _, task = store.find(task_id)
                except FileNotFoundError:
                    task = None
                if task and task.get("status") == "pending":
                    note = "stale managed worktree requires review: " + action["action"]
                    store.transition(task_id, "blocked", note)
                    project_id = task.get("project_id")
                    if project_id:
                        try:
                            scheduler.finish(project_id, task_id, passed=False)
                        except Exception as exc:
                            store.transition(
                                task_id,
                                "pending",
                                "rolled back stale-worktree block after scheduler sync failure",
                            )
                            raise RuntimeError(
                                f"Could not synchronize stale-worktree block for {task_id}"
                            ) from exc
                    action["task_state"] = "blocked"
            worktree_actions.append(action)

    return {
        "global_recovered": global_recovered,
        "project_recovered": project_recovered,
        "worktree_actions": worktree_actions,
        "active_ids": sorted(store.active_ids()),
    }


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
    result = run_bounded(
        command,
        cwd=repo,
        timeout=3600,
        capture_output=False,
    )
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
        print(json.dumps(recover(repo), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(scheduler.summary(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
