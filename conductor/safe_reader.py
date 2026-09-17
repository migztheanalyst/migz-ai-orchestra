import sys
from pathlib import Path

MAX_BYTES = 200_000


def safe_read(workspace, relative_path):
    root = Path(workspace).expanduser().resolve()
    target = (root / relative_path).resolve()

    if not root.exists() or not root.is_dir():
        raise ValueError("Invalid workspace")

    try:
        target.relative_to(root)
    except ValueError:
        raise PermissionError("Path escapes workspace")

    if not target.exists():
        raise FileNotFoundError(f"File not found: {relative_path}")

    if not target.is_file():
        raise ValueError("Target is not a regular file")

    if target.is_symlink():
        raise PermissionError("Symlink files are not allowed")

    size = target.stat().st_size

    if size > MAX_BYTES:
        raise ValueError(
            f"File too large: {size} bytes "
            f"(limit {MAX_BYTES})"
        )

    try:
        content = target.read_text(
            encoding="utf-8",
            errors="replace"
        )
    except Exception as exc:
        raise RuntimeError(f"Could not read file: {exc}")

    print("=== MIGZ SAFE FILE READER ===")
    print(f"Workspace : {root}")
    print(f"File      : {target.relative_to(root)}")
    print(f"Bytes     : {size}")
    print("Mode      : READ-ONLY")
    print()
    print("=== CONTENT ===")
    print(content)
    print()
    print("READER    : PASS")


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 conductor/safe_reader.py "
            "<workspace> <relative-file>"
        )
        raise SystemExit(1)

    try:
        safe_read(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print("READER    : FAIL")
        print(f"ERROR     : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
