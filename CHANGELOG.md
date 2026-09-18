# Changelog

All notable public changes are documented here.

## [4.1.0] - 2026-09-19

### Added

- shared bounded subprocess primitives for deterministic timeout, environment, and live-log handling
- package-import regression coverage in a fresh Python process
- explicit stale-worktree recovery with preservation of dirty and uniquely committed task work
- content-level evidence hashes that bind captured task evidence to the exact committed file contents
- recovery/orchestrator regression coverage for dual-store crash windows and rollback behavior

### Changed

- project-scoped scheduling and the global TaskStore now reconcile fail-closed across enqueue, claim, recovery, and Maestro exit paths
- Backend Change Guard must pass before evidence can reach READY_TO_COMMIT
- Ollama endpoint resolution now works across configured endpoints, localhost, and WSL without assuming WSL-only networking
- runtime subprocess usage is centralized behind the bounded process runner
- retry logic may safely reuse an old task branch only when it contains no commits unique from the current source branch

### Fixed

- prevented stale recovery from deleting dirty worktrees or task branches with preserved commits
- closed the crash window between ProjectScheduler.claim() and global TaskStore claim
- closed the post-Maestro split-state window where one task store could become terminal while the other remained nonterminal
- prevented child-process leakage when live heartbeat callbacks fail
- corrected backend failure classification for output truncation / done_reason=length
- removed test-order masking from package imports

## [4.0.0] - 2026-09-17

### Added

- public, local-first Open Orchestra baseline
- portable runtime discovery for Linux, macOS, Windows, and WSL
- unified `orchestra` / `orchestra.ps1` command wrappers
- Linux/macOS/WSL and Windows setup scripts
- public safety scanner
- portable release reviewer
- GitHub Actions CI, CodeQL, Dependabot, issue/PR templates
- contribution, security, support, architecture, and integration documentation

### Changed

- optional integrations no longer determine core readiness
- runtime paths are discovered instead of hard-coded to one machine
- public releases use a clean history independent of private development history

### Removed

- paid hosted-provider runtime paths from the public core
- machine-specific Telegram/Codex skill paths from public release gates
