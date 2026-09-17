"""Unified, bounded routing for Orchestra agent backends.

Native is the default implementation path.  Aider is an explicitly selected
secondary coding backend, while Hermes and DeepSeek are advisory/optional
lanes.  Installation is never reported as health: HEALTHY requires a live
probe or a recorded successful canary.
"""

import json
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from model_router import model_candidates
from provider_router import detect_lanes, ollama_models
from runtime_env import executable_path, resolve_ollama_base


AVAILABLE = "AVAILABLE"
HEALTHY = "HEALTHY"
DEGRADED_OPTIONAL = "DEGRADED_OPTIONAL"
UNAVAILABLE = "UNAVAILABLE"
BLOCKED = "BLOCKED"

BACKENDS = {"native", "aider", "hermes", "deepseek", "openhands"}
HERMES_MODEL = "qwen3.5:4b"
OPENHANDS_MODEL = "qwen2.5-coder:7b"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def default_ollama_base():
    return resolve_ollama_base()


@dataclass(frozen=True)
class BackendState:
    backend: str
    status: str
    provider: str | None = None
    model: str | None = None
    reason: str = ""
    checked_at: str | None = None
    latency_seconds: float | None = None


@dataclass(frozen=True)
class BackendPlan:
    backend: str
    provider: str
    model: str | None
    role: str
    reason: str
    fallback: tuple[str, ...] = ()


class BackendUnavailable(RuntimeError):
    """Raised when a requested backend cannot be used safely."""


class AgentBackendRouter:
    def __init__(self, repo=None, ollama_base=None, state_path=None):
        self.repo = Path(repo).expanduser().resolve() if repo else None
        self.ollama_base = ollama_base or default_ollama_base()
        self.state_path = Path(state_path).expanduser().resolve() if state_path else (
            self.repo / "state" / "backend-preflight.json" if self.repo else None
        )
        self.aider_executable = executable_path(
            "aider",
            (str(Path.home() / ".local/share/migz-aider-venv/bin/aider"),),
        )
        self.hermes_executable = executable_path(
            "hermes",
            (str(Path.home() / ".local/bin/hermes"),),
        )
        self.openhands_executable = executable_path(
            "openhands",
            (str(Path.home() / ".local/share/migz-openhands-venv/bin/openhands"),),
        )

    def _cached(self):
        if not self.state_path or not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}

    def _canary_path(self, backend):
        if not self.repo:
            return None
        filename = "hermes-final-probe.json" if backend == "hermes" else f"{backend}-canary.json"
        return self.repo / "evidence" / "core-final-closure" / filename

    def _canary_data(self, backend):
        path = self._canary_path(backend)
        if not path or not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}

    def _canary_passed(self, backend):
        return self._canary_data(backend).get("state") == "PASSED"

    def _canary_model(self, backend):
        return self._canary_data(backend).get("model")

    def _write_hermes_probe(self, payload):
        path = self._canary_path("hermes")
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload
    def _lane_states(self, probe=False):
        cached = self._cached().get("lanes", {})
        if probe:
            try:
                return {name: vars(lane) for name, lane in detect_lanes(self.ollama_base, probe=True, release_after_probe=True, probe_names={"qwen-fast"}).items()}
            except Exception as exc:
                return {"_error": {"status": UNAVAILABLE, "reason": f"{type(exc).__name__}: {exc}"}}
        if cached:
            allowed = {"qwen-fast", "qwen-coding", "qwen-reasoning", "deepseek"}
            return {name: dict(value) for name, value in cached.items() if name in allowed}
        try:
            models = ollama_models(self.ollama_base)
        except Exception as exc:
            return {"_error": {"status": UNAVAILABLE, "reason": f"{type(exc).__name__}: {exc}"}}
        result = {}
        for name, model in (
            ("qwen-fast", "qwen2.5-coder:3b"),
            ("qwen-coding", "qwen2.5-coder:7b"),
            ("qwen-reasoning", "qwen3.5:4b"),
        ):
            result[name] = {
                "status": AVAILABLE if model in models else UNAVAILABLE,
                "provider": "ollama",
                "model": model,
                "reason": "installed; live health not yet observed" if model in models else "model not installed",
            }
        deepseek = sorted(model for model in models if model and model.startswith("deepseek"))
        result["deepseek"] = {
            "status": AVAILABLE if deepseek else UNAVAILABLE,
            "provider": "ollama",
            "model": deepseek[0] if deepseek else None,
            "reason": "installed; live advisory probe required" if deepseek else "optional local DeepSeek model not installed",
        }
        return result

    def lane_states(self, probe=False):
        """Resolve provider lanes once so callers can reuse one live snapshot."""
        return self._lane_states(probe=probe)

    def states(self, probe=False, lanes=None):
        lanes = self._lane_states(probe=probe) if lanes is None else lanes
        now = utc_now()
        coding = lanes.get("qwen-coding", {})
        fast = lanes.get("qwen-fast", {})
        reasoning = lanes.get("qwen-reasoning", {})
        selected_native_model = (
            coding.get("model") if coding.get("status") in {"PASS", HEALTHY}
            else fast.get("model") if fast.get("status") in {"PASS", HEALTHY}
            else coding.get("model") or fast.get("model")
        )
        selected_native_lane = coding if coding.get("status") in {"PASS", HEALTHY} else fast
        native_status = coding.get("status")
        if native_status == "PASS" or fast.get("status") == "PASS":
            native_status = HEALTHY
        elif native_status in {AVAILABLE, "PASS"} or fast.get("status") in {AVAILABLE, "PASS"}:
            native_status = AVAILABLE
        else:
            native_status = UNAVAILABLE
        result = {
            "native": BackendState(
                "native", native_status, "ollama",
                selected_native_model,
                selected_native_lane.get("reason", ""), now,
                selected_native_lane.get("elapsed_seconds"),
            ),
            "aider": BackendState(
                "aider", HEALTHY if self._canary_passed("aider") else (AVAILABLE if self.aider_executable else UNAVAILABLE),
                "ollama", self._canary_model("aider") or selected_native_model or "qwen2.5-coder:7b",
                "controlled canary passed" if self._canary_passed("aider") else ("executable present; controlled canary required for HEALTHY" if self.aider_executable else "Aider executable not found"),
                now,
            ),
            "hermes": BackendState(
                "hermes",
                HEALTHY if self._canary_passed("hermes") else (DEGRADED_OPTIONAL if self.hermes_executable else UNAVAILABLE),
                "custom-local-ollama" if self.hermes_executable else None,
                self._canary_model("hermes") or HERMES_MODEL,
                "controlled advisory canary passed" if self._canary_passed("hermes") else ("executable present; controlled advisory canary required for HEALTHY" if self.hermes_executable else "Hermes executable not found"),
                now,
            ),
            "deepseek": self._deepseek_state(lanes.get("deepseek", {}), now),
            "openhands": BackendState(
                "openhands", HEALTHY if self._canary_passed("openhands") else (AVAILABLE if self.openhands_executable else UNAVAILABLE),
                "custom-local-ollama" if self.openhands_executable else None,
                self._canary_model("openhands") or OPENHANDS_MODEL,
                "controlled coding canary passed" if self._canary_passed("openhands") else ("executable present; controlled coding canary required for HEALTHY" if self.openhands_executable else "OpenHands executable not found"),
                now,
            ),
        }
        if lanes.get("_error"):
            result["native"] = BackendState("native", UNAVAILABLE, "ollama", None, lanes["_error"].get("reason", "Ollama unavailable"), now)
        return result

    def model_states(self, probe=False, lanes=None):
        """Return sanitized provider/model lane state for diagnostics."""
        lanes = self._lane_states(probe=probe) if lanes is None else lanes
        return {
            name: dict(value)
            for name, value in lanes.items()
            if name in {"qwen-fast", "qwen-coding", "qwen-reasoning", "deepseek"}
        }

    @staticmethod
    def _deepseek_state(lane, checked_at):
        status = lane.get("status", UNAVAILABLE)
        if status == "PASS":
            status = HEALTHY
        elif status == AVAILABLE:
            status = DEGRADED_OPTIONAL
        return BackendState("deepseek", status, lane.get("provider"), lane.get("model"), lane.get("reason", ""), checked_at, lane.get("elapsed_seconds"))

    def save_preflight(self, lanes, selected=None, source="live"):
        if not self.state_path:
            return None
        payload = {
            "schema": "migz.backend-preflight.v1",
            "captured_at": utc_now(),
            "source": source,
            "selected": selected,
            "lanes": lanes,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload

    def route(self, role="coding", requested_backend=None, probe=False):
        role = str(role).strip().lower()
        backend = (requested_backend or "native").strip().lower()
        if backend not in BACKENDS:
            raise BackendUnavailable(f"Unknown backend: {backend}")
        states = self.states(probe=probe)
        if backend == "aider":
            state = states["aider"]
            if state.status not in {AVAILABLE, HEALTHY}:
                raise BackendUnavailable(state.reason or "Aider unavailable")
            model = state.model if state.model else states["native"].model
            if model not in {"qwen2.5-coder:7b", "qwen2.5-coder:3b"}:
                raise BackendUnavailable("No local Qwen coding model is healthy or installed")
            return BackendPlan("aider", "ollama", model, role, "explicit secondary coding backend", ("qwen2.5-coder:3b",))
        if backend == "hermes":
            state = states["hermes"]
            if state.status not in {AVAILABLE, HEALTHY, DEGRADED_OPTIONAL}:
                raise BackendUnavailable(state.reason or "Hermes unavailable")
            return BackendPlan("hermes", state.provider or "custom-local-ollama", state.model or HERMES_MODEL, role, state.reason, ("native",))
        if backend == "deepseek":
            state = states["deepseek"]
            if state.status not in {AVAILABLE, HEALTHY, DEGRADED_OPTIONAL}:
                raise BackendUnavailable(state.reason or "DeepSeek unavailable")
            return BackendPlan("deepseek", state.provider or "ollama", state.model, role, state.reason, ("native",))
        if backend == "openhands":
            state = states["openhands"]
            if state.status not in {AVAILABLE, HEALTHY}:
                raise BackendUnavailable(state.reason or "OpenHands unavailable")
            return BackendPlan("openhands", state.provider or "custom-local-ollama", state.model or OPENHANDS_MODEL, role, state.reason, ("native",))

        lane = {
            "fast": "qwen-fast", "triage": "qwen-fast",
            "coding": "qwen-coding", "review": "qwen-coding",
            "reasoning": "qwen-reasoning", "general": "qwen-reasoning",
        }.get(role, "qwen-coding")
        lanes = self._lane_states(probe=probe)
        candidates = model_candidates(role)
        for model in candidates:
            lane_name = {"qwen2.5-coder:3b": "qwen-fast", "qwen2.5-coder:7b": "qwen-coding", "qwen3.5:4b": "qwen-reasoning"}.get(model, lane)
            state = lanes.get(lane_name, {})
            if state.get("status") in {"PASS", HEALTHY}:
                return BackendPlan("native", "ollama", model, role, f"healthy lane {lane_name}", tuple(candidates[1:]))
        if not probe:
            installed = self._lane_states(probe=False)
            for model in candidates:
                lane_name = {"qwen2.5-coder:3b": "qwen-fast", "qwen2.5-coder:7b": "qwen-coding", "qwen3.5:4b": "qwen-reasoning"}.get(model, lane)
                if installed.get(lane_name, {}).get("status") == AVAILABLE:
                    return BackendPlan("native", "ollama", model, role, "installed lane; live probe deferred", tuple(candidates[1:]))
        raise BackendUnavailable(f"No usable native model for role {role}")

    def route_with_fallback(self, role="coding", requested_backend=None, probe=False):
        requested = (requested_backend or "native").strip().lower()
        try:
            plan = self.route(role, requested, probe=probe)
            if plan.backend in {"hermes", "deepseek"} and role not in {"advisory", "reasoning", "general"}:
                raise BackendUnavailable(f"{plan.backend} is advisory-only for role {role}")
            return plan, None
        except BackendUnavailable as exc:
            if requested == "native":
                raise
            native = self.route(role, "native", probe=probe)
            return BackendPlan(
                native.backend, native.provider, native.model, native.role,
                f"fallback from {requested}: {exc}",
                (requested,) + tuple(native.fallback),
            ), str(exc)

    def command(self, plan, workspace, objective, script_path=None, allowed_scope=None):
        workspace = Path(workspace).expanduser().resolve()
        if plan.backend == "native":
            if script_path is None:
                script_path = workspace / "conductor" / "builder_agent.py"
            command = ["python3", str(script_path), str(workspace), objective]
            env = {"MIGZ_BACKEND": "native", "MIGZ_PROVIDER": plan.provider, "MIGZ_MODEL": plan.model or ""}
            return command, env
        if plan.backend == "openhands":
            if not self.openhands_executable:
                raise BackendUnavailable("OpenHands executable not found")
            scope = [str(item).replace("\\", "/") for item in (allowed_scope or [])]
            if not scope:
                raise BackendUnavailable("OpenHands requires an explicit allowed_scope")
            prompt = (
                "You are the OpenHands coding backend inside an isolated MIGZ Orchestra worktree. "
                "Make only the requested edit. Do not deploy, commit, change credentials, or touch files outside ALLOWED FILES. "
                "Do not ask interactive questions.\n\nOBJECTIVE:\n" + objective +
                "\n\nALLOWED FILES:\n" + "\n".join(scope)
            )
            command = [self.openhands_executable, "--headless", "--json", "--override-with-envs", "--exit-without-confirmation", "-t", prompt]
            env = {
                "MIGZ_BACKEND": "openhands", "MIGZ_PROVIDER": "custom-local-ollama",
                "MIGZ_MODEL": plan.model or OPENHANDS_MODEL,
                "LLM_MODEL": f"openai/{plan.model or OPENHANDS_MODEL}",
                "LLM_BASE_URL": self.ollama_base.rstrip("/") + "/v1",
                "LLM_API_KEY": "local-llm", "RUNTIME": "process", "NO_COLOR": "1",
            }
            return command, env
        if plan.backend != "aider":
            raise BackendUnavailable(f"Backend {plan.backend} is advisory-only")
        if not self.aider_executable:
            raise BackendUnavailable("Aider executable not found")
        scope = [str(item).replace("\\", "/") for item in (allowed_scope or [])]
        if not scope:
            raise BackendUnavailable("Aider requires an explicit allowed_scope")
        prompt = (
            "You are the secondary Aider coding backend inside an isolated MIGZ "
            "Orchestra worktree. Make only the requested edit. Do not run shell "
            "commands, edit .git/.env/secrets, deploy, or commit.\n\n"
            f"OBJECTIVE:\n{objective}\n\n"
            "ALLOWED FILES:\n" + "\n".join(scope)
        )
        command = [
            self.aider_executable,
            "--model", f"ollama/{plan.model}",
            "--no-auto-commits", "--no-dirty-commits", "--no-gitignore",
            "--no-add-gitignore-files", "--no-suggest-shell-commands",
            "--analytics-disable", "--no-auto-lint", "--no-auto-test",
            "--no-pretty", "--no-stream", "--no-restore-chat-history",
            "--input-history-file", "/dev/null", "--chat-history-file", "/dev/null",
            "--llm-history-file", "/dev/null",
            "--no-check-update", "--exit", "--yes-always", "--timeout", "300",
            "--message", prompt,
        ]
        for item in scope:
            command.extend(["--file", item])
        env = {
            "MIGZ_BACKEND": "aider", "MIGZ_PROVIDER": plan.provider,
            "MIGZ_MODEL": plan.model or "", "OLLAMA_API_BASE": self.ollama_base,
            "AIDER_ANALYTICS": "false",
            "AIDER_MAP_TOKENS": "0",
        }
        return command, env

    def _hermes_command(self, prompt, workspace):
        return [
            self.hermes_executable,
            "--in", str(workspace),
            "--reasoning", "none",
            "--toolsets", "context_engine",
            "--safe-mode",
            "--ignore-rules",
            "-z", prompt,
        ]

    def bounded_hermes_probe(self, prompt="Reply exactly: HERMES_OK", timeout=160):
        started = time.monotonic()
        if not self.hermes_executable:
            return {"status": UNAVAILABLE, "reason": "Hermes executable not found"}
        env = os.environ.copy()
        env.update({"HERMES_SAFE_MODE": "1", "NO_COLOR": "1"})
        try:
            with tempfile.TemporaryDirectory(prefix="migz-hermes-canary-") as scratch:
                command = self._hermes_command(prompt, scratch)
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=timeout,
                    env=env, cwd=scratch, shell=False,
                )
            text = (result.stdout + "\n" + result.stderr).strip()
            ok = result.returncode == 0 and "HERMES_OK" in result.stdout
            elapsed = round(time.monotonic() - started, 3)
            evidence = {
                "schema": "migz.core.hermes-probe.v1",
                "state": "PASSED" if ok else "DEGRADED_OPTIONAL",
                "backend": "hermes",
                "provider": "custom-local-ollama",
                "model": HERMES_MODEL,
                "configured_context_length": 65536,
                "probe": prompt,
                "elapsed_seconds": elapsed,
                "reason": "isolated advisory canary passed" if ok else text[-600:],
                "response_exact": ok,
                "observed": True,
            }
            self._write_hermes_probe(evidence)
            return {
                "status": HEALTHY if ok else DEGRADED_OPTIONAL,
                "returncode": result.returncode,
                "elapsed_seconds": elapsed,
                "response_exact": ok,
                "reason": evidence["reason"],
            }
        except subprocess.TimeoutExpired:
            elapsed = round(time.monotonic() - started, 3)
            self._write_hermes_probe({
                "schema": "migz.core.hermes-probe.v1", "state": "DEGRADED_OPTIONAL",
                "backend": "hermes", "provider": "custom-local-ollama", "model": HERMES_MODEL,
                "configured_context_length": 65536, "probe": prompt,
                "elapsed_seconds": elapsed, "reason": "bounded timeout", "observed": True,
            })
            return {"status": DEGRADED_OPTIONAL, "elapsed_seconds": elapsed, "reason": "bounded timeout"}
        except Exception as exc:
            return {"status": DEGRADED_OPTIONAL, "elapsed_seconds": round(time.monotonic() - started, 3), "reason": f"{type(exc).__name__}: {exc}"}

    def run_hermes_advisory(self, prompt, timeout=180):
        if not self.hermes_executable:
            raise BackendUnavailable("Hermes executable not found")
        if self.repo and not self._canary_passed("hermes"):
            raise BackendUnavailable("Hermes controlled advisory canary has not passed")
        env = os.environ.copy()
        env.update({"HERMES_SAFE_MODE": "1", "NO_COLOR": "1"})
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="migz-hermes-advisory-") as scratch:
            result = subprocess.run(
                self._hermes_command(prompt, scratch), capture_output=True, text=True,
                timeout=timeout, env=env, cwd=scratch, shell=False,
            )
        response = result.stdout.strip()
        if result.returncode != 0 or not response:
            detail = (result.stderr or result.stdout or "Hermes produced no response")[-600:]
            raise BackendUnavailable(detail)
        return {
            "status": HEALTHY, "backend": "hermes", "provider": "custom-local-ollama",
            "model": HERMES_MODEL, "elapsed_seconds": round(time.monotonic() - started, 3),
            "response": response,
        }


    def bounded_openhands_probe(self, prompt="Do not modify files. Reply exactly: OPENHANDS_OK", timeout=240):
        started = time.monotonic()
        if not self.openhands_executable:
            return {"status": UNAVAILABLE, "reason": "OpenHands executable not found"}
        env = os.environ.copy()
        env.update({
            "LLM_MODEL": f"openai/{OPENHANDS_MODEL}",
            "LLM_BASE_URL": self.ollama_base.rstrip("/") + "/v1",
            "LLM_API_KEY": "local-llm", "RUNTIME": "process", "NO_COLOR": "1",
        })
        try:
            with tempfile.TemporaryDirectory(prefix="migz-openhands-canary-") as scratch:
                command = [self.openhands_executable, "--headless", "--json", "--override-with-envs", "--exit-without-confirmation", "-t", prompt]
                result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env, cwd=scratch, shell=False)
                residual = [item.name for item in Path(scratch).iterdir()]
            text = (result.stdout + "\n" + result.stderr).strip()
            ok = result.returncode == 0 and "OPENHANDS_OK" in text and not residual
            elapsed = round(time.monotonic() - started, 3)
            payload = {
                "schema": "migz.core.openhands-canary.v1", "state": "PASSED" if ok else "FAILED",
                "backend": "openhands", "provider": "custom-local-ollama", "model": OPENHANDS_MODEL,
                "elapsed_seconds": elapsed, "response_marker": "OPENHANDS_OK" in text,
                "workspace_clean": not residual, "returncode": result.returncode,
                "reason": "isolated headless coding canary passed" if ok else text[-800:], "observed": True,
            }
            path = self._canary_path("openhands")
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return {"status": HEALTHY if ok else UNAVAILABLE, "elapsed_seconds": elapsed, "workspace_clean": not residual, "returncode": result.returncode, "reason": payload["reason"]}
        except subprocess.TimeoutExpired:
            return {"status": UNAVAILABLE, "elapsed_seconds": round(time.monotonic() - started, 3), "reason": "bounded timeout"}
        except Exception as exc:
            return {"status": UNAVAILABLE, "elapsed_seconds": round(time.monotonic() - started, 3), "reason": f"{type(exc).__name__}: {exc}"}

    def as_json(self, probe=False, lanes=None):
        return {name: asdict(state) for name, state in self.states(probe=probe, lanes=lanes).items()}
