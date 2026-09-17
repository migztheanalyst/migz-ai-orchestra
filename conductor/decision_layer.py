"""Fast, fail-safe decision layer for MIGZ AI Orchestra V3.

Jev is used only when an authorized TYPESAFE_API_KEY is present.  The default
mode is shadow/advisory so existing routing, Terra review, and safety gates are
never bypassed merely by enabling this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
VALID_ROLES = ("fast", "triage", "coding", "review", "reasoning", "general")
VALID_MODES = {"shadow", "assist"}
DEFAULT_CREDENTIAL_PATH = Path.home() / ".config" / "migz-ai-orchestra" / "typesafe.key"
DEFAULT_CANARY_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def credential_fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def model_matches(requested: str, actual: str | None) -> bool:
    """Accept a concrete Jev release resolved from the jev-latest alias."""
    if not actual:
        return False
    if actual == requested:
        return True
    return requested == "jev-latest" and re.fullmatch(r"jev-\d+\.\d+\.\d+", actual) is not None


@dataclass(frozen=True)
class Decision:
    source: str
    recommended_role: str
    effective_role: str
    operational_risk: str
    needs_escalation: bool
    needs_review: bool
    confidence: float
    model: str | None
    mode: str
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class DecisionLayer:
    def __init__(
        self,
        *,
        mode: str | None = None,
        min_confidence: float | None = None,
        urlopen: Callable[..., Any] | None = None,
        credential_path: str | os.PathLike[str] | None = None,
        allow_local_credential: bool = True,
        canary_max_age_seconds: int = DEFAULT_CANARY_MAX_AGE_SECONDS,
    ):
        configured_mode = (mode or os.environ.get("MIGZ_DECISION_MODE", "shadow")).strip().lower()
        self.mode = configured_mode if configured_mode in VALID_MODES else "shadow"
        raw_threshold = min_confidence if min_confidence is not None else os.environ.get("MIGZ_JEV_MIN_CONFIDENCE", "0.65")
        try:
            threshold = float(raw_threshold)
        except (TypeError, ValueError):
            threshold = 0.65
        self.min_confidence = min(max(threshold, 0.0), 1.0)
        self._urlopen = urlopen or urllib.request.urlopen
        self.credential_path = Path(credential_path).expanduser() if credential_path else DEFAULT_CREDENTIAL_PATH
        self.allow_local_credential = bool(allow_local_credential)
        self.canary_max_age_seconds = max(int(canary_max_age_seconds), 0)

    def _credential(self) -> tuple[str | None, str | None, str | None]:
        env_key = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
        if env_key:
            return env_key, "environment", None
        if not self.allow_local_credential:
            return None, None, None
        path = self.credential_path
        try:
            if not path.is_file():
                return None, None, None
            if path.stat().st_mode & 0o077:
                return None, "local_file", "credential_file_permissions_must_be_600"
            key = path.read_text(encoding="utf-8").strip()
            return (key, "local_file", None) if key else (None, "local_file", "credential_file_empty")
        except OSError as exc:
            return None, "local_file", f"credential_file_unreadable:{type(exc).__name__}"

    def _canary_is_fresh(self, captured_at: object) -> bool:
        if not isinstance(captured_at, str):
            return False
        try:
            instant = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - instant.astimezone(timezone.utc)).total_seconds()
            return 0 <= age <= self.canary_max_age_seconds
        except (TypeError, ValueError):
            return False

    def status(self, repo: str | os.PathLike[str] | None = None) -> dict[str, Any]:
        api_key, credential_source, credential_error = self._credential()
        configured = bool(api_key)
        result = {
            "provider": "typesafe-jev",
            "model": MODEL,
            "status": "CONFIGURED_UNVERIFIED" if configured else "READY_FOR_CREDENTIALS",
            "mode": self.mode,
            "min_confidence": self.min_confidence,
            "credential_source": credential_source,
        }
        if credential_error:
            result["status"] = "CREDENTIAL_BLOCKED"
            result["reason"] = credential_error
        if configured and repo is not None:
            evidence = os.path.join(os.fspath(repo), "evidence", "jev-canary.json")
            try:
                with open(evidence, "r", encoding="utf-8") as handle:
                    canary = json.load(handle)
                fingerprint_matches = canary.get("credential_fingerprint") == credential_fingerprint(api_key)
                fresh = self._canary_is_fresh(canary.get("captured_at"))
                if canary.get("status") == "PASS" and model_matches(MODEL, canary.get("model")) and fingerprint_matches and fresh:
                    result["status"] = "ACTIVE"
                    result["last_canary_at"] = canary.get("captured_at")
                    result["last_latency_ms"] = canary.get("latency_ms")
                elif canary.get("status") == "PASS":
                    result["verification"] = "STALE_OR_CREDENTIAL_MISMATCH"
            except (OSError, ValueError, TypeError):
                pass
        return result

    def decide(self, task: dict[str, Any]) -> Decision:
        fallback = self._fallback(task)
        api_key, _, _ = self._credential()
        if not api_key:
            return fallback
        try:
            live = self._call_jev(task, api_key)
        except Exception as exc:
            return self._fallback(task, reason=f"jev_unavailable:{type(exc).__name__}")
        if live.confidence < self.min_confidence:
            return self._fallback(task, reason="jev_low_confidence")
        return live

    def _fallback(self, task: dict[str, Any], reason: str = "jev_not_configured") -> Decision:
        explicit = str(task.get("role", "")).strip().lower()
        role = explicit if explicit in VALID_ROLES else self._heuristic_role(task)
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        text = self._task_text(task).lower()
        high_risk = any(word in text for word in (
            "delete", "drop database", "production deploy", "credential", "secret", "payment", "destructive",
        ))
        needs_escalation = high_risk or any(word in text for word in (
            "architecture", "security", "release authority", "high risk", "breaking change",
        ))
        effective = role
        if self.mode == "assist" and metadata.get("decision_mode") == "auto":
            effective = role
        return Decision(
            source="heuristic",
            recommended_role=role,
            effective_role=effective,
            operational_risk="high" if high_risk else "moderate" if needs_escalation else "low",
            needs_escalation=needs_escalation,
            needs_review=True,
            confidence=1.0 if explicit in VALID_ROLES else 0.60,
            model=None,
            mode=self.mode,
            reason=reason,
        )

    def _heuristic_role(self, task: dict[str, Any]) -> str:
        text = self._task_text(task).lower()
        if any(word in text for word in ("code", "implement", "build", "fix", "test", "refactor")):
            return "coding"
        if any(word in text for word in ("review", "audit", "qa", "validate")):
            return "review"
        if any(word in text for word in ("architecture", "strategy", "reason", "design")):
            return "reasoning"
        return "general"

    @staticmethod
    def _task_text(task: dict[str, Any]) -> str:
        return "\n".join((
            str(task.get("title", "")),
            str(task.get("objective", "")),
            str(task.get("role", "")),
        ))

    @staticmethod
    def _safe_state(task: dict[str, Any]) -> dict[str, Any]:
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        return {
            "title": str(task.get("title", ""))[:500],
            "objective": str(task.get("objective", ""))[:5000],
            "explicit_role": str(task.get("role", "")),
            "project_id": task.get("project_id"),
            "backend": metadata.get("backend"),
            "lane": metadata.get("lane"),
            "decision_mode": metadata.get("decision_mode"),
        }

    def _call_jev(self, task: dict[str, Any], api_key: str) -> Decision:
        payload = {
            "state": self._safe_state(task),
            "model": MODEL,
            "questions": {
                "recommended_role": {
                    "type": "choice",
                    "instructions": "Which MIGZ Orchestra execution role best fits this task?",
                    "criteria": {
                        "fast": "Tiny, low-risk, fast task",
                        "triage": "Classify or inspect before execution",
                        "coding": "Implement, fix, refactor, or test code",
                        "review": "Independent QA, audit, or verification",
                        "reasoning": "Architecture, strategy, or complex reasoning",
                        "general": "General task that does not fit another role",
                    },
                },
                "operational_risk": {
                    "type": "score",
                    "instructions": "Operational risk if this task is executed automatically",
                    "criteria": ["Low and reversible", "Moderate", "High or destructive"],
                },
                "needs_escalation": {
                    "type": "noul",
                    "instructions": "This task requires Sol-level escalation or human attention",
                },
                "needs_review": {
                    "type": "noul",
                    "instructions": "This task requires independent Terra review after execution",
                },
            },
        }
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with self._urlopen(request, timeout=12) as response:
            raw = json.load(response)
        answers = raw.get("answers")
        if not isinstance(answers, dict):
            raise ValueError("missing answers")

        role_answer = answers.get("recommended_role") or {}
        recommended = str(role_answer.get("choice", "")).strip().lower()
        if recommended not in VALID_ROLES:
            raise ValueError("invalid recommended role")
        confidence = self._unit_float(role_answer.get("confidence"), default=0.0)

        risk_answer = answers.get("operational_risk") or {}
        try:
            risk_score = float(risk_answer.get("score", 0.0))
        except (TypeError, ValueError):
            risk_score = 0.0
        risk = "high" if risk_score >= 1.5 else "moderate" if risk_score >= 0.5 else "low"

        escalation = self._unit_float((answers.get("needs_escalation") or {}).get("noul"), default=0.0) >= 0.5
        review = self._unit_float((answers.get("needs_review") or {}).get("noul"), default=1.0) >= 0.5
        explicit = str(task.get("role", "")).strip().lower()
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        auto = self.mode == "assist" and metadata.get("decision_mode") == "auto"
        auto_allowed = auto and risk != "high" and not escalation
        effective = recommended if auto_allowed or explicit not in VALID_ROLES else explicit
        return Decision(
            source="jev",
            recommended_role=recommended,
            effective_role=effective,
            operational_risk=risk,
            needs_escalation=escalation,
            needs_review=review,
            confidence=confidence,
            model=str(raw.get("model") or MODEL),
            mode=self.mode,
            reason="live_decision",
        )

    @staticmethod
    def _unit_float(value: Any, *, default: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return min(max(number, 0.0), 1.0)
