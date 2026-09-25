# Benchmarking

MIGZ AI Orchestra separates **engineering benchmarks** from **adoption metrics**. A fast agent is not necessarily a safe or reproducible delivery system.

## What to benchmark

The repository includes stress, smoke, and failure-oriented utilities that can be used to measure:

- deterministic task-state behavior
- bounded retries and fallbacks
- recovery after interrupted processes
- release-gate behavior
- entrypoint reliability
- backend/provider health where available

Useful commands include:

```bash
python scripts/core_entrypoint_smoke.py
python scripts/core_stress.py
python scripts/core_fallback_canary.py
python scripts/v4_smoke.py
python scripts/v2_failure_matrix.py
```

## Reporting a benchmark

A benchmark report should include:

1. exact commit SHA
2. operating system and Python version
3. CPU/RAM only when performance is relevant
4. models/providers and exact versions when a live backend is tested
5. command and parameters
6. pass/fail criteria defined before the run
7. raw or summarized results sufficient to reproduce the conclusion

## Claims policy

Do not publish a number as a project benchmark unless it can be traced to a reproducible run.

In particular:

- stars are not users
- clones are not installations
- benchmark fixtures are not production workloads
- maintainer use is not independent third-party adoption
- a model's self-evaluation is not independent QA

Comparative claims should use the same task set, environment, timeout policy, and scoring method across systems.

## Current public baseline

The repository currently publishes deterministic tests and stress/canary utilities, but it does **not** claim a broad independent benchmark corpus or large downstream adoption.

That distinction is intentional. As external users contribute reproducible results, this document can link validated benchmark reports without rewriting historical claims.

## Contributing results

Open an issue or pull request with a concise methodology and reproducible artifacts. Sensitive credentials, private source code, or machine-specific evidence should not be committed.
