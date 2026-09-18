import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from process_runner import run_bounded
from task_engine import TaskStore


def validate_task_id(task_id):
    try:
        uuid.UUID(task_id)
    except Exception:
        raise ValueError("Invalid task ID")


def git(repo, *args):
    result = run_bounded(
        ["git", *args],
        cwd=repo,
        timeout=60,
    )

    return result.stdout.strip()


def build_escalation(repo, task_id):
    repo = Path(repo).expanduser().resolve()

    validate_task_id(task_id)

    store = TaskStore(repo / "tasks")

    _, task = store.find(task_id)

    if task["status"] != "blocked":
        raise ValueError(
            "Only blocked tasks can be escalated"
        )

    main_head = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    branch = f"task/{task_id}"

    branch_exists = bool(
        git(
            repo,
            "branch",
            "--list",
            branch,
        )
    )

    task_evidence = (
        repo
        / "evidence"
        / "tasks"
        / task_id
        / "snapshot.json"
    )

    snapshot = None

    if task_evidence.exists():
        snapshot = json.loads(
            task_evidence.read_text(
                encoding="utf-8"
            )
        )

    package = {
        "schema_version": 1,
        "type": "MIGZ_CODEX_ESCALATION",
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "task": task,
        "main_head": main_head,
        "task_branch": (
            branch if branch_exists else None
        ),
        "evidence": snapshot,
        "requested_action": {
            "authority": "Codex/Sol",
            "goal": (
                "Diagnose the blocker and return "
                "minimal corrective instructions "
                "for the local orchestra."
            ),
            "do_not": [
                "claim unverified execution",
                "approve unsafe shortcuts",
                "remove security boundaries",
                "assume production access",
            ],
        },
    }

    output_dir = (
        repo
        / "evidence"
        / "escalations"
        / task_id
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = output_dir / "escalation.json"

    json_path.write_text(
        json.dumps(
            package,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    prompt = f"""# MIGZ AI ORCHESTRA — CODEX/SOL ESCALATION

You are the architecture and escalation authority for MIGZ AI ORCHESTRA.

A local autonomous task has been BLOCKED.

TASK ID:
{task_id}

TITLE:
{task['title']}

OBJECTIVE:
{task['objective']}

ROLE:
{task['role']}

ATTEMPTS:
{task['attempts']} / {task['max_attempts']}

LATEST HISTORY:
{json.dumps(task['history'][-5:], indent=2, ensure_ascii=False)}

MAIN HEAD:
{main_head}

TASK BRANCH:
{branch if branch_exists else 'No surviving task branch detected'}

Your job:

1. Diagnose the blocker using only supplied evidence.
2. Decide whether the task should be:
   - RETRY_LOCAL
   - CHANGE_PLAN
   - REQUIRE_HUMAN
   - ABANDON
3. Give the smallest safe corrective instruction.
4. Preserve all workspace, secret, Git, test, review and security boundaries.
5. Never claim execution you did not perform.

Return:

DECISION:
REASON:
LOCAL_INSTRUCTIONS:
ACCEPTANCE_CRITERIA:
RISK:
"""

    prompt_path = (
        output_dir
        / "CODEX_PROMPT.md"
    )

    prompt_path.write_text(
        prompt,
        encoding="utf-8",
    )

    return json_path, prompt_path


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 "
            "conductor/escalation_manager.py "
            "<repo> <task-id>"
        )
        raise SystemExit(1)

    try:
        json_path, prompt_path = (
            build_escalation(
                sys.argv[1],
                sys.argv[2],
            )
        )

        print("=== MIGZ ESCALATION ===")
        print(f"Package : {json_path}")
        print(f"Prompt  : {prompt_path}")
        print("ESCALATION : PASS")

    except Exception as exc:
        print("ESCALATION : FAIL")
        print(f"ERROR      : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
