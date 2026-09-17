#!/usr/bin/env python3
"""Low-resource core-only scheduler, retry and restart acceptance exercise."""

import json
import multiprocessing
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conductor.project_registry import ProjectRegistry
from conductor.project_scheduler import ProjectScheduler


PROJECTS = ["core-alpha", "core-bravo", "core-charlie", "core-delta", "core-echo"]


def make_repo(root, name):
    path = root / name
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, timeout=10)
    return path


def claim_once(registry, state):
    return ProjectScheduler(registry, state).claim_next()


def main():
    output = ROOT / "evidence" / "core-final-closure" / "core-stress.json"
    with tempfile.TemporaryDirectory(prefix="migz-core-stress-") as raw:
        base = Path(raw)
        registry_path = base / "projects.json"
        state_root = base / "scheduler"
        registry = ProjectRegistry(registry_path)
        for project_id in PROJECTS:
            registry.add_project(project_id, project_id, make_repo(base, project_id))
        scheduler = ProjectScheduler(registry_path, state_root)
        for project_id in PROJECTS:
            scheduler.enqueue(project_id, f"success-{project_id}", "bounded core simulation")
            scheduler.enqueue(project_id, f"pending-{project_id}", "bounded core simulation", lane="local-light")

        first_cycle = []
        for _ in PROJECTS:
            task = scheduler.claim_next()
            if not task:
                raise RuntimeError("scheduler lost a fairness-cycle task")
            first_cycle.append(task["project_id"])
            scheduler.finish(task["project_id"], task["id"], passed=True)
        if set(first_cycle) != set(PROJECTS):
            raise RuntimeError("round-robin fairness failed")

        failed = scheduler.claim_next()
        if not failed:
            raise RuntimeError("failure injection task was not claimable")
        scheduler.finish(failed["project_id"], failed["id"], passed=False)
        scheduler.retry(failed["project_id"], failed["id"])
        restarted = ProjectScheduler(registry_path, state_root)
        recovered = next(item for item in restarted.all_tasks() if item["id"] == failed["id"])
        if recovered["status"] != "pending":
            raise RuntimeError("retry did not persist across reload")
        retried = restarted.claim_next()
        restarted.finish(retried["project_id"], retried["id"], passed=True)

        scheduler = ProjectScheduler(registry_path, state_root)
        while True:
            task = scheduler.claim_next()
            if not task:
                break
            scheduler.finish(task["project_id"], task["id"], passed=True)

        race = [scheduler.enqueue(project_id, f"race-{project_id}", "bounded heavy claim") for project_id in PROJECTS]
        ctx = multiprocessing.get_context("fork")
        queue = ctx.Queue()
        # The child return values are sent through a tiny wrapper so the parent
        # can prove there was one claim and no duplicate claim.
        def worker(q):
            q.put(claim_once(registry_path, state_root))
        processes = [ctx.Process(target=worker, args=(queue,)) for _ in range(2)]
        for process in processes:
            process.start()
        results = [queue.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
        claimed = [item for item in results if item]
        if len(claimed) != 1 or len({item["id"] for item in claimed}) != 1:
            raise RuntimeError(f"heavy concurrency violation: {results}")
        winner = claimed[0]
        scheduler.finish(winner["project_id"], winner["id"], passed=True)

        while True:
            task = scheduler.claim_next()
            if not task:
                break
            scheduler.finish(task["project_id"], task["id"], passed=True)

        final = ProjectScheduler(registry_path, state_root).summary()
        all_tasks = ProjectScheduler(registry_path, state_root).all_tasks()
        if any(task["project_id"] not in PROJECTS for task in all_tasks):
            raise RuntimeError("cross-project mutation detected")
        if any(final["totals"][state] for state in ("pending", "running", "review")):
            raise RuntimeError(f"terminal cleanup failed: {final}")
        report = {
            "schema": "migz.core.stress.v1",
            "state": "PASSED",
            "observed": True,
            "logical_projects": PROJECTS,
            "fairness_first_cycle": first_cycle,
            "failure_injection": "PASSED",
            "retry_persistence": "PASSED",
            "restart_reload": "PASSED",
            "duplicate_claims": 0,
            "heavy_local_max": 1,
            "cross_project_mutation": False,
            "terminal_cleanup": "PASSED",
            "final_summary": final,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("CORE_STRESS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
