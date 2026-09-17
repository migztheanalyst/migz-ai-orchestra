import hashlib
import json
from datetime import datetime, timezone


MISSION_SCHEMA = "migz.mission.v1"
EVIDENCE_SCHEMA = "migz.evidence.v1"
EVIDENCE_STATES = {"OBSERVED", "INFERRED", "UNAVAILABLE", "BLOCKED", "PASSED"}
MISSION_REQUIRED = {
    "mission_id", "project", "title", "objective", "allowed_scope",
    "prohibited_operations", "provider_preference", "fallback",
    "qa_requirements", "completion_gates", "tasks", "created_at",
}


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _string(value, field, max_length=5000):
    value = str(value or "").strip()
    if not value or len(value) > max_length:
        raise ValueError(f"{field} is required and bounded")
    return value


def _list(value, field, allow_empty=False, max_items=100):
    if not isinstance(value, list) or (not allow_empty and not value) or len(value) > max_items:
        raise ValueError(f"{field} must be a bounded list")
    if not all(isinstance(item, (str, dict)) for item in value):
        raise ValueError(f"{field} contains an invalid item")
    return value


def _validate_tasks(tasks):
    _list(tasks, "tasks")
    normalized = []
    for index, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            raise ValueError(f"task {index} must be an object")
        title = _string(task.get("title"), f"task {index} title", 200)
        objective = _string(task.get("objective"), f"task {index} objective")
        role = _string(task.get("role", "coding"), f"task {index} role", 32).lower()
        if role not in {"fast", "triage", "coding", "review", "reasoning", "general"}:
            raise ValueError(f"task {index} has an invalid role")
        attempts = task.get("max_attempts", 3)
        if not isinstance(attempts, int) or not 1 <= attempts <= 10:
            raise ValueError(f"task {index} max_attempts must be 1-10")
        item = dict(task)
        item.update({"title": title, "objective": objective, "role": role, "max_attempts": attempts})
        normalized.append(item)
    return normalized


def mission_manifest(mission_id, project_id, objective, tasks, *, title=None,
                     allowed_scope=None, prohibited_operations=None,
                     provider_preference=None, fallback=None,
                     qa_requirements=None, completion_gates=None):
    mission_id = _string(mission_id, "mission_id", 200)
    project_id = _string(project_id, "project", 200)
    objective = _string(objective, "objective")
    # The original V1 helper accepted a title-only task.  Preserve that API
    # while making the persisted V2 manifest fully explicit and validated.
    compatible_tasks = []
    for task in tasks:
        item = dict(task) if isinstance(task, dict) else task
        if isinstance(item, dict):
            item.setdefault("objective", objective)
            item.setdefault("role", "coding")
            item.setdefault("max_attempts", 3)
        compatible_tasks.append(item)
    tasks = _validate_tasks(compatible_tasks)
    manifest = {
        "schema": MISSION_SCHEMA,
        "mission_id": mission_id,
        "project": project_id,
        "project_id": project_id,
        "title": _string(title or tasks[0]["title"], "title", 200),
        "objective": objective,
        "allowed_scope": _list(allowed_scope or [project_id], "allowed_scope"),
        "prohibited_operations": _list(
            prohibited_operations or ["production deployment", "secrets access", "billing", "DNS changes"],
            "prohibited_operations", allow_empty=True,
        ),
        "provider_preference": _list(
            provider_preference or ["qwen2.5-coder:7b", "qwen2.5-coder:3b"],
            "provider_preference",
        ),
        "fallback": _list(fallback or ["qwen2.5-coder:3b"], "fallback", allow_empty=True),
        "qa_requirements": _list(
            qa_requirements or [
                "python3 -m compileall -q conductor tests",
                "python3 -m unittest discover -s tests -p 'test_*.py' -v",
                "git diff --check",
            ],
            "qa_requirements",
        ),
        "completion_gates": _list(
            completion_gates or ["tester PASS", "Terra independent review PASS", "evidence packet complete", "verified commit"],
            "completion_gates",
        ),
        "tasks": tasks,
        "created_at": _utc(),
    }
    return validate_manifest(manifest)


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema") != MISSION_SCHEMA:
        raise ValueError("malformed mission manifest")
    missing = MISSION_REQUIRED - set(manifest)
    if missing:
        raise ValueError(f"mission fields missing: {sorted(missing)}")
    if manifest.get("project_id") != manifest.get("project"):
        raise ValueError("project and project_id must agree")
    _string(manifest.get("mission_id"), "mission_id", 200)
    _string(manifest.get("project"), "project", 200)
    _string(manifest.get("title"), "title", 200)
    _string(manifest.get("objective"), "objective")
    _validate_tasks(manifest.get("tasks"))
    for field in ("allowed_scope", "prohibited_operations", "provider_preference", "fallback", "qa_requirements", "completion_gates"):
        _list(manifest.get(field), field, allow_empty=field in {"prohibited_operations", "fallback"})
    if not isinstance(manifest.get("created_at"), str) or not manifest["created_at"].strip():
        raise ValueError("created_at is required")
    return dict(manifest)


def _normalize_check(check):
    if not isinstance(check, dict) or not str(check.get("name", "")).strip():
        raise ValueError("each evidence check needs a name")
    item = dict(check)
    state = item.get("state")
    if state is None:
        state = "PASSED" if item.get("passed") is True else "OBSERVED"
    if state not in EVIDENCE_STATES:
        raise ValueError("invalid evidence state")
    item["state"] = state
    return item


def evidence_packet(mission_id, task_id, status, checks, artifacts=None, notes="", *,
                    project=None, model=None, provider=None, timestamps=None,
                    changed_files=None, test_commands=None, exit_codes=None,
                    reviewer_verdict=None, retries=0, commit=None, backend=None,
                    final_state=None, observations=None):
    if status not in {"PASS", "FAIL", "BLOCKED", "UNVERIFIED"}:
        raise ValueError("invalid evidence status")
    if not isinstance(checks, list) or not checks:
        raise ValueError("evidence checks are required")
    if not isinstance(retries, int) or retries < 0 or retries > 10:
        raise ValueError("retries must be bounded")
    packet = {
        "schema": EVIDENCE_SCHEMA,
        "mission_id": str(mission_id),
        "task_id": str(task_id),
        "status": status,
        "checks": [_normalize_check(item) for item in checks],
        "artifacts": list(artifacts or []),
        "notes": str(notes),
        "created_at": _utc(),
        "project": project if project is not None else "UNAVAILABLE",
        "model": model if model is not None else "UNAVAILABLE",
        "provider": provider if provider is not None else "UNAVAILABLE",
        "backend": backend if backend is not None else "UNAVAILABLE",
        "timestamps": dict(timestamps or {"captured_at": _utc()}),
        "changed_files": list(changed_files or []),
        "test_commands": list(test_commands or []),
        "exit_codes": dict(exit_codes or {}),
        "reviewer_verdict": reviewer_verdict if reviewer_verdict is not None else "UNAVAILABLE",
        "retries": retries,
        "commit": commit if commit is not None else "UNAVAILABLE",
        "final_state": final_state or ("PASSED" if status == "PASS" else status),
        "observations": list(observations or []),
    }
    canonical = json.dumps(packet, sort_keys=True, ensure_ascii=False).encode()
    packet["sha256"] = hashlib.sha256(canonical).hexdigest()
    return packet


def validate_evidence_packet(packet):
    if not isinstance(packet, dict) or packet.get("schema") != EVIDENCE_SCHEMA:
        raise ValueError("malformed evidence packet")
    required = {"mission_id", "task_id", "status", "checks", "artifacts", "created_at", "sha256"}
    if not required.issubset(packet):
        raise ValueError("evidence fields missing")
    expected = dict(packet)
    digest = expected.pop("sha256")
    actual = hashlib.sha256(json.dumps(expected, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if digest != actual:
        raise ValueError("evidence sha256 mismatch")
    for check in packet["checks"]:
        _normalize_check(check)
    return dict(packet)
