"""Portable Ollama health diagnostics."""

import json
import socket
import time
import urllib.error
import urllib.request

from runtime_env import ollama_candidates

REQUIRED_MODELS = [
    "qwen2.5-coder:3b",
]


def diagnose_ollama(retries=1, timeout=8):
    attempts = []
    candidates = ollama_candidates()
    for attempt in range(1, int(retries) + 1):
        for base_url in candidates:
            try:
                with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout) as response:
                    data = json.load(response)
                available = sorted(
                    model.get("name") for model in data.get("models", []) if model.get("name")
                )
                missing = [model for model in REQUIRED_MODELS if model not in available]
                return {
                    "status": "MODEL_MISSING" if missing else "PASS",
                    "endpoint": base_url,
                    "attempts": attempts + [{"attempt": attempt, "endpoint": base_url, "status": "PASS"}],
                    "models": available,
                    "missing": missing,
                }
            except urllib.error.HTTPError as exc:
                attempts.append({"attempt": attempt, "endpoint": base_url, "status": "API_ERROR", "http_status": exc.code})
            except (ConnectionRefusedError, ConnectionResetError, socket.timeout) as exc:
                attempts.append({"attempt": attempt, "endpoint": base_url, "status": "OLLAMA_NOT_RUNNING", "error": type(exc).__name__})
            except urllib.error.URLError as exc:
                attempts.append({"attempt": attempt, "endpoint": base_url, "status": "BRIDGE_UNREACHABLE", "error": type(getattr(exc, "reason", exc)).__name__})
            except Exception as exc:
                attempts.append({"attempt": attempt, "endpoint": base_url, "status": "API_ERROR", "error": type(exc).__name__})
        if attempt < retries:
            time.sleep(0.5)
    return {
        "status": attempts[-1]["status"] if attempts else "BRIDGE_UNREACHABLE",
        "endpoint": candidates[0] if candidates else None,
        "attempts": attempts,
        "models": [],
        "missing": list(REQUIRED_MODELS),
    }


def main():
    diagnosis = diagnose_ollama()
    print("=== MIGZ AI ORCHESTRA HEALTH CHECK ===")
    print(f"Ollama endpoint : {diagnosis.get('endpoint')}")
    print(f"Ollama API      : {diagnosis.get('status')}")
    if diagnosis.get("status") != "PASS":
        if diagnosis.get("missing"):
            print("Missing required models:")
            for model in diagnosis["missing"]:
                print(f"  - {model}")
        print("HEALTH          : FAIL")
        raise SystemExit(1)

    print("Required models : PASS")
    print("HEALTH          : PASS")


if __name__ == "__main__":
    main()
