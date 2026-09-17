#!/usr/bin/env python3
"""Bounded, low-resource V2 scheduler acceptance exercise."""

import argparse
import json
import multiprocessing
import subprocess
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from conductor.project_registry import ProjectRegistry
from conductor.project_scheduler import ProjectScheduler


PROJECTS = ["shiletna", "nutrition-canvas", "dose-lens", "sharm-derma", "migz-course"]


def make_repo(root, name):
    path = root / name
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    return path


def claim_once(registry, state):
    scheduler = ProjectScheduler(registry, state)
    task = scheduler.claim_next()
    return task


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="migz-v2-stress-") as raw:
        root = Path(raw)
        registry_path = root / "projects.json"
        state_root = root / "scheduler"
        registry = ProjectRegistry(registry_path)
        for project_id in PROJECTS:
            registry.add_project(project_id, project_id, make_repo(root, project_id))
        scheduler = ProjectScheduler(registry_path, state_root)
        tasks = []
        for project_id in PROJECTS:
            tasks.append(scheduler.enqueue(project_id, f"success-{project_id}", "bounded success"))
            scheduler.enqueue(project_id, f"pending-{project_id}", "bounded pending", lane="local-light")

        first_cycle = []
        for _ in PROJECTS:
            task = scheduler.claim_next()
            if not task:
                raise RuntimeError("scheduler lost a fair-cycle task")
            first_cycle.append(task["project_id"])
            scheduler.finish(task["project_id"], task["id"], passed=True)
        if set(first_cycle) != set(PROJECTS):
            raise RuntimeError("round-robin fairness failed")

        failed = scheduler.claim_next()
        if not failed:
            raise RuntimeError("deliberate failure task was not claimable")
        scheduler.finish(failed["project_id"], failed["id"], passed=False)
        scheduler.retry(failed["project_id"], failed["id"])
        restarted = ProjectScheduler(registry_path, state_root)
        recovered = [item for item in restarted.all_tasks() if item["id"] == failed["id"]][0]
        if recovered["status"] != "pending":
            raise RuntimeError("retry was not persisted")
        retried = restarted.claim_next()
        restarted.finish(retried["project_id"], retried["id"], passed=True)

        # Drain the remaining lightweight queue before testing the heavy cap.
        scheduler = ProjectScheduler(registry_path, state_root)
        while True:
            task = scheduler.claim_next()
            if not task:
                break
            scheduler.finish(task["project_id"], task["id"], passed=True)

        # Two independent processes race for the heavy lane.  The lock must allow
        # one claim and return no duplicate claim to the other process.
        race = []
        for project_id in PROJECTS:
            race.append(scheduler.enqueue(project_id, f"race-{project_id}", "single heavy claim"))
        ctx = multiprocessing.get_context("fork") if hasattr(multiprocessing, "get_context") else multiprocessing
        queue = ctx.Queue()
        processes = [ctx.Process(target=lambda q: q.put(claim_once(registry_path, state_root)), args=(queue,)) for _ in range(2)]
        for process in processes:
            process.start()
        results = [queue.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
        claimed_ids = [item["id"] for item in results if item]
        if len(set(claimed_ids)) != len(claimed_ids) or len(claimed_ids) != 1:
            raise RuntimeError(f"duplicate or over-capacity heavy claims: {results}")
        winner = next(item for item in results if item)
        scheduler.finish(winner["project_id"], winner["id"], passed=True)

        # Complete all remaining lightweight tasks while preserving project scope.
        while True:
            task = scheduler.claim_next()
            if not task:
                break
            scheduler.finish(task["project_id"], task["id"], passed=True)

        final = ProjectScheduler(registry_path, state_root).summary()
        if final["totals"]["pending"] or final["totals"]["running"] or final["totals"]["review"]:
            raise RuntimeError(f"terminal cleanup failed: {final}")
        all_tasks = ProjectScheduler(registry_path, state_root).all_tasks()
        if any(task["project_id"] not in PROJECTS for task in all_tasks):
            raise RuntimeError("cross-project mutation detected")
        report = {
            "schema": "migz.v2.stress.v1",
            "projects": PROJECTS,
            "fairness_first_cycle": first_cycle,
            "duplicate_claims": 0,
            "heavy_local_max": 1,
            "failure_retry": "PASSED",
            "restart_persistence": "PASSED",
            "terminal_cleanup": "PASSED",
            "final_summary": final,
            "verdict": "PASSED",
        }
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Evidence: {output}")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("V2_STRESS: PASS")


if __name__ == "__main__":
    main()
