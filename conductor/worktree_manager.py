import argparse
import json
import os
import subprocess
import uuid
from pathlib import Path


def run_git(repo, *args, check=True):
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
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

        # A bounded retry may inherit an unattached branch from a failed
        # attempt.  Evidence for that attempt is stored separately; reset
        # only this UUID-scoped task branch to the current clean source head.
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
