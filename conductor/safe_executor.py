import os
import shlex
import sys
import re
from pathlib import Path

try:
    from .process_runner import run_bounded
except ImportError:
    from process_runner import run_bounded

TIMEOUT = 300
SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+")

EXACT_COMMANDS = {
    ("git", "status"),
    ("git", "status", "--short"),
    ("git", "diff"),
    ("git", "diff", "--check"),
    ("git", "diff", "--cached"),
    ("git", "log", "--oneline", "-10"),

    (
        "python3", "-m", "compileall",
        "-q", "conductor", "tests"
    ),

    (
        "python3", "-m", "unittest",
        "discover",
        "-s", "tests",
        "-p", "test_*.py",
        "-v"
    ),
}


def validate_workspace(workspace):
    root = Path(workspace).expanduser().resolve()

    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise ValueError("Invalid workspace")

    return root


def redact(text):
    return SECRET_RE.sub(lambda m: m.group(1) + "=<REDACTED>", str(text))


def is_allowed(parts):
    return tuple(parts) in EXACT_COMMANDS


def run_safe(workspace, command_text):
    root = validate_workspace(workspace)

    parts = shlex.split(command_text)

    if not parts:
        raise ValueError("Empty command")

    if not is_allowed(parts):
        raise PermissionError(
            "Command is not an exact approved command"
        )

    safe_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "CI": "true",
    }

    result = run_bounded(
        parts,
        cwd=root,
        timeout=TIMEOUT,
        env=safe_env,
        merge_env=False,
    )

    print("=== MIGZ SAFE EXECUTOR ===")
    print(f"Workspace : {root}")
    print(f"Command   : {' '.join(parts)}")
    print(f"Exit Code : {result.returncode}")

    if result.stdout:
        print("\n=== STDOUT ===")
        print(redact(result.stdout.rstrip()))

    if result.stderr:
        print("\n=== STDERR ===")
        print(redact(result.stderr.rstrip()))

    print(
        "\nEXECUTOR  : "
        + (
            "PASS"
            if result.returncode == 0
            else "COMMAND_FAILED"
        )
    )

    return result.returncode


def main():
    if len(sys.argv) < 3:
        print(
            'Usage: python3 conductor/safe_executor.py '
            '<workspace> "<command>"'
        )
        raise SystemExit(1)

    try:
        code = run_safe(
            sys.argv[1],
            " ".join(sys.argv[2:])
        )
        raise SystemExit(code)

    except Exception as exc:
        print("EXECUTOR  : BLOCKED")
        print(f"ERROR     : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
