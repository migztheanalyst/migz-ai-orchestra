## What changed?

Describe the problem and the smallest useful solution.

## Why?

Explain the user or maintainer impact.

## Scope

List the files/subsystems intentionally changed and anything deliberately left out.

## Verification

- [ ] Unit tests pass
- [ ] Core entrypoint smoke passes
- [ ] V4 smoke passes
- [ ] Public safety scan passes
- [ ] Docs link integrity passes
- [ ] Release reviewer passes when relevant
- [ ] `git diff --check` passes
- [ ] New backend/provider changes include bounded canary coverage
- [ ] No secrets, personal paths, runtime state, or generated private evidence are committed

## Security / trust-boundary impact

Describe any new command execution, network access, writable paths, credentials, provider authority, or release-path changes. Write `None` if not applicable.

## Claims / benchmarking

If this PR introduces performance, reliability, adoption, download, dependency, or contributor claims, link the reproducible/public source. Otherwise write `None`.

## Evidence

Add sanitized evidence or reproduction steps when useful. Follow [docs/benchmarking.md](../docs/benchmarking.md) for benchmark claims.
