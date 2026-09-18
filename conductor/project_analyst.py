import json
import os
import sys
import urllib.request
from pathlib import Path

from model_router import route_model
from runtime_env import resolve_ollama_base

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

ALLOWED_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".md", ".txt", ".yml", ".yaml", ".toml",
}

MAX_FILES = 20
MAX_FILE_BYTES = 30_000
MAX_TOTAL_CHARS = 18_000


def collect_project_context(workspace):
    root = Path(workspace).expanduser().resolve()

    if not root.exists() or not root.is_dir():
        raise ValueError("Invalid workspace")

    collected = []
    total_chars = 0
    capped = False

    for current_root, dirnames, filenames in os.walk(
        root,
        followlinks=False
    ):
        current_path = Path(current_root)

        dirnames[:] = [
            name
            for name in dirnames
            if name not in EXCLUDED_DIRS
            and not (current_path / name).is_symlink()
        ]

        for filename in sorted(filenames):
            path = current_path / filename

            if path.is_symlink():
                continue

            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue

            if path.stat().st_size > MAX_FILE_BYTES:
                continue

            try:
                path.resolve().relative_to(root)
            except ValueError:
                continue

            content = path.read_text(
                encoding="utf-8",
                errors="replace"
            )

            relative = path.relative_to(root)

            block = (
                "\n--- FILE: " + str(relative) + " ---\n"
                + content
                + "\n"
            )

            if total_chars + len(block) > MAX_TOTAL_CHARS:
                capped = True
                break

            collected.append(block)
            total_chars += len(block)

            if len(collected) >= MAX_FILES:
                capped = True
                break

        if capped:
            break

    return root, collected, capped


def call_model(prompt):
    base_url = resolve_ollama_base()

    model = route_model("reasoning")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the read-only Project Analyst inside "
                    "MIGZ AI ORCHESTRA. Analyze only supplied evidence. "
                    "Never claim commands, tests, edits, deployments, "
                    "or capabilities that are not explicitly visible."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 300
        }
    }

    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(
        request,
        timeout=900
    ) as response:
        return json.load(response), model


def validate_analysis(result):
    done_reason = result.get("done_reason", "")
    content = result["message"]["content"].strip()

    if done_reason == "length":
        raise RuntimeError("Model output was truncated")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Model returned invalid JSON: {exc}"
        )

    required = {
        "current_content",
        "verified_working",
        "verified_gaps",
        "next_priority",
    }

    missing = required - set(parsed)

    if missing:
        raise RuntimeError(
            "Missing JSON keys: " + ", ".join(sorted(missing))
        )

    for key in required:
        if not isinstance(parsed[key], str) or not parsed[key].strip():
            raise RuntimeError(
                f"Invalid or empty value for: {key}"
            )

    return parsed, done_reason


def main():
    if len(sys.argv) < 3:
        print(
            'Usage: python3 conductor/project_analyst.py '
            '<workspace> "<question>"'
        )
        raise SystemExit(1)

    workspace = sys.argv[1]
    question = " ".join(sys.argv[2:])

    try:
        root, files, capped = collect_project_context(workspace)

        print("=== MIGZ PROJECT ANALYST ===")
        print(f"Workspace : {root}")
        print("Mode      : READ-ONLY")
        print(f"Files     : {len(files)}")
        print(f"Capped    : {capped}")
        print("Status    : ANALYZING")
        print()

        schema = {
            "current_content": "maximum 2 short sentences",
            "verified_working": "maximum 2 short sentences",
            "verified_gaps": "maximum 2 short sentences",
            "next_priority": "maximum 1 short sentence",
        }

        prompt = (
            "PROJECT WORKSPACE:\n"
            + str(root)
            + "\n\nPROJECT CONTENT:\n"
            + "".join(files)
            + "\n\nUSER QUESTION:\n"
            + question
            + "\n\nReturn ONLY valid JSON matching this exact schema:\n"
            + json.dumps(schema)
            + "\nDo not use markdown. Do not invent anything."
        )

        result, model = call_model(prompt)
        analysis, done_reason = validate_analysis(result)

        print(f"Model     : {model}")
        print()
        print("=== ANALYSIS ===")
        print(json.dumps(
            analysis,
            indent=2,
            ensure_ascii=False
        ))
        print()
        print(f"DONE_REASON : {done_reason or 'unknown'}")
        print("STATUS      : PASS")

    except Exception as exc:
        print()
        print("STATUS      : FAIL")
        print(f"ERROR       : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
