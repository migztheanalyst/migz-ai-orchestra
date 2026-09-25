# Architecture

MIGZ AI Orchestra separates **decision**, **execution**, **verification**, and **release authority** so one agent does not silently own the whole lifecycle.

```text
User / CLI
   ↓
Decision layer (heuristic by default, JEV optional)
   ↓
Maestro / scheduler
   ↓
Backend router
   ├─ Native local model
   ├─ Aider (optional)
   ├─ OpenHands (optional)
   ├─ Hermes advisory (optional)
   └─ DeepSeek local advisory (optional)
   ↓
Isolated Git worktree
   ↓
Change guard
   ↓
Tests / independent QA
   ↓
Independent reviewer
   ↓
Evidence → verified commit or explicit block
```

The public core is local-first. Optional integrations may add capabilities but are not required for core health.

## Control plane

The control plane owns the state machine and the rules that determine whether a task can advance. Backends are execution providers, not release authorities.

Core responsibilities include:

- task creation and state transitions
- project/workspace resolution
- backend selection and bounded fallback
- process execution and timeout handling
- allowed-scope validation
- test/review orchestration
- evidence generation
- release decision and commit handling

## Execution isolation

Each implementation task is designed to run in an isolated Git worktree. Isolation makes the proposed change inspectable without silently mutating the authoritative branch.

The change guard compares resulting paths with the task's permitted scope before a change can progress.

## Verification

Verification is deliberately separate from implementation.

A typical task moves through:

1. explicit objective and scope
2. isolated implementation
3. allowed-scope validation
4. deterministic tests
5. independent review
6. evidence capture
7. verified commit or blocked terminal state

See [reproducibility.md](reproducibility.md).

## Backend abstraction

Backends are optional adapters behind the router. A backend is expected to expose bounded execution and machine-readable outcomes without owning task-state transitions.

A new backend should not:

- bypass workspace isolation
- bypass scope validation
- declare a release successful
- require credentials for the default core to start
- silently fall back to an unrelated provider

See [adding-a-backend.md](adding-a-backend.md).

## Decision layers

The default system can use deterministic or heuristic routing. Optional decision systems can advise routing or risk assessment, but their output remains subject to the same state and release controls.

## Failure model

Failures should be explicit and bounded.

Examples include:

- provider unavailable
- provider timeout
- implementation changed disallowed files
- tests failed
- review failed
- evidence could not be produced
- release gate rejected the task

A fallback is permitted only when configured for that failure class. A fallback response does not erase the original failure from evidence.

## Design principle

Orchestra optimizes for **inspectable delivery**, not maximum autonomous action.

The architecture intentionally adds friction at the boundaries where an autonomous coding system can otherwise turn a plausible response into an unverified repository mutation.
