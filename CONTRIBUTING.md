# Contributing to MIGZ AI Orchestra

Thanks for helping build a safer, more extensible local AI orchestration layer.

## Start here

1. Read [GOVERNANCE.md](GOVERNANCE.md) and [docs/security-model.md](docs/security-model.md).
2. Fork the repository or create a focused branch.
3. Run `./orchestra setup --skip-models` if your local models are already installed.
4. Run the deterministic tests and public-safety scan.
5. Keep one concern per pull request.

If you are proposing a new backend or provider, read [docs/adding-a-backend.md](docs/adding-a-backend.md) first.

## Development rules

- Never commit secrets, tokens, personal paths, runtime state, or generated private evidence.
- New backends must be optional and fail closed when unavailable.
- Installing a tool is not proof of health; add a bounded live canary.
- All command execution must use explicit argument lists with `shell=False`.
- Workspace boundaries and allowed scopes must remain enforced.
- Preserve independent testing/review paths; builders do not approve themselves.
- Prefer local/free defaults. External integrations belong behind explicit adapters.
- Do not manufacture benchmark, download, adoption, contributor, or dependency metrics.
## Pull-request checklist

Before opening a PR:

- `python3 -m compileall -q conductor scripts tests`
- `python3 -m unittest discover -s tests -p 'test_*.py' -q`
- `python3 scripts/core_entrypoint_smoke.py`
- `python3 scripts/v4_smoke.py`
- `python3 scripts/public_safety_scan.py`
- `python3 scripts/check_docs_links.py`
- `python3 conductor/release_reviewer.py .`
- `git diff --check`

If your change touches a live backend, include reproducible canary evidence in the PR description. Do not commit machine-specific evidence files.

For claims about performance or reliability, follow [docs/benchmarking.md](docs/benchmarking.md).

## Review expectations

A useful PR description explains:

- the problem being solved
- the intended scope
- important trust-boundary changes
- tests or reproduction steps
- known limitations

Maintainers may request smaller scope, stronger tests, or independent evidence before merge.

## Good first contributions

Documentation, platform portability, test coverage, backend adapters, observability, scheduling, and UX improvements are welcome.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
