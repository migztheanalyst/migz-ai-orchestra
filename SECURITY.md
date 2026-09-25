# Security Policy

Security is a release gate, not an afterthought. MIGZ AI Orchestra assumes model output and external backends are untrusted until constrained and independently verified.

## Supported versions

The latest major public release is the supported baseline. Security fixes may be backported when practical.

| Version | Supported |
| --- | --- |
| 4.x | Yes |
| Earlier | Best effort only |

## Security model

The architectural threat model and trust boundaries are documented in [docs/security-model.md](docs/security-model.md).

High-impact areas include:

- command execution and argument handling
- Git worktree and workspace isolation
- allowed-scope enforcement
- secrets or credential handling
- task-state transitions
- evidence integrity
- backend/provider boundaries
- release-gate bypasses

## Report a vulnerability

Do **not** open a public issue for a suspected vulnerability, secret exposure, sandbox escape, unsafe command execution, credential leak, or workspace-boundary bypass.
Use GitHub private vulnerability reporting when available. If it is unavailable, contact a maintainer privately through the contact method on the maintainer's GitHub profile.

Please include:

- affected version or commit SHA
- operating system/runtime when relevant
- reproduction steps
- expected vs actual behavior
- likely impact
- suggested mitigation, if known

Never include real credentials or sensitive customer/project data in a report.

## Response and disclosure

Maintainers will validate the report, determine affected versions, and coordinate a fix before public disclosure when exploitation risk warrants it.

There is no guaranteed response-time SLA for this community project. Security reports are prioritized by demonstrated impact and reproducibility.

After a safe fix is available, maintainers should publish enough information for users to understand affected versions and the remediation without exposing unnecessary exploit detail.

## Safe research

Good-faith testing against your own local checkout is welcome. Do not test against systems, repositories, credentials, or users you do not own or have permission to assess.
