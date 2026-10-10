#!/usr/bin/env bash
# Start the inference service that the agent talks to.
#
# The competition fixes the base image and the EDA toolchain but leaves the
# inference backend, service parameters and context configuration to the team
# (topic guide 3.1.3.2), so those choices are recorded here and nowhere else.
#
# The service must come up with no network access: weights are expected to be
# present already, and this script never downloads anything. Run
# fetch-model.sh once, while the network is still available, to populate the
# model directory.
#
# Usage:  bash serve/start.sh [--model NAME]
set -euo pipefail

MODEL="${LOGICLENS_MODEL_NAME:-qwen2.5-coder:1.5b}"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
BINARY="${OLLAMA_BINARY:-ollama}"

while [ $# -gt 0 ]; do
    case "$1" in
        --model) MODEL="$2"; shift 2 ;;
        --host) HOST="$1"; shift 2 ;;
        --binary) BINARY="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

export OLLAMA_HOST="$HOST"
# Keeping the models on a mounted volume is what makes the image small enough
# to distribute; see serve/README-zh.md.
export OLLAMA_MODELS="${OLLAMA_MODELS:-/models}"

if ! command -v "$BINARY" >/dev/null 2>&1; then
    echo "inference binary not found: $BINARY" >&2
    echo "set OLLAMA_BINARY, or install Ollama into the image" >&2
    exit 127
fi

# Refuse to start if the weights are missing: a container that silently
# downloads at evaluation time would fail in the offline sandbox.
if [ ! -d "$OLLAMA_MODELS" ] || [ -z "$(ls -A "$OLLAMA_MODELS" 2>/dev/null)" ]; then
    echo "no model weights found in $OLLAMA_MODELS" >&2
    echo "the evaluation sandbox has no network, so run serve/fetch-model.sh first" >&2
    exit 1
fi

echo "starting inference service"
echo "  host   : $HOST"
echo "  models : $OLLAMA_MODELS"
echo "  model  : $MODEL"

"$BINARY" serve &
SERVE_PID=$!
trap 'kill "$SERVE_PID" 2>/dev/null || true' EXIT

# Wait for readiness before returning, so the caller can start the agent
# immediately instead of racing the server.
for _ in $(seq 1 60); do
    if python3 - <<'PY' 2>/dev/null
import urllib.request
urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2).read()
PY
    then
        echo "inference service is ready"
        # Record the configuration the run will use, for MODEL.md.
        python3 "$(dirname "$0")/record_service.py" --model "$MODEL" || true
        wait "$SERVE_PID"
        exit 0
    fi
    sleep 1
done

echo "inference service did not become ready within 60s" >&2
exit 1
