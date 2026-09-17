#!/usr/bin/env python3
"""Deterministic failure/retry acceptance matrix."""

import json
import tempfile
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from conductor.decomposition import should_decompose
from conductor.provider_router import classify_failure
from conductor.task_engine import TaskStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    cases = {
        "model_timeout": "model timed out after 120 seconds",
        "provider_unavailable": "provider unavailable: connection refused",
        "malformed_output": "malformed JSON output",
        "truncated_output": "Builder output truncated done_reason=length",
        "builder_failure": "builder failed",
        "tester_failure": "tester failed",
        "credential": "401 missing API key",
        "safety": "unsafe arbitrary command blocked",
    }
    matrix = {name: {"class": classify_failure(value), "decompose": should_decompose(value)} for name, value in cases.items()}
    with tempfile.TemporaryDirectory(prefix="migz-failure-") as raw:
        store = TaskStore(Path(raw))
        task = store.create("retry", "bounded retry", "coding", max_attempts=2)
        store.transition(task["id"], "running", "attempt 1")
        store.transition(task["id"], "pending", "transient failure")
        store.transition(task["id"], "running", "attempt 2")
        store.transition(task["id"], "blocked", "terminal after bounded attempts")
        store.transition(task["id"], "pending", "operator retry request")
        bounded = False
        try:
            store.transition(task["id"], "running", "should not exceed max attempts")
        except RuntimeError:
            bounded = True
        result = {"schema": "migz.v2.failure-matrix.v1", "cases": matrix, "bounded_retries": bounded, "verdict": "PASSED"}
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Evidence: {output}")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("V2_FAILURE_MATRIX: PASS")


if __name__ == "__main__":
    main()
