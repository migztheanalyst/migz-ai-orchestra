# Reproducibility

MIGZ AI Orchestra treats reproducibility as part of release quality. A successful agent response is not, by itself, evidence that a software change is valid.

## Reproducible local gate

From a clean checkout with Python 3.11+:

```bash
python -m compileall -q conductor scripts tests
python -m unittest discover -s tests -p 'test_*.py' -q
python scripts/public_safety_scan.py
python scripts/check_docs_links.py
python scripts/core_entrypoint_smoke.py
python conductor/release_reviewer.py .
git diff --check
```

The default checks do not require a paid hosted model provider.

## Live-runtime verification

Machines with Ollama and optional backends can additionally run:

```bash
./orchestra doctor --probe
./orchestra preflight
./orchestra release-check --live
```

Live checks verify runtime/provider health. They are intentionally separated from deterministic CI so external availability does not redefine the core test baseline.

## Evidence model

For a governed task, evidence should be attributable to:

- the exact repository/worktree
- the task objective and allowed scope
- implementation outcome
- test/review outcome
- release decision
- commit or blocked terminal state

Runtime evidence, credentials, local paths, and generated logs are not committed to the public repository unless they are deliberately sanitized fixtures.

## What a release claim means

A release claim should identify the exact commit or tag and the checks that passed. A claim such as "verified" must not mean only that an AI backend returned success.

When a check is environment-dependent, documentation should distinguish:

- deterministic repository checks
- live provider checks
- platform-specific checks
- external or manual validation

## Independent reproduction

Contributors are encouraged to reproduce the deterministic gate on a clean machine or ephemeral environment and report:

- operating system
- Python version
- commit SHA
- commands executed
- unexpected differences

Reproduction reports can be submitted as issues or pull-request evidence.

## Known limitation

The project is early in public adoption. Reproducibility documentation describes the project's engineering contract; it does not imply independent third-party validation unless such validation is linked explicitly.
