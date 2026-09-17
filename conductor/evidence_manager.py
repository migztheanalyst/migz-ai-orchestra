import argparse
import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mission_contracts import evidence_packet


def run_git(workspace, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
        )

    return result.stdout


def validate_task_id(task_id):
    try:
        uuid.UUID(task_id)
    except Exception:
        raise ValueError(
            "Invalid task ID"
        )


def capture_evidence(
    repo,
    task_id,
    workspace=None,
    evidence_root=None,
    project_id=None,
):
    repo = Path(
        repo
    ).expanduser().resolve()

    validate_task_id(task_id)

    workspace = Path(
        workspace or repo
    ).expanduser().resolve()

    detected = Path(
        run_git(
            workspace,
            "rev-parse",
            "--show-toplevel",
        ).strip()
    ).resolve()

    if detected != workspace:
        raise ValueError(
            "Workspace is not Git root"
        )

    head = run_git(
        workspace,
        "rev-parse",
        "HEAD",
    ).strip()

    branch = run_git(
        workspace,
        "branch",
        "--show-current",
    ).strip()

    status = run_git(
        workspace,
        "status",
        "--short",
        "-uall",
    )

    diff_check_result = subprocess.run(
        [
            "git",
            "diff",
            "--check",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
    )

    diff = run_git(
        workspace,
        "diff",
        "--no-ext-diff",
    )

    name_status = run_git(workspace, "diff", "--name-status")
    untracked = [line[3:] for line in status.splitlines() if line.startswith("?? ")]
    changed_files = [line.split("\t", 1)[-1] for line in name_status.splitlines() if line.strip()]
    changed_files.extend(untracked)

    diff_hash = hashlib.sha256(
        diff.encode("utf-8")
    ).hexdigest()

    tester_path = (
        workspace
        / "evidence"
        / "tester-latest.json"
    )

    reviewer_path = (
        workspace
        / "evidence"
        / "reviewer-latest.json"
    )

    tester = None
    reviewer = None

    if tester_path.exists():
        tester = json.loads(
            tester_path.read_text()
        )

    if reviewer_path.exists():
        reviewer = json.loads(
            reviewer_path.read_text()
        )

    builder_path = workspace / "evidence" / "builder-latest.json"
    builder = json.loads(builder_path.read_text()) if builder_path.exists() else None
    backend_path = workspace / "evidence" / "backend-latest.json"
    backend = json.loads(backend_path.read_text()) if backend_path.exists() else None
    guard_path = workspace / "evidence" / "backend-guard.json"
    guard = json.loads(guard_path.read_text()) if guard_path.exists() else None
    test_commands = []
    exit_codes = {}
    if tester:
        for item in tester.get("tests", []):
            command = item.get("command", [])
            key = " ".join(command) if isinstance(command, list) else str(command)
            test_commands.append(key)
            exit_codes[key] = item.get("exit_code")

    report = {
        "task_id": task_id,
        "captured_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "workspace": str(workspace),
        "branch": branch,
        "head": head,
        "git_status": status,
        "diff_check": (
            "PASS"
            if diff_check_result.returncode == 0
            else "FAIL"
        ),
        "diff_sha256": diff_hash,
        "changed_files": sorted(set(changed_files)),
        "test_commands": test_commands,
        "exit_codes": exit_codes,
        "backend": (backend or {}).get("backend", "native") if backend else "UNAVAILABLE",
        "provider": (backend or builder or {}).get("provider", "ollama") if (backend or builder) else "UNAVAILABLE",
        "model": (backend or builder or {}).get("model", "UNAVAILABLE") if (backend or builder) else "UNAVAILABLE",
        "backend_change_guard": guard or {"state": "UNAVAILABLE"},
        "reviewer_verdict": (reviewer or {}).get("decision", "UNAVAILABLE") if reviewer else "UNAVAILABLE",
        "final_state": "PASSED" if tester and tester.get("overall") == "PASS" and reviewer and reviewer.get("decision") == "PASS" else "UNAVAILABLE",
        "tester": tester,
        "reviewer": reviewer,
    }

    checks = [
        {"name": "git diff --check", "passed": diff_check_result.returncode == 0},
        {"name": "tester", "passed": bool(tester and tester.get("overall") == "PASS")},
        {"name": "reviewer", "passed": bool(reviewer and reviewer.get("decision") == "PASS")},
    ]
    report["evidence_packet"] = evidence_packet(
        f"task:{task_id}", task_id,
        "PASS" if report["final_state"] == "PASSED" else "UNVERIFIED",
        checks,
        artifacts=["evidence/tester-latest.json", "evidence/reviewer-latest.json"],
        notes="Evidence distinguishes observed command results from unavailable release fields.",
        project=project_id or "UNAVAILABLE",
        model=report["model"],
        provider=report["provider"],
        backend=report["backend"],
        changed_files=report["changed_files"],
        test_commands=report["test_commands"],
        exit_codes=report["exit_codes"],
        reviewer_verdict=report["reviewer_verdict"],
        commit=head,
    )

    root = (
        Path(evidence_root).resolve()
        if evidence_root
        else repo / "evidence" / "tasks"
    )

    output_dir = (
        root / task_id
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = (
        output_dir
        / "snapshot.json"
    )

    output.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    return output, report


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "repo"
    )

    parser.add_argument(
        "task_id"
    )

    parser.add_argument(
        "--workspace",
        default=None,
    )

    args = parser.parse_args()

    try:
        output, report = capture_evidence(
            args.repo,
            args.task_id,
            args.workspace,
        )

        print("=== MIGZ EVIDENCE ===")
        print(
            f"Task       : {report['task_id']}"
        )
        print(
            f"Branch     : {report['branch']}"
        )
        print(
            f"HEAD       : {report['head']}"
        )
        print(
            f"Diff Check : {report['diff_check']}"
        )
        print(
            f"Diff SHA   : {report['diff_sha256']}"
        )
        print(
            f"Snapshot   : {output}"
        )
        print("EVIDENCE   : PASS")

    except Exception as exc:
        print("EVIDENCE   : FAIL")
        print(f"ERROR      : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
