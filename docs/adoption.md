# Adoption and Project Maturity

MIGZ AI Orchestra became a public open-source project in September 2026. It is actively maintained, but public ecosystem adoption is still early.

## Current status

The repository is the public core of a local-first orchestration workflow used by its maintainer to coordinate and verify AI-assisted software delivery across multiple projects.

The public project currently focuses on:

- a stable and inspectable control plane
- local-first execution
- isolated Git worktrees
- bounded backend routing
- independent tests and review
- explicit release gates
- contributor-ready integration boundaries

## What we do not claim

At this stage the project does not claim:

- hundreds of dependent repositories
- hundreds of thousands of package downloads
- a large external contributor community
- independent validation of every supported integration
- production suitability for every environment

Public adoption metrics should be read directly from GitHub or other linked registries rather than inferred from internal usage.

## Why publish early

Agentic software tooling changes quickly. Publishing the control plane early allows its safety assumptions, failure behavior, interfaces, and tests to be reviewed while the architecture is still adaptable.

## Evidence of maturity

Repository maturity is demonstrated through artifacts that can be inspected directly:

- MIT license
- public CI and CodeQL workflows
- security policy and threat model
- contribution and governance documentation
- deterministic test suite
- smoke, stress, and fallback canaries
- release reviewer and public-safety scan
- documented maintainer responsibilities

See [reproducibility.md](reproducibility.md), [benchmarking.md](benchmarking.md), and [../GOVERNANCE.md](../GOVERNANCE.md).

## External users and contributors

External use, integrations, reproduction reports, and pull requests are welcome. When verifiable external adoption data becomes available, it should be added here with a source and date rather than estimated.

For contribution paths, see [../CONTRIBUTING.md](../CONTRIBUTING.md).
