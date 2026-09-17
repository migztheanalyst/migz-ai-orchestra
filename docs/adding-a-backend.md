# Adding a Backend

A backend is not considered production-ready just because its executable exists.

## Required contract

1. Add discovery without hard-coded personal paths.
2. Return a sanitized state: unavailable, available, healthy, or blocked.
3. Add a bounded live canary with a hard timeout.
4. Keep execution inside an isolated workspace.
5. Require explicit `allowed_scope` for coding backends.
6. Route subprocesses with argument lists and `shell=False`.
7. Classify failures so transient provider errors do not look like code defects.
8. Add fallback behavior where appropriate.
9. Add regression tests for discovery, canary, routing, and failure cases.
10. Update `docs/integrations.md` and the README capability matrix.

## Evidence

Canary evidence should include backend, provider/model when non-sensitive, timestamp, bounded latency, result, and safety checks. Never store prompts containing secrets or credentials.

## Review expectations

Backend PRs should explain the trust boundary, required permissions, network access, write scope, timeout policy, and what happens when the backend is unavailable.
