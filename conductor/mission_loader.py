import json
import sys
from pathlib import Path

from task_engine import TaskStore, ROLES
from mission_contracts import validate_manifest


MAX_TASKS = 50


def load_mission(repo, mission_file):
    repo = Path(repo).expanduser().resolve()

    mission_file = Path(
        mission_file
    ).expanduser().resolve()

    data = json.loads(
        mission_file.read_text(
            encoding="utf-8"
        )
    )

    if data.get("schema") == "migz.mission.v1":
        data = validate_manifest(data)
        data["mission"] = data["title"]

    if not isinstance(
        data.get("mission"),
        str,
    ):
        raise ValueError(
            "Mission name missing"
        )

    tasks = data.get("tasks")

    if not isinstance(tasks, list):
        raise ValueError(
            "Tasks must be a list"
        )

    if not tasks:
        raise ValueError(
            "Mission contains no tasks"
        )

    if len(tasks) > MAX_TASKS:
        raise ValueError(
            "Mission exceeds task limit"
        )

    store = TaskStore(
        repo / "tasks"
    )

    created = []

    for index, item in enumerate(
        tasks,
        start=1,
    ):
        if not isinstance(item, dict):
            raise ValueError(
                f"Task {index} is invalid"
            )

        role = item.get(
            "role",
            "coding",
        )

        if role not in ROLES:
            raise ValueError(
                f"Invalid role in task {index}"
            )

        metadata = {
            "mission_id": data.get("mission_id"),
            "backend": item.get("backend", data.get("backend", "native")),
        }
        if item.get("allowed_scope") or data.get("allowed_scope"):
            metadata["allowed_scope"] = list(item.get("allowed_scope") or data.get("allowed_scope"))
        task = store.create(
            title=item["title"],
            objective=item["objective"],
            role=role,
            max_attempts=item.get(
                "max_attempts",
                3,
            ),
            project_id=data.get("project_id") or data.get("project"),
            metadata=metadata,
        )

        created.append(task)

    return data["mission"], created


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 "
            "conductor/mission_loader.py "
            "<repo> <mission.json>"
        )
        raise SystemExit(1)

    try:
        mission, tasks = load_mission(
            sys.argv[1],
            sys.argv[2],
        )

        print("=== MIGZ MISSION LOADER ===")
        print(f"Mission : {mission}")
        print(f"Tasks   : {len(tasks)}")

        for task in tasks:
            print(
                f"{task['id']} | "
                f"{task['role']} | "
                f"{task['title']}"
            )

        print("MISSION : PASS")

    except Exception as exc:
        print("MISSION : FAIL")
        print(f"ERROR   : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
