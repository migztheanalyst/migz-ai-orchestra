import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from .mission_contracts import evidence_packet
    from .process_runner import run_bounded
except ImportError:
    from mission_contracts import evidence_packet
    from process_runner import run_bounded


def run_git(workspace, *args):
    result = run_bounded(
        ["git", *args],
        cwd=workspace,
        timeout=120,
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


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_entry_hash(workspace, relative):
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"Invalid evidence path: {relative}")
    candidate = (Path(workspace) / relative_path).resolve(strict=False)
    root = Path(workspace).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Evidence path escapes workspace") from exc
    lexical = root / relative_path
    if lexical.is_symlink():
        target = os.readlink(lexical)
        data = b"SYMLINK\0" + os.fsencode(target)
        return hashlib.sha256(data).hexdigest()
    if lexical.exists():
        if not lexical.is_file():
            raise ValueError(f"Unsupported evidence path: {relative}")
        return _sha256_file(lexical)
    return "DELETED"


def _packet_rehash(packet):
    canonical = dict(packet)
    canonical.pop("sha256", None)
    packet["sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return packet


def _write_json_atomic(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


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

    diff_check_result = run_bounded(
        ["git", "diff", "HEAD", "--check"],
        cwd=workspace,
        timeout=60,
    )

    diff = run_git(
        workspace,
        "diff",
        "HEAD",
        "--no-ext-diff",
        "--binary",
    )

    name_status = run_git(workspace, "diff", "HEAD", "--name-status", "--no-renames")
    untracked_raw = run_git(
        workspace, "ls-files", "--others", "--exclude-standard", "-z"
    )
    untracked = [item for item in untracked_raw.split("\0") if item]
    changed_files = [line.split("\t", 1)[-1] for line in name_status.splitlines() if line.strip()]
    changed_files.extend(untracked)
    changed_files = sorted(set(changed_files))
    content_hashes = {
        relative: _workspace_entry_hash(workspace, relative)
        for relative in changed_files
    }

    diff_hash = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    untracked_hashes = {}
    for relative in sorted(untracked):
        candidate = (workspace / relative).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError as exc:
            raise ValueError("Untracked evidence path escapes workspace") from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"Unsupported untracked evidence path: {relative}")
        untracked_hashes[relative] = _sha256_file(candidate)

    change_material = diff + "\n" + json.dumps(
        untracked_hashes, sort_keys=True, ensure_ascii=False
    )
    change_hash = hashlib.sha256(change_material.encode("utf-8")).hexdigest()

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

    guard_passed = bool(guard and guard.get("state") == "PASSED")
    precommit_ready = bool(
        diff_check_result.returncode == 0
        and tester and tester.get("overall") == "PASS"
        and reviewer and reviewer.get("decision") == "PASS"
        and guard_passed
    )
    report = {
        "task_id": task_id,
        "captured_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "workspace": str(workspace),
        "branch": branch,
        "head": head,
        "base_head": head,
        "task_commit": "UNAVAILABLE",
        "commit_verified": False,
        "git_status": status,
        "diff_check": (
            "PASS"
            if diff_check_result.returncode == 0
            else "FAIL"
        ),
        "diff_sha256": diff_hash,
        "untracked_sha256": untracked_hashes,
        "content_sha256": content_hashes,
        "change_sha256": change_hash,
        "changed_files": changed_files,
        "test_commands": test_commands,
        "exit_codes": exit_codes,
        "backend": (backend or {}).get("backend", "native") if backend else "UNAVAILABLE",
        "provider": (backend or builder or {}).get("provider", "ollama") if (backend or builder) else "UNAVAILABLE",
        "model": (backend or builder or {}).get("model", "UNAVAILABLE") if (backend or builder) else "UNAVAILABLE",
        "backend_change_guard": guard or {"state": "UNAVAILABLE"},
        "reviewer_verdict": (reviewer or {}).get("decision", "UNAVAILABLE") if reviewer else "UNAVAILABLE",
        "precommit_ready": precommit_ready,
        "final_state": "READY_TO_COMMIT" if precommit_ready else "UNAVAILABLE",
        "tester": tester,
        "reviewer": reviewer,
    }

    checks = [
        {"name": "git diff --check", "passed": diff_check_result.returncode == 0},
        {"name": "tester", "passed": bool(tester and tester.get("overall") == "PASS")},
        {"name": "reviewer", "passed": bool(reviewer and reviewer.get("decision") == "PASS")},
        {"name": "backend change guard", "passed": guard_passed},
    ]
    report["evidence_packet"] = evidence_packet(
        f"task:{task_id}", task_id,
        "UNVERIFIED",
        checks,
        artifacts=["evidence/tester-latest.json", "evidence/reviewer-latest.json"],
        notes="Pre-commit evidence captured; task commit is verified during finalization.",
        project=project_id or "UNAVAILABLE",
        model=report["model"],
        provider=report["provider"],
        backend=report["backend"],
        changed_files=report["changed_files"],
        test_commands=report["test_commands"],
        exit_codes=report["exit_codes"],
        reviewer_verdict=report["reviewer_verdict"],
        commit="UNAVAILABLE",
        final_state="UNAVAILABLE",
        observations=[f"base_head={head}", f"change_sha256={change_hash}"],
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

    _write_json_atomic(output, report)

    return output, report


def finalize_evidence(snapshot_path, workspace, commit):
    """Bind pre-commit evidence to the exact verified task commit."""
    snapshot_path = Path(snapshot_path).expanduser().resolve()
    workspace = Path(workspace).expanduser().resolve()
    report = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not report.get("precommit_ready"):
        raise RuntimeError("Pre-commit evidence is not ready for finalization")

    commit = str(commit).strip()
    head = run_git(workspace, "rev-parse", "HEAD").strip()
    if not commit or head != commit:
        raise RuntimeError("Task commit does not match workspace HEAD")
    parent = run_git(workspace, "rev-parse", f"{commit}^").strip()
    if parent != report.get("base_head"):
        raise RuntimeError("Task commit parent does not match evidence base HEAD")

    committed = run_git(
        workspace, "show", "--format=", "--name-only", "--no-renames", commit
    )
    committed_files = sorted({line.strip() for line in committed.splitlines() if line.strip()})
    expected_files = sorted(set(report.get("changed_files", [])))
    if committed_files != expected_files:
        raise RuntimeError("Task commit files do not match captured evidence")
    if run_git(workspace, "status", "--porcelain").strip():
        raise RuntimeError("Workspace is not clean after task commit")

    final_hashes = {
        relative: _workspace_entry_hash(workspace, relative)
        for relative in committed_files
    }
    if final_hashes != report.get("content_sha256", {}):
        raise RuntimeError("Task commit content does not match captured evidence")

    report["task_commit"] = commit
    report["commit_verified"] = True
    report["committed_files"] = committed_files
    report["finalized_at"] = datetime.now(timezone.utc).isoformat()
    report["final_state"] = "PASSED"
    packet = report["evidence_packet"]
    packet["status"] = "PASS"
    packet["final_state"] = "PASSED"
    packet["commit"] = commit
    packet["changed_files"] = committed_files
    packet["notes"] = "Pre-commit evidence and exact task commit verified."
    packet.setdefault("checks", []).append({
        "name": "verified task commit", "passed": True, "state": "PASSED"
    })
    packet.setdefault("observations", []).append(f"task_commit={commit}")
    _packet_rehash(packet)
    _write_json_atomic(snapshot_path, report)
    return snapshot_path, report


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
