#!/usr/bin/env python3
"""Direct, bounded Hermes advisory agent for MIGZ AI Orchestra."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from agent_backend_router import AgentBackendRouter, HEALTHY, BackendUnavailable


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    router = AgentBackendRouter(repo=ROOT)
    if args.canary:
        result = router.bounded_hermes_probe(timeout=args.timeout)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        raise SystemExit(0 if result.get("status") == HEALTHY else 1)
    prompt = " ".join(args.prompt).strip() or sys.stdin.read().strip()
    if not prompt:
        parser.error("provide a prompt or pipe one on stdin")
    try:
        result = router.run_hermes_advisory(prompt, timeout=args.timeout)
    except BackendUnavailable as exc:
        print(f"HERMES_AGENT: BLOCKED | {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(result["response"])
    print(f"HERMES_AGENT: PASS | {result['model']} | {result['elapsed_seconds']}s", file=sys.stderr)


if __name__ == "__main__":
    main()
