import subprocess
import sys
import tempfile
import time
import json
import os
from pathlib import Path

from evidence_manager import capture_evidence
from agent_backend_router import AgentBackendRouter, BackendUnavailable
from decision_layer import DecisionLayer
from backend_change_guard import inspect_changes, write_report
from decomposition import bounded_subtasks, should_decompose
from provider_router import classify_backend_failure
from war_room_event_bus import EventBus, make_event
from task_engine import TaskStore
from project_registry import ProjectRegistry
from worktree_manager import (
    create_worktree,
    default_worktree_root,
    remove_worktree,
)


def run(workspace, *command):
    result = subprocess.run(
        list(command),
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=1800,
        shell=False,
    )

    print(
        "$ " + " ".join(command)
    )

    if result.stdout:
        print(result.stdout.rstrip())

    if result.stderr:
        print(result.stderr.rstrip())

    return result



def run_live(workspace, command, heartbeat, env=None, timeout=1800):
    fd, name = tempfile.mkstemp(prefix="migz-live-", suffix=".log")
    try:
        with open(fd, "w") as log:
            child_env = os.environ.copy()
            child_env.update(env or {})
            proc = subprocess.Popen(list(command), cwd=workspace, stdout=log, stderr=subprocess.STDOUT, text=True, shell=False, env=child_env)
            last = time.monotonic()
            deadline = last + timeout
            while proc.poll() is None:
                now = time.monotonic()
                if now - last >= 45:
                    heartbeat()
                    last = now
                if now >= deadline:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=10)
                    text = Path(name).read_text(encoding="utf-8", errors="replace")
                    return subprocess.CompletedProcess(command, 124, text, "bounded backend timeout")
                time.sleep(1)
        text = Path(name).read_text(encoding="utf-8", errors="replace")
        print("$ " + " ".join(command))
        if text:
            print(text.rstrip())
        return subprocess.CompletedProcess(command, proc.returncode, text, "")
    finally:
        Path(name).unlink(missing_ok=True)


def block_task(store, task_id, note):
    try:
        _, task = store.find(task_id)

        if task["status"] in {
            "running",
            "review",
            "pending",
        }:
            store.transition(
                task_id,
                "blocked",
                note,
            )
    except Exception:
        pass


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 conductor/maestro.py "
            "<repo> <task-id>"
        )
        raise SystemExit(1)

    repo = Path(
        sys.argv[1]
    ).expanduser().resolve()

    task_id = sys.argv[2]

    store = TaskStore(
        repo / "tasks"
    )

    workspace = None
    target_repo = repo
    worktree_removed = False
    bus = EventBus(repo / "evidence" / "war_room")
    backend_plan = None

    def emit(kind, agent=None, summary="", visibility="normal", data=None):
        event_data = dict(data or {})
        if backend_plan is not None:
            event_data.setdefault("backend", backend_plan.backend)
            event_data.setdefault("provider", backend_plan.provider)
            event_data.setdefault("model", backend_plan.model)
        return bus.publish(make_event(kind, task_id=task_id, agent=agent, summary=summary, data=event_data, visibility=visibility))

    def cleanup_worktree():
        nonlocal worktree_removed
        if workspace is not None and not worktree_removed:
            try:
                remove_worktree(target_repo, task_id)
            except FileNotFoundError:
                pass
            except RuntimeError:
                # A failed builder/tester may leave an untracked artifact in
                # the isolated worktree.  Only force-clean the exact task
                # directory under the configured worktree root; never widen
                # this fallback to an arbitrary path.
                try:
                    worktree_root = default_worktree_root(target_repo).resolve()
                    workspace_path = workspace.resolve()
                    if workspace_path.parent != worktree_root:
                        raise ValueError("Worktree is outside the managed root")
                    remove_worktree(target_repo, task_id, force=True)
                except (FileNotFoundError, RuntimeError, ValueError):
                    pass
            except ValueError:
                pass
            worktree_removed = True

    try:
        _, task = store.find(
            task_id
        )

        if task["status"] != "pending":
            raise RuntimeError(
                "Task must be pending"
            )

        project_id = task.get("project_id")
        if project_id:
            registry = ProjectRegistry(repo / "state" / "projects.json")
            project = registry.resolve(project_id)
            if not project or project.get("status") != "ready" or not project.get("enabled"):
                raise RuntimeError("Project is not enabled and ready")
            target_repo = Path(project["repository_path"]).expanduser().resolve()
            if not target_repo.is_dir():
                raise RuntimeError("Project repository path is unavailable")

        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        requested_backend = str(metadata.get("backend", "native")).strip().lower()
        allowed_scope = metadata.get("allowed_scope") or task.get("allowed_scope") or []

        decision_mode = metadata.get("decision_layer_mode")
        if decision_mode is None and metadata.get("decision_mode") == "auto":
            decision_mode = "assist"
        decision_layer = DecisionLayer(mode=decision_mode)
        decision = decision_layer.decide(task)
        effective_role = decision.effective_role

        router = AgentBackendRouter(repo=repo, ollama_base=os.environ.get("OLLAMA_BASE_URL"))
        fallback_reason = None
        try:
            backend_plan, fallback_reason = router.route_with_fallback(effective_role, requested_backend, probe=False)
        except BackendUnavailable as exc:
            block_task(store, task_id, f"Backend unavailable: {exc}")
            emit("task.blocked", "sol", f"Backend blocked: {requested_backend}", data={"failure_class": "BACKEND_UNAVAILABLE", "reason": str(exc)})
            print("MAESTRO   : BLOCKED")
            raise SystemExit(1)

        print("=== MIGZ MAESTRO V3 ===")
        print(f"Task      : {task_id}")
        print(f"Title     : {task['title']}")
        print(f"Role      : {task['role']} -> {effective_role}")
        print(f"Decision  : {decision.source} | {decision.mode} | confidence={decision.confidence:.2f}")
        emit(
            "decision.evaluated",
            "jev",
            f"Decision: {decision.source} -> {decision.recommended_role} (effective {effective_role})",
            data={
                "source": decision.source,
                "mode": decision.mode,
                "recommended_role": decision.recommended_role,
                "effective_role": effective_role,
                "operational_risk": decision.operational_risk,
                "needs_escalation": decision.needs_escalation,
                "needs_review": decision.needs_review,
                "confidence": decision.confidence,
                "model": decision.model,
                "reason": decision.reason,
            },
        )
        emit("task.started", "sol", f"Started: {task['title']}", data={"backend": backend_plan.backend, "provider": backend_plan.provider, "model": backend_plan.model, "effective_role": effective_role})
        if fallback_reason:
            emit(
                "task.retry",
                "sol",
                f"Requested backend unavailable; using {backend_plan.backend}",
                data={"fallback": [requested_backend, backend_plan.backend], "reason": fallback_reason, "retry": 0},
            )

        created = create_worktree(
            target_repo,
            task_id,
        )

        workspace = Path(
            created["workspace"]
        )

        store.transition(
            task_id,
            "running",
            "Maestro claimed task",
        )

        emit("builder.started", "luna", f"Backend: {backend_plan.backend} | Model: {backend_plan.model} | Builder started isolated implementation")

        builder_script = (workspace / "conductor" / "builder_agent.py") if (workspace / "conductor" / "builder_agent.py").exists() else (repo / "conductor" / "builder_agent.py")
        builder_command, backend_env = router.command(backend_plan, workspace, task["objective"], builder_script, allowed_scope=allowed_scope)
        builder = run_live(workspace, builder_command, lambda: emit("heartbeat", "luna", f"Backend: {backend_plan.backend} | Model: {backend_plan.model} | Still implementing safely; no blocker detected"), env=backend_env, timeout=900 if backend_plan.backend == "aider" else 1800)

        builder_report = workspace / "evidence" / "builder-latest.json"
        model_note = ""
        if builder_report.exists():
            builder_data = json.loads(builder_report.read_text(encoding="utf-8"))
            model_note = f" via {builder_data.get('provider', 'UNAVAILABLE')}/{builder_data.get('model', 'UNAVAILABLE')}"
            builder_report.unlink(missing_ok=True)

        guard = inspect_changes(
            workspace,
            backend=backend_plan.backend,
            allowed_scope=allowed_scope,
            managed_root=default_worktree_root(target_repo),
        )
        guard_output, _ = write_report(workspace, guard, backend_plan.provider, backend_plan.model, fallback=list(backend_plan.fallback))
        backend_report = workspace / "evidence" / "backend-latest.json"
        backend_report.write_text(json.dumps({
            "schema": "migz.backend.execution.v1",
            "backend": backend_plan.backend,
            "provider": backend_plan.provider,
            "model": backend_plan.model,
            "role": effective_role,
            "requested_role": task.get("role", "coding"),
            "decision": decision.as_dict(),
            "status": "PASS" if builder.returncode == 0 and guard.passed else "BLOCKED",
            "fallback": list(backend_plan.fallback),
            "guard": str(guard_output),
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        emit("backend.guard", "sol", f"Backend change guard: {'PASS' if guard.passed else 'BLOCKED'}", data={"guard": "PASS" if guard.passed else "BLOCKED", "files": list(guard.files), "violations": list(guard.violations)})
        if not guard.passed:
            block_task(store, task_id, "Backend change guard blocked: " + "; ".join(guard.violations))
            emit("task.blocked", "sol", "Backend change guard blocked the edit", data={"failure_class": "SECURITY_BLOCKER", "guard_evidence": str(guard_output)})
            print("MAESTRO   : BLOCKED")
            raise SystemExit(1)

        if builder.returncode != 0:
            if should_decompose(builder.stdout):
                subtasks = bounded_subtasks(task["title"], task["objective"], task["role"], task_id)
                created = [store.create(x["title"], x["objective"], x["role"], task.get("max_attempts", 3), project_id=project_id, metadata=x) for x in subtasks]
                block_task(store, task_id, f"Builder oversized; decomposed into {len(created)} bounded subtasks")
                emit("task.retry", "sol", f"Oversized builder output decomposed into {len(created)} bounded subtasks")
                print(f"DECOMPOSED: {len(created)}")
                raise SystemExit(1)
            failure_class = classify_backend_failure(builder.stdout or "Builder failed")
            block_task(store, task_id, "Builder failed")
            emit("task.blocked", "sol", "Builder failed; task blocked", data={"failure_class": failure_class, "backend": backend_plan.backend})
            print("MAESTRO   : BLOCKED")
            raise SystemExit(1)

        emit("builder.complete", "luna", "Backend: %s | Model: %s | Implementation completed%s; sending to tests" % (backend_plan.backend, backend_plan.model, model_note))

        store.transition(
            task_id,
            "review",
            "Builder completed",
        )

        emit("tester.started", "terra", "Testing started")
        tester_script = (workspace / "conductor" / "tester_agent.py") if (workspace / "conductor" / "tester_agent.py").exists() else (repo / "conductor" / "tester_agent.py")
        tester = run_live(workspace, ["python3", str(tester_script), str(workspace)], lambda: emit("heartbeat", "terra", "Tests still running; no blocker detected"))
        test_report = workspace / "evidence" / "tester-latest.json"
        if test_report.exists():
            for item in json.loads(test_report.read_text()).get("tests", []):
                cmd = " ".join(item.get("command", []))
                verdict = "PASS" if item.get("passed") else "FAIL"
                emit("tester.command", "terra", f"{verdict}: {cmd}")

        if tester.returncode != 0:
            emit("tester.fail", "terra", "Tests failed; refusing to approve")
            block_task(
                store,
                task_id,
                "Tester failed",
            )
            emit("task.blocked", "sol", "Tester failed; task blocked")
            print("MAESTRO   : BLOCKED")
            raise SystemExit(1)

        emit("tester.pass", "terra", "All configured tests passed")

        emit("reviewer.started", "terra", "Independent review started")
        reviewer_script = (workspace / "conductor" / "reviewer_agent.py") if (workspace / "conductor" / "reviewer_agent.py").exists() else (repo / "conductor" / "reviewer_agent.py")
        review_plan = router.route("review", "native", probe=False)
        reviewer = run_live(
            workspace,
            ["python3", str(reviewer_script), str(workspace)],
            lambda: emit("heartbeat", "terra", f"Reviewer backend: {review_plan.backend} | Model: {review_plan.model} | Independent review still running"),
            env={"MIGZ_REVIEW_MODEL": review_plan.model or "", "MIGZ_PROVIDER": review_plan.provider},
            timeout=1200,
        )

        if reviewer.returncode != 0:
            emit("reviewer.fail", "terra", "Independent review rejected the change")
            block_task(
                store,
                task_id,
                "Reviewer failed",
            )
            emit("task.blocked", "sol", "Reviewer failed; task blocked")
            print("MAESTRO   : BLOCKED")
            raise SystemExit(1)

        emit("reviewer.pass", "terra", "Independent review passed")

        emit("evidence.started", "terra", "Capturing reproducible evidence")
        output, _ = capture_evidence(repo, task_id, workspace, project_id=project_id)
        emit("evidence.complete", "terra", f"Evidence captured: {output}")
        operational_evidence = ("builder-latest.json", "backend-guard.json", "backend-latest.json", "tester-latest.json", "reviewer-latest.json")
        evidence_dir = workspace / "evidence"
        for name in operational_evidence:
            (evidence_dir / name).unlink(missing_ok=True)
        if evidence_dir.exists() and not any(evidence_dir.iterdir()):
            evidence_dir.rmdir()
        emit("commit.started", "sol", "Creating verified task commit")
        if allowed_scope:
            run(workspace, "git", "add", "--", *allowed_scope)
        else:
            run(workspace, "git", "add", "-A")

        commit = run(
            workspace,
            "git",
            "commit",
            "-m",
            f"task {task_id}: {task['title']}",
        )

        if commit.returncode != 0:
            block_task(
                store,
                task_id,
                "Task commit failed",
            )
            print("MAESTRO   : BLOCKED")
            raise SystemExit(1)

        head = run(workspace, "git", "rev-parse", "HEAD").stdout.strip()
        emit("commit.complete", "sol", f"Verified commit created: {head}")

        store.transition(
            task_id,
            "passed",
            f"Verified task commit {head}",
        )

        remove_worktree(target_repo, task_id)
        worktree_removed = True

        print()
        print(f"Commit    : {head}")
        print(f"Evidence  : {output}")
        emit("task.passed", "sol", f"Task passed with commit {head}", visibility="quiet")
        print("MAESTRO   : PASS")

    except SystemExit:
        cleanup_worktree()
        raise

    except Exception as exc:
        cleanup_worktree()
        block_task(
            store,
            task_id,
            str(exc),
        )

        print("MAESTRO   : FAIL")
        print(f"ERROR     : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
