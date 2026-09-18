"""Portable operational diagnostic for MIGZ AI Orchestra."""

import argparse
import json
from pathlib import Path

from agent_backend_router import AgentBackendRouter
from decision_layer import DecisionLayer
from health_check import diagnose_ollama
from project_scheduler import ProjectScheduler
from runtime_env import codex_executable, optional_path
from task_engine import TaskStore
from process_runner import run_bounded
from version import ORCHESTRA_CODENAME, ORCHESTRA_NAME, ORCHESTRA_VERSION


def _git(repo, *args):
    result = run_bounded(
        ["git", *args], cwd=repo, timeout=30,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _telegram_state():
    path = optional_path("MIGZ_WAR_ROOM_STATE")
    if not path:
        return {"status": "NOT_CONFIGURED"}
    if not path.exists():
        return {"status": "UNAVAILABLE", "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {
            "status": "PASS",
            "mode": raw.get("mode"),
            "paused": raw.get("paused"),
            "active_run": raw.get("active_run"),
        }
    except (OSError, ValueError):
        return {"status": "UNAVAILABLE", "path": str(path)}


def doctor(repo=None, probe=False):
    root = Path(repo or Path(__file__).resolve().parents[1]).expanduser().resolve()
    store = TaskStore(root / "tasks")
    counts = {
        state: len(list((store.root / state).glob("*.json")))
        for state in ("pending", "running", "review", "passed", "blocked")
    }
    scheduler = ProjectScheduler(root / "state" / "projects.json", root / "state" / "scheduler")
    try:
        ollama = diagnose_ollama(retries=1, timeout=5)
    except Exception as exc:
        ollama = {"status": "UNAVAILABLE", "error": type(exc).__name__}

    router = AgentBackendRouter(repo=root)
    lane_snapshot = router.lane_states(probe=probe)
    backends = router.as_json(lanes=lane_snapshot)
    lanes = router.model_states(lanes=lane_snapshot)
    jev = DecisionLayer().status(root)
    telegram = _telegram_state()
    skill_path = optional_path("MIGZ_CODEX_SKILL_PATH")
    skill_status = "PASS" if skill_path and skill_path.exists() else "NOT_CONFIGURED"
    codex_bin = codex_executable()
    codex_status = "AVAILABLE" if codex_bin else "NOT_CONFIGURED"

    _, worktree_text, _ = _git(root, "worktree", "list", "--porcelain")
    worktrees = len([line for line in worktree_text.splitlines() if line.startswith("worktree ")])
    native_state = backends.get("native", {}).get("status", "UNAVAILABLE")
    accepted_native = {"HEALTHY"} if probe else {"HEALTHY", "AVAILABLE"}
    native_gate = native_state in accepted_native
    model_gate = lanes.get("qwen-fast", {}).get("status") in (
        {"PASS"} if probe else {"PASS", "AVAILABLE"}
    )

    result = {
        "schema": "migz.orchestra.doctor.v4",
        "identity": {
            "name": ORCHESTRA_NAME,
            "version": ORCHESTRA_VERSION,
            "codename": ORCHESTRA_CODENAME,
        },
        "core": {
            "task_engine": "PASS",
            "scheduler": scheduler.summary(),
            "safe_writer": "PASS",
            "safe_executor": "PASS",
            "worktrees": {"count": worktrees, "git": "PASS" if worktrees >= 1 else "UNAVAILABLE"},
        },
        "models": {
            "qwen_fast": lanes.get("qwen-fast", {"status": "UNAVAILABLE"}),
            "qwen_coding": lanes.get("qwen-coding", {"status": "UNAVAILABLE"}),
            "qwen_reasoning": lanes.get("qwen-reasoning", {"status": "UNAVAILABLE"}),
            "deepseek_local": lanes.get("deepseek", {"status": "UNAVAILABLE"}),
        },
        "backends": backends,
        "providers": {
            "ollama": ollama,
            "jev_optional": jev,
        },
        "integrations": {
            "codex": {"status": codex_status, "executable": codex_bin},
            "jev": jev,
            "telegram": telegram,
            "codex_skill": {"status": skill_status, "path": str(skill_path) if skill_path else None},
            "aider": backends.get("aider", {"status": "UNAVAILABLE"}),
            "hermes": backends.get("hermes", {"status": "UNAVAILABLE"}),
            "openhands": backends.get("openhands", {"status": "UNAVAILABLE"}),
            "deepseek_local": backends.get("deepseek", {"status": "UNAVAILABLE"}),
        },
        "control": {
            "authority": {
                "recommended_brain": "codex",
                "recommended_final_reviewer": "codex",
                "independent_qa": "terra",
                "codex_status": codex_status,
            }
        },
        "runtime": {
            **counts,
            "heavy_local_busy": scheduler.summary().get("heavy_local_busy"),
        },
    }
    gates = {
        "ollama": ollama.get("status") == "PASS",
        "native_backend": native_gate,
        "required_models": model_gate,
        "git_worktree": worktrees >= 1,
    }
    result["core_gates"] = gates
    result["overall"] = "PASS" if all(gates.values()) else "DEGRADED"
    return result


def main():
    parser = argparse.ArgumentParser(description="Diagnose MIGZ AI Orchestra core and optional integrations")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--probe", action="store_true", help="run bounded live model probes")
    args = parser.parse_args()
    result = doctor(args.repo, args.probe)
    print(f"=== {ORCHESTRA_NAME} V{ORCHESTRA_VERSION} DOCTOR ===")
    print(f"Codename : {ORCHESTRA_CODENAME}")
    print(f"Core     : {result['overall']}")
    print(f"Ollama   : {result['providers']['ollama'].get('status')}")
    print(f"Native   : {result['backends'].get('native', {}).get('status')}")
    print(f"Codex    : {result['integrations']['codex']['status']} (optional authority integration)")
    print(f"JEV      : {result['integrations']['jev'].get('status')} (optional decision layer)")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("ORCHESTRA_DOCTOR: " + result["overall"])
    raise SystemExit(0 if result["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
