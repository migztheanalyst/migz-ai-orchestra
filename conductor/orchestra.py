import json
import sys
from pathlib import Path

from escalation_manager import build_escalation
from task_engine import TaskStore
from project_scheduler import ProjectScheduler
from project_orchestrator import run_next as run_project_next
from decision_layer import DecisionLayer
from version import ORCHESTRA_NAME, ORCHESTRA_VERSION, ORCHESTRA_CODENAME
from process_runner import run_bounded


def run_maestro(repo, task_id):
    result = run_bounded(
        [
            "python3",
            "conductor/maestro.py",
            str(repo),
            task_id,
        ],
        cwd=repo,
        timeout=3600,
        capture_output=False,
    )

    return result.returncode


def run_next(repo):
    store = TaskStore(
        repo / "tasks"
    )

    task = store.next_pending()

    if task is None:
        try:
            scheduler = ProjectScheduler(repo / "state" / "projects.json", repo / "state" / "scheduler")
            if scheduler.next_eligible() is not None:
                return run_project_next(repo)
        except Exception:
            pass
        print("NO_PENDING_TASKS")
        return 0

    if task.get("project_id"):
        return run_project_next(repo)

    print(
        f"ORCHESTRA TASK: "
        f"{task['id']} | "
        f"{task['title']}"
    )

    code = run_maestro(
        repo,
        task["id"],
    )

    try:
        _, latest = store.find(
            task["id"]
        )
    except Exception:
        latest = None

    if (
        code != 0
        and latest
        and latest["status"] == "blocked"
    ):
        json_path, prompt_path = (
            build_escalation(
                repo,
                task["id"],
            )
        )

        print()
        print("CODEX ESCALATION CREATED")
        print(f"Package : {json_path}")
        print(f"Prompt  : {prompt_path}")

    return code


def status(repo):
    store = TaskStore(
        repo / "tasks"
    )

    print(f"=== {ORCHESTRA_NAME} V{ORCHESTRA_VERSION} STATUS ===")
    print(f"CODENAME : {ORCHESTRA_CODENAME}")
    decision_status = DecisionLayer().status(repo)
    print(
        "JEV      : "
        f"{decision_status['status']} | "
        f"mode={decision_status['mode']} | "
        f"model={decision_status['model']}"
    )

    for state in [
        "pending",
        "running",
        "review",
        "passed",
        "blocked",
    ]:
        count = len(
            list(
                (store.root / state).glob(
                    "*.json"
                )
            )
        )

        print(
            f"{state.upper():8} : {count}"
        )

    try:
        scheduler = ProjectScheduler(repo / "state" / "projects.json", repo / "state" / "scheduler")
        summary = scheduler.summary()
        print("PROJECT_SCHEDULER:")
        for state, count in summary["totals"].items():
            print(f"  {state.upper():8} : {count}")
        print(f"  HEAVY_LOCAL_BUSY : {summary['heavy_local_busy']}")
    except Exception as exc:
        print(f"PROJECT_SCHEDULER: UNAVAILABLE ({type(exc).__name__})")


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python3 conductor/orchestra.py "
            "<repo> status\n"
            "  python3 conductor/orchestra.py "
            "<repo> run-next"
        )
        raise SystemExit(1)

    repo = Path(
        sys.argv[1]
    ).expanduser().resolve()

    command = sys.argv[2]

    if command == "status":
        status(repo)

    elif command == "run-next":
        raise SystemExit(
            run_next(repo)
        )

    elif command == "doctor":
        from orchestra_doctor import doctor
        result = doctor(repo)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        raise SystemExit(0 if result.get("overall") == "PASS" else 1)

    else:
        print("Unknown command")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
