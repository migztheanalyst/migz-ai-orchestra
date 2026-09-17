"""Portable deterministic release gate for MIGZ AI Orchestra."""

import argparse
import ast
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def run(root, *args, timeout=900):
    result = subprocess.run(
        [str(arg) for arg in args], cwd=root, capture_output=True,
        text=True, timeout=timeout, shell=False,
    )
    return result.returncode, result.stdout + result.stderr


def security_scan(root):
    findings = []
    for path in sorted((root / "conductor").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            findings.append(f"{path.name}:syntax")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "system":
                findings.append(f"{path.name}:os.system")
            if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                findings.append(f"{path.name}:{node.func.id}")
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    findings.append(f"{path.name}:shell_true")
    return sorted(set(findings))


def inspect(repo, expected_branch=None, live=False):
    root = Path(repo).expanduser().resolve()
    checks = []

    def check(name, passed, **extra):
        item = {"name": name, "state": "PASSED" if passed else "BLOCKED"}
        item.update(extra)
        checks.append(item)

    branch_code, branch_text = run(root, "git", "branch", "--show-current")
    branch = branch_text.strip()
    check(
        "branch",
        branch_code == 0 and (expected_branch is None or branch == expected_branch),
        branch=branch,
    )

    commands = (
        ("compile", ["python3", "-m", "compileall", "-q", "conductor", "scripts", "tests"]),
        ("unit", ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"]),
        ("diff", ["git", "diff", "--check"]),
    )
    for name, args in commands:
        code, output = run(root, *args)
        check(name, code == 0, exit_code=code, output_tail=output[-1200:])

    required = [
        "README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md",
        "conductor/orchestra.py", "conductor/orchestra_doctor.py",
        "conductor/agent_backend_router.py", "conductor/provider_router.py",
        "scripts/setup.sh", ".github/workflows/ci.yml",
    ]
    check("public_release_files", all((root / item).exists() for item in required), files=required)
    findings = security_scan(root)
    check("security_scan", not findings, findings=findings)

    if live:
        live_commands = (
            ("doctor_live", ["python3", "conductor/orchestra_doctor.py", "--probe"]),
            ("fallback_canary", ["python3", "scripts/core_fallback_canary.py"]),
            ("core_stress", ["python3", "scripts/core_stress.py"]),
        )
        for name, args in live_commands:
            code, output = run(root, *args, timeout=1200)
            check(name, code == 0, exit_code=code, output_tail=output[-1400:])

    decision = "APPROVED" if all(item["state"] == "PASSED" for item in checks) else "REJECTED"
    result = {
        "schema": "migz.terra.release.v4",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "branch": branch,
        "live": live,
        "checks": checks,
        "decision": decision,
    }
    output = root / "evidence" / "terra-release.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output, result


def main():
    parser = argparse.ArgumentParser(description="Run the deterministic Orchestra release gate")
    parser.add_argument("repo")
    parser.add_argument("--expected-branch")
    parser.add_argument("--live", action="store_true", help="also run bounded live runtime checks")
    args = parser.parse_args()
    output, result = inspect(args.repo, args.expected_branch, args.live)
    print(f"Evidence: {output}")
    print(f"TERRA_RELEASE = {result['decision']}")
    raise SystemExit(0 if result["decision"] == "APPROVED" else 1)


if __name__ == "__main__":
    main()
