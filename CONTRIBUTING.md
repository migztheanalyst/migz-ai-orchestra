# Contributing to MIGZ AI ORCHESTRA

Thanks for helping build a safer, more extensible local AI orchestration layer.

## Start here

1. Fork the repository and create a focused branch.
2. Run `./orchestra setup --skip-models` if your local models are already installed.
3. Run `python3 -m unittest discover -s tests -p 'test_*.py' -q`.
4. Run `python3 scripts/public_safety_scan.py`.
5. Keep one concern per pull request.

## Development rules

- Never commit secrets, tokens, personal paths, runtime state, or generated evidence.
- New backends must be optional and fail closed when unavailable.
- Installing a tool is not proof of health; add a bounded live canary.
- All command execution must use explicit argument lists with `shell=False`.
- Workspace boundaries and allowed scopes must remain enforced.
- Preserve independent testing/review paths; builders do not approve themselves.
- Prefer local/free defaults. External integrations belong behind explicit adapters.

## Pull-request checklist

Before opening a PR:

- `python3 -m compileall -q conductor scripts tests`
- `python3 -m unittest discover -s tests -p 'test_*.py' -q`
- `python3 scripts/core_entrypoint_smoke.py`
- `python3 scripts/v4_smoke.py`
- `python3 scripts/public_safety_scan.py`
- `python3 conductor/release_reviewer.py .`
- `git diff --check`

If your change touches a live backend, also include reproducible canary evidence in the PR description. Do not commit machine-specific evidence files.

## Good first contributions

Documentation, platform portability, test coverage, backend adapters, observability, scheduling, and UX improvements are welcome. For a new provider/backend, start with `docs/adding-a-backend.md`.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
