#!/usr/bin/env python3
"""Fail CI if public-source hygiene regresses."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_EXTENSIONS = {
    ".py", ".sh", ".ps1", ".md", ".yml", ".yaml", ".json",
    ".toml", ".txt", ".example", "",
}

BANNED_PATTERNS = {
    "private key": re.compile(r"BEGIN (?:RSA|OPENSSH|EC|PRIVATE) KEY"),
    "github token": re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    "openai-style secret": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "telegram bot token": re.compile(r"bot?\d{6,}:[A-Za-z0-9_-]{20,}"),
    "windows user path": re.compile(r"(?:/mnt/[a-z]/Users/|[A-Za-z]:\\\\Users\\\\)"),
    "hardcoded unix home": re.compile(r"/home/[A-Za-z0-9._-]+/"),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True,
        text=True, timeout=30, shell=False, check=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    findings: list[str] = []
    forbidden_roots = {"tasks", "state", "evidence", "logs"}
    for path in tracked_files():
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] in forbidden_roots:
            findings.append(f"tracked runtime state: {rel}")
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS and path.name not in {"LICENSE", "Makefile", "orchestra"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in BANNED_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {rel}")

    if findings:
        print("PUBLIC_SAFETY_SCAN: FAIL")
        for item in sorted(set(findings)):
            print(f"- {item}")
        return 1

    print("PUBLIC_SAFETY_SCAN: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
