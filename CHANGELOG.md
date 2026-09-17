# Changelog

All notable public changes are documented here.

## [4.0.0] - Unreleased

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
