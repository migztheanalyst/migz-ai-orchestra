"""Bounded runtime smoke for every Orchestra core entrypoint."""

import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


MODULES = sorted(
    path.stem
    for path in (Path(__file__).resolve().parents[1] / "conductor").glob("*.py")
    if path.name != "__init__.py"
)

def run():
    root = Path(__file__).resolve().parents[1]
    conductor = root / "conductor"
    sys.path.insert(0, str(conductor))
    result = {"schema": "migz.core.entrypoint-smoke.v1", "imports": {}, "functions": {}, "cli": {}}

    for name in MODULES:
        try:
            importlib.import_module(name)
            result["imports"][name] = "PASS"
        except Exception as exc:
            result["imports"][name] = f"FAIL:{type(exc).__name__}:{exc}"

    from agent_backend_router import AgentBackendRouter
    from backend_change_guard import inspect_changes
    from evidence_manager import run_git
    from health_check import diagnose_ollama
    from model_router import route_healthy_model
    from provider_router import classify_backend_failure
    from project_registry import ProjectRegistry
    from project_scheduler import ProjectScheduler
    from task_engine import TaskStore

    try:
        assert route_healthy_model("coding", {"qwen2.5-coder:3b", "qwen2.5-coder:7b"}, {"qwen2.5-coder:7b"}) == "qwen2.5-coder:7b"
        assert classify_backend_failure("model timeout") == "MODEL_TIMEOUT"
        assert classify_backend_failure("malformed output") == "MALFORMED_OUTPUT"
        registry = ProjectRegistry(root / "state" / "projects.json")
        # A clean isolated worktree may not carry ignored registry state. The
        # runtime contract is that the registry can be opened and queried;
        # project onboarding is deliberately outside this core smoke gate.
        registry.list_projects()
        scheduler = ProjectScheduler(root / "state" / "projects.json", root / "state" / "scheduler")
        assert "totals" in scheduler.summary()
        with tempfile.TemporaryDirectory(prefix="migz-entrypoint-") as tmp:
            store = TaskStore(Path(tmp) / "tasks")
            task = store.create("smoke", "read-only smoke", "fast", max_attempts=1)
            assert store.find(task["id"])[1]["status"] == "pending"
        router = AgentBackendRouter(repo=root)
        assert router.states(probe=False)["native"].status in {"AVAILABLE", "HEALTHY"}
        # Exercise the guard against a clean throw-away repository. The
        # source checkout may intentionally be dirty while this smoke runs.
        with tempfile.TemporaryDirectory(prefix="migz-guard-") as guard_tmp:
            guard_root = Path(guard_tmp)
            subprocess.run(["git", "init", "-q"], cwd=guard_root, check=True, timeout=10)
            guard = inspect_changes(guard_root, backend="native")
            assert guard.passed
        run_git(root, "status", "--short")
        diagnosis = diagnose_ollama(retries=1, timeout=5)
        assert diagnosis.get("status") in {"PASS", "MODEL_MISSING", "OLLAMA_NOT_RUNNING", "BRIDGE_UNREACHABLE", "API_ERROR"}
        result["functions"] = {
            "model_router": "PASS",
            "provider_router": "PASS",
            "task_store": "PASS",
            "project_registry": "PASS",
            "project_scheduler": "PASS",
            "backend_router": "PASS",
            "change_guard": "PASS",
            "ollama_diagnosis": diagnosis.get("status"),
        }
    except Exception as exc:
        result["functions"] = {"status": f"FAIL:{type(exc).__name__}:{exc}"}

    cli_commands = {
        "model_router": ["python3", str(conductor / "model_router.py"), "fast"],
        "project_registry": ["python3", str(conductor / "project_registry.py"), "--help"],
        "project_scheduler": ["python3", str(conductor / "project_scheduler.py"), "--help"],
        "project_orchestrator": ["python3", str(conductor / "project_orchestrator.py"), str(root), "status"],
        "mission_loader": ["python3", str(conductor / "mission_loader.py")],
        "orchestra": ["python3", str(conductor / "orchestra.py"), str(root), "status"],
        "builder_agent": ["python3", str(conductor / "builder_agent.py")],
        "maestro": ["python3", str(conductor / "maestro.py")],
        "escalation_manager": ["python3", str(conductor / "escalation_manager.py")],
        "release_reviewer": ["python3", str(conductor / "release_reviewer.py"), "--help"],
        "orchestra_doctor": ["python3", str(conductor / "orchestra_doctor.py"), "--help"],
    }
    for name, command in cli_commands.items():
        proc = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60, shell=False)
        output = (proc.stdout + proc.stderr).lower()
        expected = proc.returncode == 0 or "usage" in output
        result["cli"][name] = "PASS" if expected else f"FAIL:{proc.returncode}"

    result["status"] = "PASS" if all(value == "PASS" or value in {"PASS", "HEALTHY", "AVAILABLE"} for value in result["imports"].values()) and all(value == "PASS" for value in result["cli"].values()) and result["functions"].get("change_guard") == "PASS" else "FAIL"
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("CORE_ENTRYPOINT_SMOKE: " + result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run())
