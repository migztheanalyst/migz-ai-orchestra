# Integrations

The public core does not require cloud credentials. Integrations are optional capability layers.

## Codex

Recommended as a top-level planning/final-review authority when available. The public core must still run without it.

## JEV / TypeSafe

Optional typed decision layer. Without credentials, the Orchestra falls back to deterministic heuristics. Never commit TypeSafe credentials.

## Aider

Optional coding backend. Install Aider using its official installer or package instructions, then run the Orchestra canary before treating it as healthy.

## OpenHands

Optional isolated coding backend. A healthy status requires a controlled canary, not merely an installed executable.

## Hermes

Optional advisory/reasoning backend. The Orchestra runs it in a bounded isolated workspace and records only sanitized evidence.

## DeepSeek Local

Optional local advisory model through Ollama. Hosted DeepSeek is not part of the public core.

## Telegram / chat surfaces

External chat surfaces may consume Orchestra telemetry, but they are not required for core operation and should maintain their own credentials/state outside this repository.
