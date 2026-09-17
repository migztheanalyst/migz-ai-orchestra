#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${TYPESAFE_API_KEY:-}" ]]; then
  printf 'TypeSafe API key (hidden, not saved): '
  IFS= read -r -s TYPESAFE_API_KEY
  printf '\n'
  export TYPESAFE_API_KEY
fi

if [[ -z "$TYPESAFE_API_KEY" ]]; then
  echo 'JEV_SESSION: BLOCKED_EXTERNAL_CREDENTIAL'
  exit 2
fi

python3 scripts/jev_canary.py

echo 'JEV_SESSION: CANARY PASS'
echo 'Opening a child WSL shell with Jev enabled for this session only.'
echo 'Exit this shell to discard the credential from the child session.'
exec bash
