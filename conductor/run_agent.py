import json
import sys
import urllib.request

from model_router import route_model
from runtime_env import resolve_ollama_base


def call_ollama(model, prompt):
    base_url = resolve_ollama_base()

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a worker inside MIGZ AI ORCHESTRA. "
                    "Follow the task precisely. Do not invent results."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.1
        }
    }

    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(
        request,
        timeout=600
    ) as response:
        return json.load(response)


def main():
    if len(sys.argv) < 3:
        print(
            'Usage: python3 conductor/run_agent.py '
            '<role> "<task>"'
        )
        raise SystemExit(1)

    role = sys.argv[1]
    task = " ".join(sys.argv[2:])

    try:
        model = route_model(role)

        print("=== MIGZ AI AGENT ===")
        print(f"ROLE   : {role}")
        print(f"MODEL  : {model}")
        print("STATUS : RUNNING")
        print()

        result = call_ollama(model, task)

        answer = result["message"]["content"].strip()

        print("=== RESULT ===")
        print(answer)
        print()
        print("STATUS : PASS")

    except Exception as exc:
        print()
        print("STATUS : FAIL")
        print(f"ERROR  : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
