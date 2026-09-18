import json
import os
import sys
import urllib.request
from pathlib import Path

from model_router import route_model
from process_runner import run_bounded
from provider_router import ollama_models
from runtime_env import resolve_ollama_base

MAX_EVIDENCE = 30000


def run_git(root, *args):
    result = run_bounded(
        ["git", *args],
        cwd=root,
        timeout=60,
    )

    return result.stdout + result.stderr


def load_test_evidence(root):
    path = root / "evidence" / "tester-latest.json"

    if not path.exists():
        raise RuntimeError(
            "Tester evidence is missing"
        )

    data = json.loads(path.read_text())

    if data.get("overall") != "PASS":
        raise RuntimeError(
            "Tester evidence does not show PASS"
        )

    return data


def collect_evidence(root, tests):
    status = run_git(
        root,
        "status",
        "--short",
        "-uall",
    )

    diff = run_git(
        root,
        "diff",
        "--no-ext-diff",
    )

    diff_stat = run_git(root, "diff", "--stat")
    name_status = run_git(root, "diff", "--name-status")

    backend_path = root / "evidence" / "backend-latest.json"
    guard_path = root / "evidence" / "backend-guard.json"
    backend = json.loads(backend_path.read_text()) if backend_path.exists() else {"status": "UNAVAILABLE"}
    guard = json.loads(guard_path.read_text()) if guard_path.exists() else {"state": "UNAVAILABLE"}

    untracked = []

    for line in status.splitlines():
        if not line.startswith("?? "):
            continue

        rel = line[3:]
        path = root / rel

        if (
            path.is_file()
            and path.stat().st_size < 100000
            and path.suffix in {
                ".py",
                ".json",
                ".md",
                ".txt",
            }
        ):
            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            untracked.append(
                f"\n--- UNTRACKED {rel} ---\n"
                + text
            )

    evidence = (
        "VERIFIED TEST EVIDENCE:\n"
        + json.dumps(tests, indent=2)
        + "\n\nGIT STATUS:\n"
        + status
        + "\n\nTRACKED DIFF:\n"
        + diff
        + "\n\nDIFF STAT:\n"
        + diff_stat
        + "\n\nNAME STATUS:\n"
        + name_status
        + "\n\nBACKEND:\n"
        + json.dumps(backend, indent=2, ensure_ascii=False)
        + "\n\nBACKEND CHANGE GUARD:\n"
        + json.dumps(guard, indent=2, ensure_ascii=False)
        + "\n"
        + "".join(untracked)
    )

    return evidence[:MAX_EVIDENCE]


def hard_scope_blockers(root):
    status = run_git(root, "status", "--short", "-uall")
    blockers = []
    for line in status.splitlines():
        raw = line[3:].strip() if len(line) >= 4 else ""
        path = raw.split(" -> ", 1)[-1]
        normalized = path.replace("\\", "/")
        if normalized.startswith("/") or "../" in normalized or normalized == ".env" or normalized.startswith(".env/") or "/.git/" in ("/" + normalized):
            blockers.append(f"protected or escaping path: {path}")
    backend_path = root / "evidence" / "backend-latest.json"
    guard_path = root / "evidence" / "backend-guard.json"
    if not backend_path.exists():
        blockers.append("backend execution evidence missing")
    if not guard_path.exists():
        blockers.append("backend change guard evidence missing")
    else:
        try:
            guard = json.loads(guard_path.read_text())
            if guard.get("state") != "PASSED":
                blockers.append("backend change guard did not pass")
        except (OSError, ValueError):
            blockers.append("backend change guard evidence is malformed")
    return blockers


def call_reviewer(evidence):
    endpoint = resolve_ollama_base()
    model = os.environ.get("MIGZ_REVIEW_MODEL") or os.environ.get("MIGZ_MODEL") or route_model("review", ollama_models(endpoint))

    schema = {
        "decision": "PASS or FAIL",
        "summary": "short factual assessment",
        "blockers": [],
        "risk": "LOW, MEDIUM, or HIGH",
    }

    prompt = (
        "You are an independent security and code reviewer "
        "inside MIGZ AI ORCHESTRA.\n"
        "Use ONLY the supplied evidence.\n"
        "Tests marked PASS are verified evidence.\n"
        "Fail only for a CONCRETE defect or security blocker "
        "visible in the supplied implementation.\n"
        "Do not fail for hypothetical risks already prevented "
        "by exact command matching or explicit validation.\n"
        "Unsafe shell=True, unrestricted command execution, "
        "workspace escape, secret exposure, or demonstrated "
        "runtime defects are blockers.\n\n"
        "EVIDENCE:\n"
        + evidence
        + "\n\nReturn ONLY JSON matching:\n"
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
            "num_predict": 350,
        },
    }

    request = urllib.request.Request(
        endpoint + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type":
            "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=900,
    ) as response:
        raw = json.load(response)

    if raw.get("done_reason") == "length":
        raise RuntimeError(
            "Reviewer output truncated"
        )

    result = json.loads(
        raw["message"]["content"]
    )

    required = {
        "decision",
        "summary",
        "blockers",
        "risk",
    }

    if not required.issubset(result):
        raise RuntimeError(
            "Reviewer JSON incomplete"
        )

    if result["decision"] not in {
        "PASS",
        "FAIL",
    }:
        raise RuntimeError(
            "Invalid reviewer decision"
        )

    return model, result


def main():
    root = (
        Path(sys.argv[1]).expanduser().resolve()
        if len(sys.argv) > 1
        else Path.cwd().resolve()
    )

    print("=== MIGZ REVIEWER AGENT ===")

    try:
        tests = load_test_evidence(root)
        evidence = collect_evidence(
            root,
            tests,
        )

        model, result = call_reviewer(
            evidence
        )

        result["backend"] = "terra-review"
        result["provider"] = os.environ.get("MIGZ_PROVIDER", "ollama")
        result["model"] = model
        blockers = hard_scope_blockers(root)
        if blockers:
            result["decision"] = "FAIL"
            result["blockers"] = list(result.get("blockers", [])) + blockers
            result["summary"] = "Hard safety/scope validation rejected the change before approval."

        print(f"Provider : ollama")
        print(f"Model    : {model}")

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

        output = (
            root
            / "evidence"
            / "reviewer-latest.json"
        )

        output.parent.mkdir(exist_ok=True)

        output.write_text(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

        print(f"Evidence : {output}")
        print(
            "REVIEWER : "
            + result["decision"]
        )

        raise SystemExit(
            0
            if result["decision"] == "PASS"
            else 1
        )

    except Exception as exc:
        print("REVIEWER : FAIL")
        print(f"ERROR    : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
