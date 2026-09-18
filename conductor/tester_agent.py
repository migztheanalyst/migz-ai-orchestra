import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .process_runner import run_bounded
except ImportError:
    from process_runner import run_bounded


TESTS = [
    [
        "python3",
        "-m",
        "compileall",
        "-q",
        "conductor",
        "tests",
    ],
    [
        "python3",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-p",
        "test_*.py",
        "-v",
    ],
    [
        "git",
        "diff",
        "--check",
    ],
    [
        "python3",
        "scripts/core_entrypoint_smoke.py",
    ],
]


def run_test(root, command):
    result = run_bounded(
        command,
        cwd=root,
        timeout=300,
    )

    return {
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout[-8000:],
        "stderr": result.stderr[-8000:],
        "passed": result.returncode == 0,
    }


def main():
    workspace = (
        Path(sys.argv[1]).expanduser().resolve()
        if len(sys.argv) > 1
        else Path.cwd().resolve()
    )

    if not workspace.is_dir():
        raise SystemExit("Invalid workspace")

    print("=== MIGZ TESTER AGENT ===")
    print(f"Workspace : {workspace}")
    print()

    results = []

    for command in TESTS:
        print("RUN:", " ".join(command))

        result = run_test(
            workspace,
            command
        )

        results.append(result)

        print(
            "PASS"
            if result["passed"]
            else "FAIL"
        )

    passed = all(
        item["passed"]
        for item in results
    )

    report = {
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "workspace": str(workspace),
        "tests": results,
        "overall": (
            "PASS"
            if passed
            else "FAIL"
        ),
    }

    evidence = workspace / "evidence"
    evidence.mkdir(exist_ok=True)

    output = evidence / "tester-latest.json"

    output.write_text(
        json.dumps(
            report,
            indent=2
        )
    )

    print()
    print(f"Evidence  : {output}")
    print(
        "TESTER    : "
        + report["overall"]
    )

    raise SystemExit(
        0 if passed else 1
    )


if __name__ == "__main__":
    main()
