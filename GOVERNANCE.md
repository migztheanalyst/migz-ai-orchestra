# Governance

MIGZ AI Orchestra is an open-source project maintained in public. Governance is intentionally lightweight while the contributor community is small, but technical authority and release criteria are documented so they can scale with the project.

## Principles

- Decisions should be reviewable from public issues, pull requests, commits, and release notes.
- Maintainers do not treat an AI agent's self-report as evidence that a change is correct.
- Security, reproducibility, and contributor safety take priority over release speed.
- Core functionality must remain usable without private credentials or a mandatory paid model provider.
- Project metrics must be reported honestly; adoption or benchmark numbers are not manufactured.

## Roles

**Lead maintainer** — owns project direction, release decisions, security response, and final merge authority.

**Maintainer** — may triage issues, review and merge scoped changes, maintain documentation and integrations, and participate in releases.

**Contributor** — anyone whose pull request or other contribution is accepted into the project.

Current maintainers are listed in [MAINTAINERS.md](MAINTAINERS.md).
## Decision process

Routine changes use pull-request review and CI. Significant changes should begin with an issue or discussion when they alter:

- trust boundaries or command execution
- workspace isolation or allowed-scope enforcement
- task-state transitions or release gates
- backend/provider interfaces
- evidence format or verification semantics

When maintainers disagree, the lead maintainer records the decision and rationale publicly. As the maintainer group grows, this policy will be revised toward multi-maintainer approval for sensitive changes.

## Release policy

A public release should have:

1. deterministic CI passing on the release commit
2. public-safety scanning passing
3. no known unresolved release-blocking security finding
4. release notes describing user-visible changes and known limitations
5. a reproducible commit/tag reference

See [docs/reproducibility.md](docs/reproducibility.md).

## Security decisions

Security reports are handled according to [SECURITY.md](SECURITY.md). Security-sensitive fixes may be developed privately until disclosure is safe, then documented publicly after release.

## Governance changes

Governance changes are made through pull requests. Material changes should explain why the existing process is insufficient and how the new rule improves reviewability or contributor trust.
