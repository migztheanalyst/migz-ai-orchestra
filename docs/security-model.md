# Security Model

MIGZ AI Orchestra assumes model output, tool output, and external backends are **untrusted until constrained and independently verified**.

This document describes the public core's trust model. It is not a claim that every optional integration provides the same isolation guarantees.

## Assets to protect

- source repositories and Git history
- credentials and environment secrets
- task intent and allowed change scope
- evidence and release decisions
- host filesystem outside the assigned workspace
- integrity of tests and review stages

## Trust boundaries

The control plane is responsible for task state, routing, workspace selection, scope validation, verification, evidence, and release decisions.

A backend may propose or implement changes only inside its assigned workspace. A successful model/provider response does not imply that the resulting change is safe, correct, in scope, or releasable.

Optional integrations are separate trust domains. Their availability or self-reported success cannot bypass the core release gate.

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
## Threats considered

### Scope escape

An agent modifies files outside the requested project or allowed paths.

**Controls:** worktree isolation, workspace validation, allowed-scope change guard, review before release.

### Command injection

Model-generated content causes unintended shell interpretation.

**Controls:** explicit argument lists, `shell=False`, bounded execution paths, review of new command surfaces.

### False-success reporting

A backend claims completion despite failed tests, partial edits, or missing evidence.

**Controls:** independent tests, reviewer stage, evidence packet, terminal failure states.

### Credential exposure

Secrets enter prompts, logs, evidence, commits, or public fixtures.

**Controls:** ignored runtime state, public-safety scan, sanitized status reporting, no credentials in committed evidence.

### Verification tampering

The same actor that writes a change alters or bypasses tests/review to approve itself.

**Controls:** separate builder and verification stages, release reviewer, explicit release authority.

### Unbounded retry or provider failure

A failing backend consumes resources or repeatedly mutates state.

**Controls:** bounded retries, hard timeouts, explicit fallback rules, fail-closed behavior.

## Security invariants

Changes to the control plane should preserve these invariants:

1. A task cannot silently expand its authorized workspace.
2. A backend cannot directly grant itself release authority.
3. Failure remains visible; it is not rewritten as success because a fallback responded.
4. Evidence must refer to the actual task/repository state being released.
5. Optional integrations do not become mandatory for core health.
6. Secret-bearing runtime state remains outside the public repository.

## Public-repository safety

`scripts/public_safety_scan.py` rejects known personal paths, secret-like files, generated runtime state, and retired hosted-provider references before release.

The scan is a guardrail, not a substitute for secret scanning, code review, or GitHub security features.

## Non-goals

The public core does not claim to provide:

- a hardened OS/container sandbox against a malicious local process
- endpoint detection or host security
- protection when users deliberately grant a backend unrestricted credentials
- security guarantees for third-party tools beyond the boundaries enforced by Orchestra

## Reporting vulnerabilities

Follow [../SECURITY.md](../SECURITY.md). Do not publish exploit details in a public issue before maintainers can evaluate and remediate them.
