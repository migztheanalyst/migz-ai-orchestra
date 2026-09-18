import argparse
import json
import os
import uuid
from pathlib import Path

try:
    from .process_runner import run_bounded
except ImportError:
    from process_runner import run_bounded


def run_git(repo, *args, check=True):
    result = run_bounded(
        ["git", *args],
        cwd=repo,
        timeout=120,
    )

    if check and result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
        )

    return result


def validate_task_id(task_id):
    try:
        uuid.UUID(task_id)
    except Exception:
        raise ValueError("Invalid task ID")


def branch_has_unique_commits(repo, branch, source="HEAD"):
    """Return True only when branch is not fully contained in source."""
    result = run_git(
        repo, "merge-base", "--is-ancestor", branch, source, check=False
    )
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    raise RuntimeError(
        result.stderr.strip() or result.stdout.strip() or "Could not compare task branch"
    )


def validate_repo(repo):
    repo = Path(repo).expanduser().resolve()

    result = run_git(
        repo,
        "rev-parse",
        "--show-toplevel",
    )

    detected = Path(
        result.stdout.strip()
    ).resolve()

    if detected != repo:
        raise ValueError(
            "Repository path must be Git root"
        )

    return repo


def default_worktree_root(repo):
    configured = os.environ.get(
        "MIGZ_WORKTREE_ROOT"
    )

    if configured:
        return Path(
            configured
        ).expanduser().resolve()

    return (
        repo.parent
        / f"{repo.name}-worktrees"
    )


def create_worktree(
    repo,
    task_id,
    root=None,
):
    repo = validate_repo(repo)
    validate_task_id(task_id)

    status = run_git(
        repo,
        "status",
        "--porcelain",
    ).stdout.strip()

    if status:
        raise RuntimeError(
            "Main repository is not clean"
        )

    worktree_root = (
        Path(root).resolve()
        if root
        else default_worktree_root(repo)
    )

    worktree_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = (
        worktree_root / task_id
    ).resolve()

    try:
        target.relative_to(
            worktree_root
        )
    except ValueError:
        raise PermissionError(
            "Invalid worktree path"
        )

    if target.exists():
        raise FileExistsError(
            "Worktree already exists"
        )

    branch = f"task/{task_id}"

    branch_check = run_git(
        repo,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{branch}",
        check=False,
    )

    if branch_check.returncode == 0:
        worktree_info = run_git(
            repo,
            "worktree",
            "list",
            "--porcelain",
        ).stdout
        if f"branch refs/heads/{branch}\n" in worktree_info:
            raise RuntimeError(
                "Task branch already exists and is attached"
            )

        if branch_has_unique_commits(repo, branch, "HEAD"):
            raise RuntimeError(
                "Task branch contains preserved commits and cannot be reset automatically"
            )

        # A bounded retry may inherit an unattached branch from a failed
        # attempt only when that branch has no commits unique to the current source history.
        run_git(
            repo,
            "branch",
            "-f",
            branch,
            "HEAD",
        )
        run_git(
            repo,
            "worktree",
            "add",
            str(target),
            branch,
        )
    else:
        run_git(
            repo,
            "worktree",
            "add",
            "-b",
            branch,
            str(target),
            "HEAD",
        )

    return {
        "task_id": task_id,
        "branch": branch,
        "workspace": str(target),
        "status": "CREATED",
    }


def remove_worktree(
    repo,
    task_id,
    root=None,
    force=False,
):
    repo = validate_repo(repo)
    validate_task_id(task_id)

    worktree_root = (
        Path(root).resolve()
        if root
        else default_worktree_root(repo)
    )

    target = (
        worktree_root / task_id
    ).resolve()

    if not target.exists():
        raise FileNotFoundError(
            "Worktree does not exist"
        )

    command = [
        "worktree",
        "remove",
    ]
    if force:
        command.append("--force")
    command.append(str(target))

    run_git(repo, *command)

    return {
        "task_id": task_id,
        "workspace": str(target),
        "status": "REMOVED",
    }


def _porcelain_worktrees(repo):
    text = run_git(repo, "worktree", "list", "--porcelain").stdout
    entries = []
    current = {}
    for line in text.splitlines() + [""]:
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key in {"worktree", "HEAD", "branch"}:
            current[key] = value.strip()
        else:
            current[key] = True
    return entries


def managed_worktrees(repo, root=None):
    """Inspect only UUID-scoped task worktrees under the managed root."""
    repo = validate_repo(repo)
    worktree_root = (
        Path(root).expanduser().resolve()
        if root
        else default_worktree_root(repo).resolve()
    )
    rows = []
    source_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    for entry in _porcelain_worktrees(repo):
        raw_path = entry.get("worktree")
        if not raw_path:
            continue
        path = Path(raw_path).expanduser().resolve()
        if path.parent != worktree_root:
            continue
        task_id = path.name
        try:
            validate_task_id(task_id)
        except ValueError:
            continue
        expected_branch = f"refs/heads/task/{task_id}"
        if entry.get("branch") != expected_branch:
            continue
        exists = path.exists()
        dirty = None
        if exists:
            dirty = bool(run_git(path, "status", "--porcelain").stdout.strip())
        branch_ref = f"task/{task_id}"
        branch_head = run_git(repo, "rev-parse", branch_ref).stdout.strip()
        unique_commits = branch_has_unique_commits(repo, branch_ref, "HEAD")
        rows.append({
            "task_id": task_id,
            "workspace": str(path),
            "branch": expected_branch,
            "exists": exists,
            "dirty": dirty,
            "source_head": source_head,
            "branch_head": branch_head,
            "diverged": branch_head != source_head,
            "unique_commits": unique_commits,
        })
    return rows


def recover_stale_worktrees(repo, active_task_ids=None, root=None):
    """Remove only clean stale task worktrees; preserve dirty work for review."""
    active = {str(item) for item in (active_task_ids or [])}
    actions = []
    for item in managed_worktrees(repo, root=root):
        task_id = item["task_id"]
        if task_id in active:
            actions.append({**item, "action": "PRESERVED_ACTIVE"})
            continue
        if not item["exists"]:
            actions.append({**item, "action": "BLOCKED_MISSING_METADATA"})
            continue
        if item["dirty"]:
            actions.append({**item, "action": "BLOCKED_DIRTY"})
            continue
        if item["unique_commits"]:
            actions.append({**item, "action": "BLOCKED_COMMITTED"})
            continue
        remove_worktree(repo, task_id, root=root, force=False)
        actions.append({**item, "action": "REMOVED_CLEAN"})
    return actions


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "repo"
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    create = sub.add_parser(
        "create"
    )
    create.add_argument(
        "task_id"
    )

    remove = sub.add_parser(
        "remove"
    )
    remove.add_argument(
        "task_id"
    )

    sub.add_parser(
        "list"
    )

    args = parser.parse_args()

    try:
        repo = validate_repo(
            args.repo
        )

        if args.command == "create":
            result = create_worktree(
                repo,
                args.task_id,
            )

            print(
                json.dumps(
                    result,
                    indent=2,
                )
            )

        elif args.command == "remove":
            result = remove_worktree(
                repo,
                args.task_id,
            )

            print(
                json.dumps(
                    result,
                    indent=2,
                )
            )

        elif args.command == "list":
            result = run_git(
                repo,
                "worktree",
                "list",
            )

            print(
                result.stdout.rstrip()
            )

    except Exception as exc:
        print("WORKTREE : FAIL")
        print(f"ERROR    : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
