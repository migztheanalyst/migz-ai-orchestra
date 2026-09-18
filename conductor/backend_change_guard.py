"""Common fail-closed post-edit gate for every modifying backend."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from .process_runner import run_bounded
except ImportError:
    from process_runner import run_bounded


MAX_FILES = 16
MAX_DELETED_LINES = 2000
SECRET_DIFF_RE = re.compile(r"(?i)(api[_-]?key|access[_-]?token|password|secret|private[_-]?key)\s*[:=]\s*[^\s,;]+")
PROTECTED_PARTS = {".git", ".env", ".env.local", ".env.production", "credentials"}


@dataclass(frozen=True)
class ChangeGuardResult:
    passed: bool
    backend: str
    files: tuple[str, ...]
    violations: tuple[str, ...]
    added_lines: int
    deleted_lines: int
    suspicious_deletions: bool
    unexpected_binary: bool


def _git(root, *args):
    result = run_bounded(
        ["git", *args],
        cwd=root,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git command failed")
    return result.stdout


def _normalize(path):
    path = str(path).replace("\\", "/").strip()
    if not path or path.startswith("/") or ":" in path.split("/")[0]:
        raise ValueError(f"absolute path: {path}")
    parts = tuple(part for part in path.split("/") if part)
    if ".." in parts or any(part.lower() in PROTECTED_PARTS or part.lower().startswith(".env.") for part in parts):
        raise ValueError(f"protected path: {path}")
    return "/".join(parts)


def _status_paths(status):
    paths = []
    for line in status.splitlines():
        if not line:
            continue
        raw = line[3:] if len(line) >= 3 else ""
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[-1]
        paths.append(raw)
    return paths


def _allowed(path, allowed_scope):
    if not allowed_scope:
        return True
    for item in allowed_scope:
        item = str(item).replace("\\", "/").rstrip("/")
        if path == item or path.startswith(item + "/"):
            return True
    return False


def inspect_changes(workspace, backend="native", allowed_scope=None, managed_root=None):
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Invalid backend workspace")
    detected = Path(_git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    if detected != root:
        raise ValueError("Backend workspace is not the Git root")
    violations = []
    if managed_root is not None:
        expected = Path(managed_root).expanduser().resolve()
        if root.parent != expected:
            violations.append("worktree is outside managed task root")

    status = _git(root, "status", "--porcelain=v1", "-uall")
    paths = []
    for raw in _status_paths(status):
        try:
            paths.append(_normalize(raw))
        except ValueError as exc:
            violations.append(str(exc))
    paths = sorted(set(paths))
    if len(paths) > MAX_FILES:
        violations.append(f"too many changed files: {len(paths)}")
    for path in paths:
        if not _allowed(path, allowed_scope):
            violations.append(f"outside allowed scope: {path}")
        full = root / path
        try:
            full.relative_to(root)
        except ValueError:
            violations.append(f"path escapes worktree: {path}")
            continue
        parts = full.relative_to(root).parts
        current = root
        for part in parts:
            current = current / part
            if current.is_symlink():
                violations.append(f"symlink path: {path}")
                break
        if full.exists() and full.is_file():
            sample = full.read_bytes()[:4096]
            if b"\x00" in sample:
                violations.append(f"unexpected binary addition: {path}")

    diff = _git(root, "diff", "--no-ext-diff") + _git(root, "diff", "--cached", "--no-ext-diff")
    if SECRET_DIFF_RE.search(diff):
        violations.append("secret-like assignment detected in diff")
    added_lines = 0
    deleted_lines = 0
    for row in _git(root, "diff", "--numstat").splitlines():
        fields = row.split("\t")
        if len(fields) >= 2:
            try:
                added_lines += int(fields[0])
                deleted_lines += int(fields[1])
            except ValueError:
                continue
    suspicious = deleted_lines > MAX_DELETED_LINES
    if suspicious:
        violations.append(f"suspicious deletion volume: {deleted_lines} lines")
    return ChangeGuardResult(
        not violations, str(backend), tuple(paths), tuple(violations),
        added_lines, deleted_lines, suspicious,
        any("unexpected binary" in item for item in violations),
    )


def write_report(workspace, result, provider=None, model=None, retries=0, fallback=None):
    root = Path(workspace).expanduser().resolve()
    payload = asdict(result)
    payload.update({
        "schema": "migz.backend-change-guard.v1",
        "provider": provider,
        "model": model,
        "retries": int(retries or 0),
        "fallback": fallback,
        "state": "PASSED" if result.passed else "BLOCKED",
    })
    output = root / "evidence" / "backend-guard.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output, payload
