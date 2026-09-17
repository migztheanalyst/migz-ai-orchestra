import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath


MAX_BYTES = 1_000_000
BLOCKED_NAMES = {".env", ".git", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials"}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}
SECRET_NAME_RE = re.compile(r"(^|[-_.])(secret|secrets|token|password|passwd|apikey|api_key)([-_.]|$)", re.I)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _relative_parts(relative_path):
    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise PermissionError("Invalid relative path")
    normalized = relative_path.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ":" in path.parts[0] if path.parts else True:
        raise PermissionError("Absolute path blocked")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise PermissionError("Path traversal blocked")
    return path.parts


def _check_parts(parts):
    lowered = [part.lower() for part in parts]
    if any(part in {".git", ".env"} or part.startswith(".env.") for part in lowered):
        raise PermissionError("Protected path blocked")
    for part in parts:
        name = part.lower()
        if name in BLOCKED_NAMES or name.endswith(tuple(BLOCKED_SUFFIXES)) or SECRET_NAME_RE.search(name):
            raise PermissionError("Sensitive file blocked")


def _check_no_symlink(root, parts):
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise PermissionError("Symlink path is forbidden")


def safe_write(workspace, relative_path, content):
    root = Path(workspace).expanduser().resolve()
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise ValueError("Invalid workspace")
    parts = _relative_parts(relative_path)
    _check_parts(parts)
    _check_no_symlink(root, parts[:-1])
    target = root.joinpath(*parts)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PermissionError("Path escapes workspace") from exc
    if target.exists() and target.is_symlink():
        raise PermissionError("Symlink target is forbidden")
    data = content.encode("utf-8") if isinstance(content, str) else None
    if data is None:
        raise ValueError("Content must be text")
    if len(data) > MAX_BYTES:
        raise ValueError("Content exceeds size limit")
    old_hash = "NEW_FILE" if not target.exists() else sha256(target.read_bytes())
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, delete=False) as temp:
        temp.write(data)
        temp.flush()
        os.fsync(temp.fileno())
        temp_path = Path(temp.name)
    os.replace(temp_path, target)
    new_hash = sha256(target.read_bytes())
    print("=== MIGZ SAFE WRITER ===")
    print(f"Workspace : {root}")
    print(f"File      : {target.relative_to(root)}")
    print(f"Bytes     : {len(data)}")
    print(f"Old SHA   : {old_hash}")
    print(f"New SHA   : {new_hash}")
    print("WRITER    : PASS")


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 conductor/safe_writer.py <workspace> <relative-file>")
        raise SystemExit(1)
    try:
        safe_write(sys.argv[1], sys.argv[2], sys.stdin.read())
    except Exception as exc:
        print("WRITER    : BLOCKED")
        print(f"ERROR     : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
