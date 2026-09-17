import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderLane:
    name: str
    status: str
    provider: str
    model: str | None = None
    base_url: str | None = None
    reason: str = ""


FAILURE_CLASSES = {
    "TRANSIENT", "IMPLEMENTATION_FAILURE", "EXTERNAL_CREDENTIAL", "SAFETY_BLOCKER"
}

BACKEND_FAILURE_CLASSES = {
    "TRANSIENT_PROVIDER", "MODEL_TIMEOUT", "MODEL_UNAVAILABLE",
    "OUTPUT_TRUNCATED", "MALFORMED_OUTPUT", "BACKEND_UNAVAILABLE",
    "EXTERNAL_CREDENTIAL", "SECURITY_BLOCKER", "IMPLEMENTATION_FAILURE",
}


def _get_json(url, timeout=15, payload=None):
    data = None
    headers = {}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_json_bounded(url, payload, timeout):
    command = [
        "curl", "-fsS", "--max-time", str(float(timeout)),
        "-H", "Content-Type: application/json",
        "--data-binary", "@-", url,
    ]
    result = subprocess.run(
        command, input=json.dumps(payload), capture_output=True, text=True,
        timeout=float(timeout) + 5, shell=False,
    )
    if result.returncode != 0:
        raise TimeoutError(result.stderr.strip() or f"curl exit {result.returncode}")
    return json.loads(result.stdout)


def ollama_models(base_url):
    data = _get_json(base_url.rstrip("/") + "/api/tags")
    return {m.get("name") for m in data.get("models", [])}


def probe_model(ollama_base, model, timeout=30, require_exact=True, disable_reasoning=False):
    started = time.monotonic()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply exactly: PROVIDER_OK"}],
        "stream": False,
        "temperature": 0,
        "max_tokens": 8,
    }
    if disable_reasoning:
        payload["reasoning"] = {"enabled": False, "effort": "none"}
    try:
        raw = _post_json_bounded(ollama_base.rstrip("/") + "/v1/chat/completions", payload, timeout)
        choices = raw.get("choices") or []
        content = str((choices[0].get("message") or {}).get("content", "") if choices else "").strip()
        if content == "PROVIDER_OK":
            return {"status": "PASS", "elapsed_seconds": round(time.monotonic() - started, 3), "reason": "live probe passed"}
        if content and not require_exact:
            return {"status": "PASS", "elapsed_seconds": round(time.monotonic() - started, 3), "reason": "live probe responded; sentinel variance tolerated for advisory lane"}
        return {"status": "UNAVAILABLE", "elapsed_seconds": round(time.monotonic() - started, 3), "reason": "unexpected probe response"}
    except Exception as exc:
        return {"status": "UNAVAILABLE", "elapsed_seconds": round(time.monotonic() - started, 3), "reason": f"{type(exc).__name__}: {exc}"}



def _release_model(ollama_base, model):
    try:
        _post_json_bounded(ollama_base.rstrip("/") + "/api/generate", {"model": model, "keep_alive": 0}, 10)
        return True
    except Exception:
        return False

def detect_lanes(
    ollama_base, probe=False, timeout=75, release_after_probe=False,
    probe_names=None,
):
    models = ollama_models(ollama_base)
    selected = None if probe_names is None else set(probe_names)
    lanes = {
        "qwen-fast": ProviderLane("qwen-fast", "PASS", "ollama", "qwen2.5-coder:3b", ollama_base),
        "qwen-coding": ProviderLane("qwen-coding", "PASS", "ollama", "qwen2.5-coder:7b", ollama_base),
        "qwen-reasoning": ProviderLane("qwen-reasoning", "PASS", "ollama", "qwen3.5:4b", ollama_base),
    }
    for key, lane in list(lanes.items()):
        if lane.model not in models:
            lanes[key] = ProviderLane(lane.name, "UNAVAILABLE", lane.provider, lane.model, lane.base_url, "model not installed")
            continue
        should_probe = probe and (selected is None or key in selected)
        if probe and not should_probe:
            lanes[key] = ProviderLane(lane.name, "AVAILABLE", lane.provider, lane.model, lane.base_url, "installed; extended live probe not requested")
            continue
        if should_probe:
            lane_timeout = max(timeout, 150) if key == "qwen-coding" else max(timeout, 120) if key == "qwen-reasoning" else timeout
            result = probe_model(
                ollama_base, lane.model, timeout=lane_timeout,
                disable_reasoning=(key == "qwen-reasoning"),
            )
            lanes[key] = ProviderLane(
                lane.name, result["status"], lane.provider, lane.model, lane.base_url,
                f"{result['reason']}; elapsed={result['elapsed_seconds']}s",
            )
            if release_after_probe:
                _release_model(ollama_base, lane.model)
    deepseek = sorted(m for m in models if m and m.lower().startswith("deepseek"))
    if deepseek:
        deepseek_model = deepseek[0]
        deepseek_status = "PASS"
        deepseek_reason = "local model installed"
        should_probe = probe and (selected is None or "deepseek" in selected)
        if probe and not should_probe:
            deepseek_status = "AVAILABLE"
            deepseek_reason = "installed; extended live probe not requested"
        elif should_probe:
            result = probe_model(ollama_base, deepseek_model, timeout=max(timeout, 60), require_exact=False)
            deepseek_status = result["status"]
            deepseek_reason = f"{result['reason']}; elapsed={result['elapsed_seconds']}s"
            if release_after_probe:
                _release_model(ollama_base, deepseek_model)
        lanes["deepseek"] = ProviderLane(
            "deepseek", deepseek_status, "ollama", deepseek_model, ollama_base, deepseek_reason
        )
    else:
        lanes["deepseek"] = ProviderLane(
            "deepseek", "UNAVAILABLE", "ollama",
            reason="optional local DeepSeek model not installed"
        )
    return lanes


def choose_lane(lanes, preferred):
    order = [preferred, "qwen-reasoning", "qwen-coding", "qwen-fast"]
    for name in order:
        lane = lanes.get(name)
        if lane and lane.status == "PASS":
            return lane
    raise RuntimeError("No healthy provider lane")


def retry_class(error_text):
    return "transient" if classify_failure(error_text) == "TRANSIENT" else "terminal"


def classify_failure(error_text):
    text = str(error_text).lower()
    if any(x in text for x in ("safety", "unsafe", "path escapes", "secret", "arbitrary command", "security blocker")):
        return "SAFETY_BLOCKER"
    if any(x in text for x in ("api key", "authentication", "unauthorized", "401", "credential", "billing")):
        return "EXTERNAL_CREDENTIAL"
    if any(x in text for x in ("timeout", "timed out", "connection reset", "connection refused", "temporarily unavailable", "overload", "rate limit", "503", "502", "429", "provider unavailable")):
        return "TRANSIENT"
    if any(x in text for x in ("truncated", "malformed", "invalid json", "invalid schema", "builder failed", "tester failed", "reviewer failed")):
        return "IMPLEMENTATION_FAILURE"
    return "IMPLEMENTATION_FAILURE"


def classify_backend_failure(error_text):
    """Classify backend failures without changing the V1 classifier."""
    text = str(error_text).lower()
    if any(x in text for x in ("safety", "unsafe", "path escapes", "secret", "arbitrary command", "security blocker")):
        return "SECURITY_BLOCKER"
    if any(x in text for x in ("api key", "authentication", "unauthorized", "401", "credential", "billing")):
        return "EXTERNAL_CREDENTIAL"
    if any(x in text for x in ("truncated", "done_reason.*length", "output length")):
        return "OUTPUT_TRUNCATED"
    if any(x in text for x in ("malformed", "invalid json", "invalid schema", "json decode", "unexpected probe response")):
        return "MALFORMED_OUTPUT"
    if any(x in text for x in ("model not installed", "no model installed", "model missing", "model unavailable")):
        return "MODEL_UNAVAILABLE"
    if any(x in text for x in ("timeout", "timed out", "deadline exceeded")):
        return "MODEL_TIMEOUT"
    if any(x in text for x in ("backend unavailable", "aider unavailable", "hermes unavailable", "no usable native backend")):
        return "BACKEND_UNAVAILABLE"
    if any(x in text for x in ("connection reset", "connection refused", "temporarily unavailable", "overload", "rate limit", "503", "502", "429", "provider unavailable", "ollama_not_running", "bridge_unreachable")):
        return "TRANSIENT_PROVIDER"
    return "IMPLEMENTATION_FAILURE"


def as_json(lanes):
    return {k: vars(v) for k, v in lanes.items()}
