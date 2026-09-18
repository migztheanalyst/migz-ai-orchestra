import json
import os
import sys
import urllib.request
from pathlib import Path, PurePosixPath

from model_router import route_model
from provider_router import ollama_models
from runtime_env import resolve_ollama_base
from safe_writer import safe_write

EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "node_modules",
    "__pycache__", "dist", "build", ".next",
    ".cache", "evidence",
}

ALLOWED_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".md", ".txt", ".yml", ".yaml",
    ".toml", ".css", ".html",
}

BLOCKED_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
}

MAX_CONTEXT_CHARS = 16000
MAX_FILE_BYTES = 30000
MAX_WRITES = 8


def validate_write_path(relative_path):
    path = PurePosixPath(relative_path)

    if path.is_absolute():
        raise PermissionError("Absolute path blocked")

    if ".." in path.parts:
        raise PermissionError("Path traversal blocked")

    if ".git" in path.parts:
        raise PermissionError(".git modification blocked")

    if path.name in BLOCKED_NAMES:
        raise PermissionError("Sensitive file blocked")

    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise PermissionError(
            f"Unsupported file type: {path.suffix}"
        )

    return str(path)


def collect_context(workspace):
    root = Path(workspace).resolve()
    blocks = []
    total = 0

    for current_root, dirnames, filenames in os.walk(
        root,
        followlinks=False,
    ):
        current = Path(current_root)

        dirnames[:] = [
            name
            for name in dirnames
            if name not in EXCLUDED_DIRS
            and not (current / name).is_symlink()
        ]

        for name in sorted(filenames):
            path = current / name

            if path.is_symlink():
                continue

            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue

            if path.stat().st_size > MAX_FILE_BYTES:
                continue

            content = path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            rel = path.relative_to(root)

            block = (
                f"\n--- FILE: {rel} ---\n"
                + content
                + "\n"
            )

            if total + len(block) > MAX_CONTEXT_CHARS:
                return "".join(blocks)

            blocks.append(block)
            total += len(block)

    return "".join(blocks)


def ask_builder(workspace, objective):
    endpoint = resolve_ollama_base()

    model = os.environ.get("MIGZ_MODEL") or route_model("coding", ollama_models(endpoint))

    context = collect_context(workspace)

    schema = {
        "summary": "short implementation summary",
        "writes": [
            {
                "path": "relative/path.ext",
                "content": "complete file content",
            }
        ],
        "notes": "short notes",
    }

    prompt = (
        "You are Builder Agent inside MIGZ AI ORCHESTRA.\n"
        "Implement the objective using ONLY file writes.\n"
        "Return complete replacement contents for every file "
        "you modify or create.\n"
        "Never modify .git, secrets, credentials, or .env.\n"
        "Do not claim tests were executed.\n"
        "Keep changes minimal and directly related to the objective.\n\n"
        f"OBJECTIVE:\n{objective}\n\n"
        f"PROJECT CONTENT:\n{context}\n\n"
        "Return ONLY JSON matching:\n"
        + json.dumps(schema)
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 1800,
        },
    }

    request = urllib.request.Request(
        endpoint + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=1200,
    ) as response:
        raw = json.load(response)

    if raw.get("done_reason") == "length":
        raise RuntimeError("Builder output truncated")

    result = json.loads(
        raw["message"]["content"]
    )

    if not isinstance(result.get("writes"), list):
        raise RuntimeError("Builder writes missing")

    if not result["writes"]:
        raise RuntimeError("Builder produced no changes")

    if len(result["writes"]) > MAX_WRITES:
        raise RuntimeError("Too many file writes")

    return model, result


def apply_plan(workspace, plan):
    written = []

    for item in plan["writes"]:
        if not isinstance(item, dict):
            raise RuntimeError("Invalid write item")

        path = validate_write_path(
            item.get("path", "")
        )

        content = item.get("content")

        if not isinstance(content, str):
            raise RuntimeError(
                f"Invalid content for {path}"
            )

        safe_write(
            workspace,
            path,
            content,
        )

        written.append(path)

    return written


def main():
    if len(sys.argv) < 3:
        print(
            'Usage: python3 conductor/builder_agent.py '
            '<workspace> "<objective>"'
        )
        raise SystemExit(1)

    workspace = Path(
        sys.argv[1]
    ).expanduser().resolve()

    objective = " ".join(
        sys.argv[2:]
    ).strip()

    try:
        print("=== MIGZ BUILDER AGENT ===")
        print(f"Workspace : {workspace}")
        print("Status    : PLANNING")

        model, plan = ask_builder(
            workspace,
            objective,
        )

        print(f"Model     : {model}")

        written = apply_plan(
            workspace,
            plan,
        )

        report = {
            "backend": os.environ.get("MIGZ_BACKEND", "native"),
            "provider": os.environ.get("MIGZ_PROVIDER", "ollama"),
            "model": model,
            "summary": plan.get(
                "summary",
                "",
            ),
            "writes": written,
            "notes": plan.get(
                "notes",
                "",
            ),
        }

        evidence = workspace / "evidence"
        evidence.mkdir(exist_ok=True)

        output = evidence / "builder-latest.json"

        output.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )

        print(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            )
        )
        print("BUILDER   : PASS")

    except Exception as exc:
        print("BUILDER   : FAIL")
        print(f"ERROR     : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
