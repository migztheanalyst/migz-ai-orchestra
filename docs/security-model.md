# Security Model

The Orchestra assumes model output is untrusted until constrained and verified.

## Core controls

- isolated Git worktrees for implementation
- explicit allowed-scope checks before accepting changes
- no `shell=True` command execution in the control plane
- bounded provider calls and hard timeouts
- task-state transition validation
- deterministic evidence capture
- independent test/review stages
- fail-closed behavior for unavailable or unsafe backends
- runtime state, evidence, and secrets excluded from Git

## Trust boundaries

A backend may propose or implement changes only inside its assigned workspace. Passing a model call does not imply a safe change. The backend change guard, configured tests, reviewer, and release gate remain separate controls.

Optional integrations must never make credentials part of evidence or logs. New integrations should store secrets outside the repository and expose only sanitized status.

## Public-repo safety

`scripts/public_safety_scan.py` rejects known personal paths, secret-like files, generated runtime state, and retired hosted-provider references before release.
