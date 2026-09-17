#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/conductor${PYTHONPATH:+:$PYTHONPATH}"

PULL_MODELS=1
WITH_DEEPSEEK=0
FULL_MODELS=0
while (($#)); do
  case "$1" in
    --skip-models) PULL_MODELS=0 ;;
    --with-deepseek) WITH_DEEPSEEK=1 ;;
    --full-models) FULL_MODELS=1 ;;
    -h|--help)
      echo "Usage: ./scripts/setup.sh [--skip-models] [--full-models] [--with-deepseek]"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

for cmd in python3 git curl; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd" >&2; exit 2; }
done

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required")
print(f"Python: {sys.version.split()[0]}")
PY

mkdir -p "$ROOT/tasks" "$ROOT/state" "$ROOT/evidence" "$ROOT/logs"
for status in pending running review passed blocked; do
  mkdir -p "$ROOT/tasks/$status"
done

OLLAMA_BASE="$(python3 - <<'PY'
from runtime_env import resolve_ollama_base
print(resolve_ollama_base())
PY
)"
echo "Ollama endpoint: $OLLAMA_BASE"

if ! curl -fsS --max-time 4 "$OLLAMA_BASE/api/tags" >/dev/null; then
  cat >&2 <<EOF
Ollama is not reachable at $OLLAMA_BASE.
Install/start Ollama, then rerun setup.
Docs: https://ollama.com/download
Override endpoint with OLLAMA_BASE_URL if needed.
EOF
  exit 2
fi

pull_model() {
  local model="$1"
  echo "Ensuring model: $model"
  if command -v ollama >/dev/null 2>&1; then
    OLLAMA_HOST="$OLLAMA_BASE" ollama pull "$model"
  else
    MODEL="$model" OLLAMA_BASE="$OLLAMA_BASE" python3 - <<'PY'
import json, os, urllib.request
base=os.environ['OLLAMA_BASE'].rstrip('/')
model=os.environ['MODEL']
req=urllib.request.Request(
    base + '/api/pull',
    data=json.dumps({'name': model, 'stream': False}).encode(),
    headers={'Content-Type':'application/json'}, method='POST')
with urllib.request.urlopen(req, timeout=3600) as response:
    payload=json.load(response)
if payload.get('status') not in {'success','pulling manifest'} and 'status' in payload:
    print(payload)
print(f"Ready: {model}")
PY
  fi
}

if [[ "$PULL_MODELS" == "1" ]]; then
  pull_model "qwen2.5-coder:3b"
  if [[ "$FULL_MODELS" == "1" ]]; then
    pull_model "qwen2.5-coder:7b"
    pull_model "qwen3.5:4b"
  fi
  if [[ "$WITH_DEEPSEEK" == "1" ]]; then
    pull_model "deepseek-r1:1.5b"
  fi
fi

chmod +x "$ROOT/orchestra" "$ROOT/scripts/setup.sh"

echo
echo "Running core health check..."
python3 "$ROOT/conductor/health_check.py"
echo
echo "Setup complete."
echo "Next: ./orchestra doctor"
echo "Optional live verification: ./orchestra doctor --probe"
