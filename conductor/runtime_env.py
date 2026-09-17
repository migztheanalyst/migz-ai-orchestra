"""Portable runtime discovery helpers for MIGZ AI Orchestra."""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path


def is_wsl() -> bool:
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
        return "microsoft" in text or "wsl" in text
    except OSError:
        return False


def wsl_gateway() -> str | None:
    if not is_wsl():
        return None
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"], capture_output=True,
            text=True, timeout=5, shell=False,
        )
        parts = result.stdout.split()
        return parts[parts.index("via") + 1] if result.returncode == 0 and "via" in parts else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def ollama_candidates() -> list[str]:
    configured = os.environ.get("OLLAMA_BASE_URL")
    candidates = [configured] if configured else []
    candidates.append("http://127.0.0.1:11434")
    gateway = wsl_gateway()
    if gateway:
        candidates.append(f"http://{gateway}:11434")
    return list(dict.fromkeys(item.rstrip("/") for item in candidates if item))


def resolve_ollama_base(timeout: float = 1.5) -> str:
    for base in ollama_candidates():
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=timeout):
                return base
        except Exception:
            continue
    return ollama_candidates()[0]


def executable_path(name: str, candidates=()) -> str | None:
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return shutil.which(name)


def optional_path(env_name: str) -> Path | None:
    value = os.environ.get(env_name)
    return Path(value).expanduser().resolve() if value else None


def codex_executable() -> str | None:
    configured = os.environ.get("MIGZ_CODEX_BIN")
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_file() else None
    for name in ("codex", "codex.exe"):
        found = shutil.which(name)
        if found:
            return found
    if is_wsl() and shutil.which("powershell.exe"):
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", "(Get-Command codex -ErrorAction SilentlyContinue).Source"],
                capture_output=True, text=True, timeout=8, shell=False,
            )
            value = result.stdout.strip().replace("\\", "/")
            if result.returncode == 0 and value:
                return value
        except (OSError, subprocess.SubprocessError):
            pass
    return None
