import os
import sys
from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".cache",
}

MAX_FILES = 500


def inspect_project(workspace):
    root = Path(workspace).expanduser().resolve()

    if not root.exists():
        raise FileNotFoundError(f"Workspace does not exist: {root}")

    if not root.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {root}")

    files = []
    directories = set()

    for current_root, dirnames, filenames in os.walk(
        root,
        followlinks=False,
    ):
        current_path = Path(current_root)

        dirnames[:] = [
            name
            for name in dirnames
            if name not in EXCLUDED_DIRS
            and not (current_path / name).is_symlink()
        ]

        for dirname in dirnames:
            path = current_path / dirname
            directories.add(path.relative_to(root))

        for filename in filenames:
            path = current_path / filename

            if path.is_symlink():
                continue

            files.append(path.relative_to(root))

            if len(files) >= MAX_FILES:
                break

        if len(files) >= MAX_FILES:
            break

    print("=== MIGZ PROJECT INSPECTOR ===")
    print(f"Workspace    : {root}")
    print("Mode         : READ-ONLY")
    print(f"Directories  : {len(directories)}")
    print(f"Files        : {len(files)}")

    print("\nProject structure:")

    for path in sorted(directories):
        print(f"[DIR]  {path}")

    for path in sorted(files):
        print(f"[FILE] {path}")

    if len(files) >= MAX_FILES:
        print(f"\nWARNING: Output limited to {MAX_FILES} files.")

    print("\nINSPECTOR    : PASS")


def main():
    if len(sys.argv) != 2:
        print(
            "Usage: python3 conductor/project_inspector.py "
            "<workspace>"
        )
        raise SystemExit(1)

    try:
        inspect_project(sys.argv[1])
    except Exception as exc:
        print("INSPECTOR    : FAIL")
        print(f"ERROR        : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
